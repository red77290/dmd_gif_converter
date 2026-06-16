import os
import queue
import threading
from src.engine.config.auto_action_config import AutoActionConfig
from src.plugins.detectors.detector import available_detectors
from .camera import _smooth

from .reader import VideoReader
from .writer import FFmpegWriter
from src.engine.analysis.analyzer import VideoAnalyzer
from src.plugins.trackers.tracker import TrackingEngine
from .renderer import Renderer

def preprocess_video_for_dmd(src_path: str, cfg: AutoActionConfig = None, cancel_event=None, callback=None, trim_start=None, trim_end=None, **kwargs):
    """Create an auto-framed temporary MP4 and return (ok, out_path, message)."""
    try:
        import cv2
        cv2.setNumThreads(1)
    except Exception:
        return False, None, "OpenCV not installed (install opencv-python to enable auto action framing)."

    if cfg is None:
        cfg = AutoActionConfig()
    elif callable(cfg):
        callback = cfg
        cfg = AutoActionConfig()

    if trim_start is not None:
        cfg.start_s = trim_start
    if trim_end is not None:
        cfg.end_s = trim_end

    filename = os.path.basename(src_path)
    def log(msg, level="info"):
        if callback:
            callback(msg, level)

    if cfg.detector.lower() not in available_detectors():
        cfg.detector = "person"

    log("Analyzing video content (smart crop/scene detection)...", "debug")
    # 1. Analyzer
    from src.engine.conversion.ffmpeg_utils import get_metadata
    w, h, f_fps, dur = get_metadata(src_path)
    if not w or not h:
        return False, None, "Could not get video metadata."
    analyzer = VideoAnalyzer(w, h, cfg)
    analyzer.analyze(src_path)

    log("Opening video reader...", "debug")
    # 2. Reader
    reader = VideoReader(src_path)
    ok, msg = reader.open()
    if not ok:
        return False, None, msg

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
    read_q = queue.Queue(maxsize=16)
    write_q = queue.Queue(maxsize=16)
    stop_event = threading.Event()

    def reader_thread():
        try:
            reader.set_time(float(initial_start_s) * 1000.0)
            while not stop_event.is_set():
                if cancel_event and cancel_event.is_set():
                    break
                ok, frame = reader.read()
                if not ok:
                    break
                while not stop_event.is_set():
                    try:
                        read_q.put(frame, timeout=0.1)
                        break
                    except queue.Full:
                        if cancel_event and cancel_event.is_set():
                            break
        except Exception as e:
            logger.error(f"Reader thread error: {e}")
        finally:
            try:
                read_q.put(None, timeout=0.5)
            except queue.Full:
                pass

    def processor_thread():
        try:
            # ── Phase 1: Intro panoramic pan ──────────────────────────────────────────
            cx, cy_center, crop_w_full, crop_h_src = tracker.cam_full_view
            if intro_frames > 0:
                cy_top = crop_h_src / 2.0
                for i in range(intro_frames):
                    if stop_event.is_set() or (cancel_event and cancel_event.is_set()):
                        break
                    t_linear = i / max(1, intro_frames - 1)
                    t = t_linear * t_linear * (3.0 - 2.0 * t_linear)
                    cy = cy_top + t * (cy_center - cy_top)
                    from src.engine.auto_action.interfaces import CamRect
                    cam_intro = CamRect(cx, cy, crop_w_full, crop_h_src)
                    out_frame = renderer.render(first_frame_for_intro, cam_intro)
                    while not stop_event.is_set():
                        try:
                            write_q.put(out_frame, timeout=0.1)
                            break
                        except queue.Full:
                            if cancel_event and cancel_event.is_set():
                                break

            last_frame = first_frame_for_intro
            cam_prev = tracker.cam_full_view
            cam_now = tracker.cam_full_view
            
            action_frames = max(1, reader.total_frames - intro_frames)
            required_smoothness = 0.10 ** (1.0 / max(5, action_frames))
            dynamic_smoothness = max(0.50, min(cfg.smoothness, required_smoothness))
            
            src_idx = 0
            
            # ── Phase 2: Action tracking ──────────────────────────────────────────────
            while not stop_event.is_set():
                if cancel_event and cancel_event.is_set():
                    break
                try:
                    frame = read_q.get(timeout=0.1)
                except queue.Empty:
                    continue
                if frame is None:
                    break
                
                t_val = src_idx / reader.fps
                if cfg.end_s is not None and (initial_start_s + t_val) >= float(cfg.end_s):
                    break

                cam_now = tracker.process_frame(frame, cam_prev, src_idx, analyzer.out_w, analyzer.out_h)
                
                # Snap camera immediately to target on the first frame or on a scene change cut
                snap_camera = False
                if src_idx == 0:
                    if intro_frames == 0:
                        snap_camera = True
                elif getattr(tracker, "frames_since_scene_change", 999) == 1:
                    snap_camera = True

                if snap_camera:
                    cam = cam_now
                else:
                    cam = _smooth(cam_prev, cam_now, dynamic_smoothness)
                cam_prev = cam
                last_frame = frame
                
                out_frame = renderer.render(frame, cam, roi=tracker.last_roi)
                while not stop_event.is_set():
                    try:
                        write_q.put(out_frame, timeout=0.1)
                        break
                    except queue.Full:
                        if cancel_event and cancel_event.is_set():
                            break
                src_idx += 1

            # ── Phase 3: Tail extension ───────────────────────────────────────────────
            if last_frame is not None and cam_prev is not None and cam_now is not None:
                max_extra = max(1, int(reader.fps * 0.3))
                settle_px = 1.0
                extra = 0
                while extra < max_extra and not stop_event.is_set():
                    if cancel_event and cancel_event.is_set():
                        break
                    
                    cam_next = _smooth(cam_prev, cam_now, dynamic_smoothness)
                    displacement = max(abs(cam_next[i] - cam_prev[i]) for i in range(4))
                        
                    cam_prev = cam_next
                    out_frame = renderer.render(last_frame, cam_next, is_tail=True)
                    while not stop_event.is_set():
                        try:
                            write_q.put(out_frame, timeout=0.1)
                            break
                        except queue.Full:
                            if cancel_event and cancel_event.is_set():
                                break
                    
                    extra += 1
                    if displacement < settle_px:
                        break
        except Exception as e:
            logger.error(f"Processor thread error: {e}", exc_info=True)
        finally:
            try:
                write_q.put(None, timeout=0.5)
            except queue.Full:
                pass

    # Start threads
    rt = threading.Thread(target=reader_thread, daemon=True)
    pt = threading.Thread(target=processor_thread, daemon=True)
    rt.start()
    pt.start()

    frame_idx = 0
    
    try:
        while not stop_event.is_set():
            if cancel_event and cancel_event.is_set():
                stop_event.set()
                break
            try:
                out_frame = write_q.get(timeout=0.2)
            except queue.Empty:
                if not pt.is_alive() and write_q.empty():
                    break
                continue
                
            if out_frame is None:
                break
            if not writer.write_frame(out_frame):
                stop_event.set()
                break
            frame_idx += 1
            if callback and (frame_idx == 1 or frame_idx % 25 == 0):
                tot = reader.total_frames or "?"
                log(f"Tracking targets: frame {frame_idx}/{tot}", "debug")
    finally:
        stop_event.set()
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
    scene_tag = f" scene={analyzer.scene_profile.scene_type}" if getattr(analyzer, 'scene_profile', None) else ""
    
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
