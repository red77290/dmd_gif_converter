import collections
import os
import subprocess
import tempfile
from typing import Deque, Optional, Tuple
import numpy as np
from .config import AutoActionConfig
from .detector import _FrameDetector, available_detectors
from .camera import _build_camera_rect, _smooth, _crop_frame, _apply_look_ahead
from .analysis import _clamp, _FloorEstimator, _compute_auto_crop_margins, _smart_auto_crop_decision, _calculate_dmd_visibility_score, _compute_scene_change_score

def preprocess_video_for_dmd(src_path: str, cfg: AutoActionConfig):
    """Create an auto-framed temporary MP4 and return (ok, out_path, message).

    Frames are processed by OpenCV and piped directly to an FFmpeg subprocess
    via stdin as raw BGR24 video — no cv2.VideoWriter, no bulky mp4v temp file.
    The intermediate MP4 is encoded with H.264 (ultrafast preset), which is
    ~5–10× smaller than the old mp4v output and ~30 % faster to produce.

    Returns:
      - ok=True: out_path is an existing intermediate video.
      - ok=False: out_path is None, message explains fallback reason.
    """
    try:
        import cv2
    except Exception:
        return False, None, "OpenCV not installed (install opencv-python to enable auto action framing)."

    if cfg.detector.lower() not in available_detectors():
        cfg.detector = "person"

    # ── GIF pre-conversion ────────────────────────────────────────────────────
    # cv2.VideoCapture decodes GIF files inconsistently on macOS/AVFoundation:
    # - Frames may be BGRA (4-channel) due to GIF transparency palettes.
    # - Actual FPS returned may be 10 fps even if the GIF header says otherwise.
    # - Sub-frame delta GIFs produce garbled frames after the first one.
    # Workaround: transcode any .gif to a clean BGR24 H.264 MP4 via FFmpeg
    # before feeding it to OpenCV.  The temp MP4 is placed in a separate dir
    # that is cleaned up at the end of this function.
    _gif_pre_tmpdir: Optional[str] = None
    if src_path.lower().endswith(".gif"):
        try:
            _gif_pre_tmpdir = tempfile.mkdtemp(prefix="dmd_gifpre_")
            _gif_mp4 = os.path.join(_gif_pre_tmpdir, "src.mp4")
            _gif_conv_cmd = [
                "ffmpeg", "-y",
                "-i", src_path,
                "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",  # ensure even dims
                _gif_mp4,
            ]
            _gif_result = subprocess.run(
                _gif_conv_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=120,
            )
            if _gif_result.returncode == 0 and os.path.isfile(_gif_mp4):
                src_path = _gif_mp4
            else:
                # Keep original path; BGR normalization below will act as safety net
                import shutil as _shutil
                _shutil.rmtree(_gif_pre_tmpdir, ignore_errors=True)
                _gif_pre_tmpdir = None
        except Exception:
            if _gif_pre_tmpdir:
                import shutil as _shutil
                _shutil.rmtree(_gif_pre_tmpdir, ignore_errors=True)
                _gif_pre_tmpdir = None

    cap = cv2.VideoCapture(src_path)
    if not cap.isOpened():
        if _gif_pre_tmpdir:
            import shutil as _shutil
            _shutil.rmtree(_gif_pre_tmpdir, ignore_errors=True)
        return False, None, "Could not open source for action preprocessing."

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    fps = max(1.0, float(fps))
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    if frame_w <= 0 or frame_h <= 0:
        cap.release()
        return False, None, "Invalid source dimensions for action preprocessing."

    # Output at native source resolution with target_width:target_height crop ratio.
    # Keeping the native resolution here means ffmpeg receives full-quality input
    # and performs the final downscale to target_width x target_height with all its colour filters.
    out_w = frame_w
    # Calculate out_h based on the desired target aspect ratio.
    # Use proper float division (not int truncation) so non-integer ratios like
    # 128×48 (≈2.667) or 256×48 (≈5.333) produce the correct height.
    # The //2*2 guarantees an even number as required by H.264/YUV420 encoding.
    target_aspect_ratio = float(cfg.target_width) / cfg.target_height
    out_h = max(8, int(round(frame_w / target_aspect_ratio / 2)) * 2)
    # This avoids framing being dragged down by feet/floor/subtitles/HUD elements.
    _bcp = _clamp(getattr(cfg, "bottom_crop_pct", 0.0), 0.0, 0.9)
    _tcp = _clamp(getattr(cfg, "top_crop_pct", 0.0), 0.0, 0.9)

    # ── Auto crop margins ─────────────────────────────────────────────────────
    # When auto_bottom_crop or auto_top_crop is enabled, sample the video to
    # compute the tightest crop that still contains the full subject (face or
    # full body), then override the manual crop percentages.
    _auto_bc = getattr(cfg, "auto_bottom_crop", False)
    _auto_tc = getattr(cfg, "auto_top_crop", False)
    _smart_reasons: list[str] = []

    # ── Smart Auto Crop decision (overrides individual flags) ─────────────────
    # When smart_auto_crop=True the engine analyses 25 frames to decide which
    # combination of auto_bottom_crop / auto_top_crop / auto_vertical_bias to
    # activate, AND pre-computes the crop percentages in the same pass so that
    # the second _compute_auto_crop_margins scan is skipped entirely.
    # This halves the scanning overhead compared to running two separate scans.
    # The entire block is wrapped in a try/except so that any unexpected error
    # (ONNX load failure, network timeout, OpenCV issue) degrades gracefully to
    # "all manual" instead of propagating an exception to the preview thread.
    _smart_crop_margins: Optional[tuple] = None   # (top_pct, bottom_pct) or None
    _smart_face_priority: bool = False             # face_priority from smart scan
    if getattr(cfg, "smart_auto_crop", False):
        try:
            _decision = _smart_auto_crop_decision(cap, cfg, frame_w, frame_h)
            _auto_bc                  = _decision["auto_bottom_crop"]
            _auto_tc                  = _decision["auto_top_crop"]
            cfg.auto_vertical_bias    = _decision["auto_vertical_bias"]
            _smart_reasons            = _decision["reasons"]
            # Use pre-computed margins from the smart scan — reuse them directly.
            _smart_crop_margins  = (_decision["top_pct"], _decision["bottom_pct"])
            _smart_face_priority = _decision.get("face_priority", False)
        except Exception as _e:
            # Graceful fallback: smart scan failed — keep individual manual flags.
            _smart_reasons = [f"smart scan error ({_e!r}) → all manual"]

    _face_priority_mode = False  # will be set True if face priority was triggered
    if _auto_bc or _auto_tc:
        try:
            if _smart_crop_margins is not None:
                # Smart scan already computed the margins — reuse them directly.
                computed_top, computed_bottom = _smart_crop_margins
                # Trust the face_priority flag from the scan directly.
                # The old heuristic (_effective_h < 0.75*dmd_h) was unreliable:
                # when FACE_FRAC placed roi_bottoms in the hair, effective_frame_h
                # was larger than expected → threshold not reached → flag stayed False
                # → camera constrained to hair zone → face cut in half.
                _face_priority_mode = _smart_face_priority
            else:
                # Individual auto flags (no smart scan): run the dedicated margin scan.
                detector_for_scan = _FrameDetector()
                computed_top, computed_bottom, _face_priority_mode = \
                    _compute_auto_crop_margins(
                        cap, detector_for_scan, cfg, frame_w, frame_h
                    )
            if _auto_tc:
                _tcp = computed_top
            if _auto_bc:
                _bcp = computed_bottom
        except Exception as _e:
            # Graceful fallback: crop margin scan failed — use manual values.
            pass

    effective_frame_top = int(frame_h * _tcp)
    effective_frame_h   = max(cfg.target_height, int(frame_h * (1.0 - _bcp)))

    initial_start_s = cfg.start_s if cfg.start_s is not None else 0.0
    if initial_start_s > 0:
        cap.set(cv2.CAP_PROP_POS_MSEC, float(initial_start_s) * 1000.0)

    # ── FFmpeg rawvideo pipe — replaces cv2.VideoWriter ───────────────────────
    # Frames are sent as BGR24 rawvideo to FFmpeg's stdin.  FFmpeg encodes them
    # to H.264/MP4 directly, eliminating all intermediate disk I/O for raw frames
    # and producing a temp file ~5–10× smaller than the old mp4v output.
    tmpdir   = tempfile.mkdtemp(prefix="dmd_action_")
    out_path = os.path.join(tmpdir, "action_pre.mp4")

    _fps_str = f"{fps:.6f}"
    _pipe_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s", f"{out_w}x{out_h}",
        "-r", _fps_str,
        "-i", "pipe:0",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        out_path,
    ]
    try:
        ffmpeg_proc = subprocess.Popen(
            _pipe_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except Exception as exc:
        cap.release()
        return False, None, f"Could not start FFmpeg pipe for action preprocessing: {exc}"

    # Helper: write a frame to the pipe; returns False on broken pipe (FFmpeg died).
    def _write_frame(f) -> bool:
        try:
            ffmpeg_proc.stdin.write(f.tobytes())
            return True
        except (BrokenPipeError, OSError):
            return False

    detector = _FrameDetector()

    # ── Camera bounds for _build_camera_rect ──────────────────────────────────
    # In face-priority mode the effective zone (effective_frame_top / effective_frame_h)
    # is intentionally smaller than one DMD strip (crop_h = frame_w/ratio).
    # Passing it as the camera's frame bounds causes _cy_min > _cy_max, so the
    # camera is forced to _cy_min = effective_frame_top + crop_h/2 = shoulder level,
    # which places the face at the very top edge of the visible strip — cut off.
    #
    # Fix: in face-priority mode the effective zone is used for DETECTION ONLY
    # (to show YOLO a tight face region so it detects a small ROI).  The camera
    # must be free to follow that small ROI over the FULL source frame height,
    # which lets _build_camera_rect centre the camera naturally on the detected face.
    #
    # In all other modes (floor tracking, normal crop) keep the effective bounds
    # so the camera does not pan into excluded HUD / sky areas.
    if _face_priority_mode:
        _cam_frame_h   = frame_h        # full source height — no artificial bottom cap
        _cam_frame_top = 0.0            # no artificial top floor
    else:
        _cam_frame_h   = effective_frame_h
        _cam_frame_top = float(effective_frame_top)

    # Full-frame overview rect: widest target_width:target_height crop centred on the source.
    # Uses effective_frame_h so the intro never pans into the bottom-cropped region.
    # Uses effective_frame_top so the intro never pans above the top-cropped region.
    cam_full_view = _build_camera_rect(frame_w, _cam_frame_h, None, cfg,
                                       frame_top=_cam_frame_top)

    # ── Intro frame count — capped relative to source length ─────────────────
    # A fixed intro_duration can dominate very short sources (e.g. a 0.5 s GIF
    # would get a 1.5 s frozen intro = 3× the source length).
    # Cap intro to at most 40 % of total source frames so the action-tracking
    # phase always has the majority of the output.
    total_frames_src = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    intro_frames = max(0, int(round(cfg.intro_duration * fps)))
    if total_frames_src > 0:
        max_intro = max(1, int(total_frames_src * 0.40))
        intro_frames = min(intro_frames, max_intro)

    last_frame = None
    frame_idx  = 0
    extra      = 0
    _pipe_alive = True  # tracks whether the FFmpeg pipe is still writable

    # Read the very first frame of the segment for intro (if any).
    ok_first, first_frame_for_intro = cap.read()
    if not ok_first:
        cap.release()
        try:
            ffmpeg_proc.stdin.close()
            ffmpeg_proc.wait()
        except Exception:
            pass
        return False, None, "Could not read first frame for intro."

    # Safety: normalise to BGR (3-channel).  cv2.VideoCapture may return BGRA
    # (4-channel) for GIFs with transparency even after the pre-conversion step
    # (e.g. if FFmpeg was not available and we fell back to reading the raw GIF).
    # Sending 4-byte pixels to a bgr24 pipe would corrupt the stream silently.
    if first_frame_for_intro.ndim == 3 and first_frame_for_intro.shape[2] == 4:
        first_frame_for_intro = cv2.cvtColor(first_frame_for_intro, cv2.COLOR_BGRA2BGR)
    elif first_frame_for_intro.ndim == 2:
        first_frame_for_intro = cv2.cvtColor(first_frame_for_intro, cv2.COLOR_GRAY2BGR)

    # ── Background subtractor warm-up ─────────────────────────────────────────
    # MOG2 starts with no background model: the very first frames it processes
    # either return an all-foreground mask (everything visible) or an all-zero
    # mask (black flash), depending on the internal state of the Gaussian mixture.
    #
    # Fix: before outputting a single frame, prime the model by replaying the
    # first frame 30× at a high learning-rate (0.5).  After this the model has
    # a solid estimate of the static background and produces clean masks from
    # frame 1 of the actual output.
    if cfg.bg_sub_enable:
        _wf = first_frame_for_intro
        if max(_wf.shape[0], _wf.shape[1]) > 512:
            _sf = 512 / max(_wf.shape[0], _wf.shape[1])
            _wf = cv2.resize(
                _wf,
                (int(_wf.shape[1] * _sf), int(_wf.shape[0] * _sf)),
                interpolation=cv2.INTER_AREA,
            )
        _BG_WARMUP_ITERS = 30
        for _ in range(_BG_WARMUP_ITERS):
            detector.bg_sub.apply(_wf, learningRate=0.5)

    # ── Phase 1: Intro panoramic pan (frozen first frame, top → centre) ──────
    # The first source frame is held for intro_frames while the camera pans
    # from the TOP of the frame down to the CENTRE (smoothstep easing).
    cx, cy_center, crop_w_full, crop_h_src = cam_full_view

    # ── 1) Static Intro / Pan Down ────────────────────────────────────────────
    # The first N seconds are a smooth pan-down from the top of the frame. This
    # is a static frozen frame, so MOG2 would just darken it progressively as
    # the model learns the content as "background".  Full frame shown instead.
    if intro_frames > 0 and _pipe_alive:
        cy_top = crop_h_src / 2.0

        for i in range(intro_frames):
            t_linear = i / max(1, intro_frames - 1)
            t = t_linear * t_linear * (3.0 - 2.0 * t_linear)
            cy = cy_top + t * (cy_center - cy_top)
            cam_intro = (cx, cy, crop_w_full, crop_h_src)
            cropped_frame = _crop_frame(first_frame_for_intro, cam_intro)

            out_frame = cv2.resize(cropped_frame, (out_w, out_h),
                                   interpolation=cv2.INTER_LANCZOS4)
            if not _write_frame(out_frame):
                _pipe_alive = False
                break
            frame_idx += 1

        last_frame = first_frame_for_intro  # last_frame for tail extension

    # Ensure the capture is at the correct start_s for the main tracking phase.
    cap.set(cv2.CAP_PROP_POS_MSEC, float(initial_start_s) * 1000.0)

    # ── Phase 2: Action tracking (full source from frame 0) ───────────────────
    # Camera starts at cam_full_view so the transition from the intro is smooth.
    cam_prev = cam_full_view
    cam_now  = cam_full_view
    src_idx  = 0

    # Dynamic floor estimator: active only when auto_vertical_bias or platformer_mode is on.
    # Use _cam_frame_h so the estimator works over the same vertical range as the camera.
    _floor_est: Optional[_FloorEstimator] = (
        _FloorEstimator(_cam_frame_h) if cfg.auto_vertical_bias or cfg.platformer_mode else None
    )

    # ── PRIORITY 2 — Temporal Scene Memory ───────────────────────────────────
    # Sliding window of (weight, roi) pairs.  Recent frames have higher weight.
    # When the live detector returns None, we synthesise a weighted-average ROI
    # from the history so the camera continues following the estimated trajectory
    # instead of jumping back to the centre.
    _roi_history: Deque[Tuple[float, Tuple[int, int, int, int]]] = collections.deque()
    _roi_history_max_len: int = max(1, int(fps * max(0.0, cfg.roi_history_window_s)))
    _roi_history_enabled: bool = cfg.roi_history_window_s > 0.0

    # ── PRIORITY 3 — Scene Change Detection ──────────────────────────────────
    _prev_frame_for_scene: Optional[np.ndarray] = None
    _scene_change_enabled: bool = cfg.scene_change_threshold > 0.0

    # ── PRIORITY 5 — Directional Look-Ahead ──────────────────────────────────
    _prev_roi_cx: Optional[float] = None
    _prev_roi_cy: Optional[float] = None

    while _pipe_alive:
        ok, frame = cap.read()
        if not ok:
            break

        # Safety: normalise to BGR (same as for first_frame_for_intro above).
        if frame.ndim == 3 and frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        elif frame.ndim == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

        t = src_idx / fps
        if cfg.end_s is not None and (initial_start_s + t) >= float(cfg.end_s):
            break

        # Detect ROI for camera framing.
        #
        # FACE PRIORITY MODE: detect on the FULL FRAME so YOLO receives a
        # proper-aspect-ratio image.  The restricted slice (effective zone)
        # would typically be a very wide, short region (e.g. 800×120 for the
        # head-only zone).  Resizing a 6:1 aspect ratio slice to 640×640
        # squishes the person severely → YOLO misses the face or returns a
        # wrong bounding box centred on the hair rather than the face.
        # After detection on the full frame, we adjust the ROI to focus on
        # the face region (top FACE_FRAC_CAM of the bounding box), so the
        # camera centres on the face rather than on the mid-body.
        #
        # NORMAL MODE: restrict to effective_frame_top:effective_frame_h so the
        # camera ignores HUD bars, sky, and other cropped-out areas.

        # ── PRIORITY 3 — Scene Change Detection ──────────────────────────────
        if _scene_change_enabled and _prev_frame_for_scene is not None:
            sim = _compute_scene_change_score(_prev_frame_for_scene, frame)
            if sim < (1.0 - cfg.scene_change_threshold):
                # Hard cut detected: flush all state derived from the old scene.
                _roi_history.clear()
                cam_prev = cam_full_view
                if _floor_est is not None:
                    _floor_est = _FloorEstimator(_cam_frame_h)
                _prev_roi_cx = None
                _prev_roi_cy = None
        _prev_frame_for_scene = frame
        # ── End Priority 3 ────────────────────────────────────────────────────

        if _face_priority_mode:
            roi = detector.detect(frame, cfg.detector,
                                  multi_fusion=cfg.multi_roi_fusion_enabled,
                                  min_conf=cfg.roi_confidence_min)
            if roi is not None:
                rx, ry, rw, rh = roi
                # Keep only the head region of the bounding box (top ~28 %).
                # This moves the camera centre from mid-body to face level.
                _face_h = max(8, int(rh * 0.28))
                roi = (rx, ry, rw, _face_h)
        else:
            detect_frame = frame[effective_frame_top:effective_frame_h, :]
            roi = detector.detect(detect_frame, cfg.detector,
                                  multi_fusion=cfg.multi_roi_fusion_enabled,
                                  min_conf=cfg.roi_confidence_min)
            # Translate ROI y-coordinate back into original frame space.
            if roi is not None and effective_frame_top > 0:
                rx, ry, rw, rh = roi
                roi = (rx, ry + effective_frame_top, rw, rh)

        # ── PRIORITY 4 — Micro-detection Rejection ────────────────────────────
        if roi is not None and cfg.min_roi_area_ratio > 0.0:
            roi_area   = roi[2] * roi[3]
            frame_area = frame_w * frame_h
            if frame_area > 0 and (roi_area / frame_area) < cfg.min_roi_area_ratio:
                roi = None   # ROI too small to survive resize — discard
        # ── End Priority 4 ────────────────────────────────────────────────────

        # ── PRIORITY 7 — Minimum Useful Size After Resize ─────────────────────
        if roi is not None and cfg.min_subject_dmd_px > 0:
            # We must estimate how many pixels this ROI will occupy in the final
            # out_w × out_h frame.  The camera crop will be `crop_w_full` wide,
            # and that crop is resized to `out_w`.
            # Ratio of output width to crop width:
            _dmd_scale = out_w / float(crop_w_full)
            dmd_w = roi[2] * _dmd_scale
            dmd_h = roi[3] * _dmd_scale
            if dmd_w < cfg.min_subject_dmd_px and dmd_h < cfg.min_subject_dmd_px:
                roi = None
        # ── End Priority 7 ────────────────────────────────────────────────────

        # Update floor estimate (asymmetric EMA) and forward it to the camera.
        floor_y_est: Optional[float] = None
        if _floor_est is not None:
            roi_bottom = float(roi[1] + roi[3]) if roi is not None else None
            floor_y_est = _floor_est.update(roi_bottom)

        # ── PRIORITY 2 — Temporal Scene Memory ────────────────────────────────
        # Push current live detection into the sliding window, then synthesise a
        # weighted-average ROI when live detection is temporarily absent.
        if _roi_history_enabled:
            if roi is not None:
                # Append with weight=1.0 (most-recent end of the deque).
                _roi_history.append((1.0, roi))
                # Evict oldest entries beyond the time window.
                while len(_roi_history) > _roi_history_max_len:
                    _roi_history.popleft()
            elif _roi_history:
                # No live detection — synthesise from history.
                # Weights increase linearly from oldest (idx=0) to newest (idx=N-1).
                n = len(_roi_history)
                total_w = 0.0
                wx, wy, ww, wh = 0.0, 0.0, 0.0, 0.0
                for idx, (_, hr) in enumerate(_roi_history):
                    w = float(idx + 1)  # linear ramp: 1, 2, …, n
                    total_w += w
                    wx += w * hr[0]
                    wy += w * hr[1]
                    ww += w * hr[2]
                    wh += w * hr[3]
                if total_w > 0:
                    roi = (
                        int(wx / total_w),
                        int(wy / total_w),
                        int(ww / total_w),
                        int(wh / total_w),
                    )
        # ── End Priority 2 ────────────────────────────────────────────────────

        cam_now_proposed = _build_camera_rect(frame_w, _cam_frame_h, roi, cfg,
                                              floor_y_est=floor_y_est,
                                              frame_top=_cam_frame_top)

        # --- DMD Visibility Score Logic (PRIORITY 1) ---
        if cfg.dmd_visibility_score_enabled:
            # 1. Simulate current view (cam_prev) DMD output and score
            cropped_prev = _crop_frame(frame, cam_prev)
            dmd_prev_frame = cv2.resize(cropped_prev, (cfg.target_width, cfg.target_height),
                                        interpolation=cv2.INTER_LANCZOS4)
            score_prev = _calculate_dmd_visibility_score(dmd_prev_frame)

            # 2. Simulate proposed view (cam_now_proposed) DMD output and score
            cropped_proposed = _crop_frame(frame, cam_now_proposed)
            dmd_proposed_frame = cv2.resize(cropped_proposed, (cfg.target_width, cfg.target_height),
                                            interpolation=cv2.INTER_LANCZOS4)
            score_proposed = _calculate_dmd_visibility_score(dmd_proposed_frame)

            # 3. Compare scores and adjust cam_now if proposed is worse
            # If the proposed zoom significantly reduces visibility, we revert only the zoom (width/height)
            # but keep the proposed tracking coordinates (cx, cy) to prevent tracking stutter.
            if score_proposed < score_prev * 0.95:
                cam_now = (cam_now_proposed[0], cam_now_proposed[1], cam_prev[2], cam_prev[3])
            else:
                cam_now = cam_now_proposed
        else:
            cam_now = cam_now_proposed
        # --- End DMD Visibility Score Logic ---

        # ── PRIORITY 5 — Directional Look-Ahead ──────────────────────────────
        # Compute current ROI centre (use live ROI when available, else None).
        # We apply look-ahead to cam_now BEFORE smoothing, so the camera smoothly tracks 
        # towards the projected future position, rather than snapping to it abruptly.
        _curr_roi_cx: Optional[float] = None
        _curr_roi_cy: Optional[float] = None
        if roi is not None:
            _curr_roi_cx = float(roi[0] + roi[2] / 2.0)
            _curr_roi_cy = float(roi[1] + roi[3] / 2.0)
            
        if cfg.look_ahead_enabled and cfg.look_ahead_factor > 0.0:
            cam_now = _apply_look_ahead(
                cam_now,
                _prev_roi_cx, _curr_roi_cx,
                _prev_roi_cy, _curr_roi_cy,
                frame_w, frame_h,
                cfg.look_ahead_factor,
            )
        _prev_roi_cx = _curr_roi_cx
        _prev_roi_cy = _curr_roi_cy
        # ── End Priority 5 ────────────────────────────────────────────────────

        cam = _smooth(cam_prev, cam_now, cfg.smoothness)

        cam_prev = cam
        last_frame = frame

        cropped_frame = _crop_frame(frame, cam)

        # Apply background subtraction if enabled
        if cfg.bg_sub_enable:
            bs_frame = cropped_frame
            if max(cropped_frame.shape[0], cropped_frame.shape[1]) > 512:
                scale_factor_bs = 512 / max(cropped_frame.shape[0], cropped_frame.shape[1])
                bs_frame = cv2.resize(cropped_frame, (int(cropped_frame.shape[1] * scale_factor_bs), int(cropped_frame.shape[0] * scale_factor_bs)), interpolation=cv2.INTER_AREA)

            fg_mask = detector.bg_sub.apply(bs_frame)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)
            fg_mask = cv2.resize(fg_mask, (cropped_frame.shape[1], cropped_frame.shape[0]), interpolation=cv2.INTER_LINEAR)
            cropped_frame = cv2.bitwise_and(cropped_frame, cropped_frame, mask=fg_mask)

        out_frame = cv2.resize(cropped_frame, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
        if not _write_frame(out_frame):
            _pipe_alive = False
            break
        frame_idx += 1
        src_idx   += 1

    # ── Tail extension: freeze last frame while camera settles ────────────────
    # Kept intentionally short (≤ 0.3 s) because this output is a looping GIF:
    # long tails create a visible freeze before the loop restarts.
    # NOTE: background subtraction is skipped here — applying MOG2 to a repeated
    # static frame would progressively darken the output as the model reclassifies
    # the content as background.
    if last_frame is not None and cam_prev is not None and cam_now is not None and _pipe_alive:
        max_extra = max(1, int(fps * 0.3))   # hard cap: 0.3 s
        settle_px = 1.0                       # stop when camera moves < 1 px/frame
        extra = 0
        while extra < max_extra:
            cam_next = _smooth(cam_prev, cam_now, cfg.smoothness)
            displacement = max(abs(cam_next[i] - cam_prev[i]) for i in range(4))
            cam_prev = cam_next
            cropped_frame = _crop_frame(last_frame, cam_next)

            out_frame = cv2.resize(cropped_frame, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
            if not _write_frame(out_frame):
                break
            frame_idx += 1
            extra += 1
            if displacement < settle_px:
                break   # camera has settled — no more extension needed

    # ── Finalise FFmpeg pipe ───────────────────────────────────────────────────
    try:
        ffmpeg_proc.stdin.close()
    except Exception:
        pass
    ffmpeg_rc = ffmpeg_proc.wait()
    cap.release()

    # Clean up GIF pre-conversion temp dir (no longer needed after cap.release).
    if _gif_pre_tmpdir:
        import shutil as _shutil
        _shutil.rmtree(_gif_pre_tmpdir, ignore_errors=True)

    if ffmpeg_rc != 0 or frame_idx <= 0 or not os.path.isfile(out_path):
        _stderr_hint = ""
        try:
            _se = ffmpeg_proc.stderr.read().decode(errors="replace").strip()
            if _se:
                # Keep only the last 300 chars to avoid flooding the log
                _stderr_hint = " | ffmpeg: " + _se[-300:]
        except Exception:
            pass
    # ── Build summary message ─────────────────────────────────────────────────
    intro_info  = f", intro={cfg.intro_duration:.1f}s" if intro_frames > 0 else ""
    tail_info   = ""   # tail extension is silent (≤ 0.3 s, not user-visible)
    onnx_tag    = " [onnx]" if getattr(detector, "model_type", "") == "onnx" else ""
    _crops      = []
    if cfg.auto_bottom_crop or cfg.bottom_crop_pct > 0:
        _crops.append(f"bot={cfg.bottom_crop_pct:.0%}")
    if cfg.auto_top_crop or cfg.top_crop_pct > 0:
        _crops.append(f"top={cfg.top_crop_pct:.0%}")
    crop_info   = (" crop=" + "+".join(_crops)) if _crops else ""
    smart_tag   = " smart" if (cfg.smart_auto_crop or cfg.roi_confidence_min > 0 or cfg.min_subject_dmd_px > 0) else ""
    plat_tag    = " plat" if cfg.platformer_mode else ""
    return True, out_path, (
        f"Auto action OK ({frame_idx} frames{intro_info}{tail_info}, "
        f"{out_w}×{out_h}, detector={cfg.detector}{onnx_tag}{crop_info}{smart_tag}{plat_tag})."
    )
