import os
from src.engine.config.auto_action_config import AutoActionConfig
from src.plugins.detectors.detector import available_detectors
from .camera import _smooth

from .reader import VideoReader
from .writer import FFmpegWriter
from src.engine.analysis.analyzer import VideoAnalyzer
from src.plugins.trackers.tracker import TrackingEngine
from .renderer import Renderer

def preprocess_video_for_dmd(src_path: str, cfg: AutoActionConfig, cancel_event=None):
    """Create an auto-framed temporary MP4 and return (ok, out_path, message)."""
    try:
        import cv2
    except Exception:
        return False, None, "OpenCV not installed (install opencv-python to enable auto action framing)."

    if cfg.detector.lower() not in available_detectors():
        cfg.detector = "person"

    # 1. Reader
    reader = VideoReader(src_path)
    ok, msg = reader.open()
    if not ok:
        return False, None, msg

    # 2. Analyzer
    analyzer = VideoAnalyzer(reader.frame_w, reader.frame_h, cfg)
    analyzer.analyze(reader.cap)

    import logging
    logger = logging.getLogger(__name__)

    initial_start_s = cfg.start_s if cfg.start_s is not None else 0.0
    if initial_start_s > 0:
        reader.set_time(float(initial_start_s) * 1000.0)

    # 3. Writer
    writer = FFmpegWriter(analyzer.out_w, analyzer.out_h, reader.fps)
    ok, msg = writer.open()
    if not ok:
        reader.release()
        return False, None, msg

    # 4. Read First Frame
    ok_first, first_frame_for_intro = reader.read()
    if not ok_first:
        reader.release()
        writer.close()
        return False, None, "Could not read first frame for intro."

    # Intro Frames Calculation
    intro_frames = max(0, int(round(cfg.intro_duration * reader.fps)))
    if reader.total_frames > 0:
        max_intro = max(1, int(reader.total_frames * 0.40))
        intro_frames = min(intro_frames, max_intro)

    if hasattr(analyzer, 'best_detector') and analyzer.best_detector:
        cfg.detector = analyzer.best_detector

    # 5. Tracker
    tracker = TrackingEngine(
        reader.fps, reader.frame_w, reader.frame_h,
        analyzer.effective_frame_top, analyzer.effective_frame_h,
        analyzer.effective_frame_left, analyzer.effective_frame_w,
        analyzer.face_priority_mode, cfg
    )

    # 6. Renderer
    renderer = Renderer(reader.frame_w, reader.frame_h, analyzer.out_w, analyzer.out_h, cfg.bg_sub_enable)

    # State variables
    last_frame = None
    frame_idx = 0
    extra = 0
    src_idx = 0
    _pipe_alive = True
    
    # ── Phase 1: Intro panoramic pan ──────────────────────────────────────────
    cx, cy_center, crop_w_full, crop_h_src = tracker.cam_full_view
    if intro_frames > 0 and _pipe_alive:
        cy_top = crop_h_src / 2.0
        for i in range(intro_frames):
            t_linear = i / max(1, intro_frames - 1)
            t = t_linear * t_linear * (3.0 - 2.0 * t_linear)
            cy = cy_top + t * (cy_center - cy_top)
            cam_intro = (cx, cy, crop_w_full, crop_h_src)
            
            out_frame = renderer.render(first_frame_for_intro, cam_intro)
            if cancel_event and cancel_event.is_set():
                _pipe_alive = False
                break
            if not writer.write_frame(out_frame):
                _pipe_alive = False
                break
            frame_idx += 1
        last_frame = first_frame_for_intro

    reader.set_time(float(initial_start_s) * 1000.0)

    # ── Phase 2: Action tracking ──────────────────────────────────────────────
    cam_prev = tracker.cam_full_view
    cam_now = tracker.cam_full_view

    action_frames = max(1, reader.total_frames - intro_frames)
    required_smoothness = 0.10 ** (1.0 / max(5, action_frames))
    dynamic_smoothness = max(0.50, min(cfg.smoothness, required_smoothness))

    while _pipe_alive:
        if cancel_event and cancel_event.is_set():
            _pipe_alive = False
            break

        ok, frame = reader.read()
        if not ok:
            break

        t = src_idx / reader.fps
        if cfg.end_s is not None and (initial_start_s + t) >= float(cfg.end_s):
            break

        cam_now = tracker.process_frame(frame, cam_prev, src_idx, analyzer.out_w, analyzer.out_h)
        cam = _smooth(cam_prev, cam_now, dynamic_smoothness)
        cam_prev = cam
        last_frame = frame

        out_frame = renderer.render(frame, cam, roi=tracker.last_roi)
        if not writer.write_frame(out_frame):
            _pipe_alive = False
            break

        frame_idx += 1
        src_idx += 1

    # ── Phase 3: Tail extension ───────────────────────────────────────────────
    if last_frame is not None and cam_prev is not None and cam_now is not None and _pipe_alive:
        max_extra = max(1, int(reader.fps * 0.3))
        settle_px = 1.0
        extra = 0
        while extra < max_extra:
            if cancel_event and cancel_event.is_set():
                break

            if cam_prev is None:
                cam_next = cam_now
                displacement = 0.0
            else:
                cam_next = _smooth(cam_prev, cam_now, dynamic_smoothness)
                displacement = max(abs(cam_next[i] - cam_prev[i]) for i in range(4))
                
            cam_prev = cam_next
            out_frame = renderer.render(last_frame, cam_next, is_tail=True)
            if not writer.write_frame(out_frame):
                break
                
            frame_idx += 1
            extra += 1
            if displacement < settle_px:
                break

    # ── Finalise ──────────────────────────────────────────────────────────────
    writer_ok, stderr_hint = writer.close()
    reader.release()

    if not writer_ok or frame_idx <= 0 or not os.path.isfile(writer.out_path):
        return False, None, stderr_hint

    intro_info  = f", intro={cfg.intro_duration:.1f}s" if intro_frames > 0 else ""
    onnx_tag    = " [onnx]" if getattr(tracker.detector, "model_type", "") == "onnx" else ""
    
    _crops = []
    if cfg.auto_bottom_crop or cfg.bottom_crop_pct > 0:
        _crops.append(f"bot={cfg.bottom_crop_pct:.0%}")
    if cfg.auto_top_crop or cfg.top_crop_pct > 0:
        _crops.append(f"top={cfg.top_crop_pct:.0%}")
        
    crop_info = (" crop=" + "+".join(_crops)) if _crops else ""
    smart_tag = " smart" if (cfg.smart_auto_crop or cfg.roi_confidence_min > 0 or cfg.min_subject_dmd_px > 0) else ""
    plat_tag = " plat" if cfg.platformer_mode else ""
    scene_tag = f" scene={analyzer.scene_profile.scene_type}" if analyzer.scene_profile else ""
    
    from src.engine.auto_action.decision_logger import AutoActionDecisionLogger
    
    msg_lines = []
    
    if hasattr(analyzer, "decision_codes"):
        table_str = AutoActionDecisionLogger.process_decisions(src_path, cfg, analyzer, reader)
        msg_lines.append(table_str)
    elif hasattr(analyzer, 'smart_reasons') and analyzer.smart_reasons:
        for reason in analyzer.smart_reasons:
            msg_lines.append(f"Auto Crop Decision: {reason}")
            
    msg_lines.append(f"Auto action OK ({frame_idx} frames{intro_info}, "
           f"{analyzer.out_w}×{analyzer.out_h}, detector={cfg.detector}{onnx_tag}{crop_info}{smart_tag}{plat_tag}{scene_tag} "
           f"str={cfg.strength:.2f} sm={cfg.smoothness:.2f}).")
           
    msg = "\n".join(msg_lines)
           
    return True, writer.out_path, msg
