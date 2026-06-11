import os
import subprocess
import tempfile
import logging
import math
from typing import Dict, Any, Optional, Tuple

from ..interfaces import IConverter
from ..ffmpeg_utils import get_metadata, snap_to_clean_fps, _check_drawtext
from ...auto_action import AutoActionConfig, preprocess_video_for_dmd
from .pillow_overlay import PillowOverlayService
try:
    from ..colorimetry import analyze_and_compensate as _analyze_and_compensate
except Exception:
    _analyze_and_compensate = None

logger = logging.getLogger(__name__)

class FFmpegConverter(IConverter):
    """Implementation of IConverter using FFmpeg to generate GIFs."""
    
    def __init__(self, default_params: Dict[str, Any]):
        self.default_params = default_params

    def process(self, src_path: str, out_path: str, params: Dict[str, Any], start_s: Optional[float] = None, end_s: Optional[float] = None, callback=None) -> Tuple[bool, str]:
        p = {**self.default_params, **(params or {})}
        src_path = str(src_path)
        out_path = str(out_path)
        filename = os.path.basename(src_path)

        def log(msg, level="info"):
            getattr(logger, level)(msg)
            if callback:
                callback(msg, level)

        temp_pre_src = None
        original_src = src_path

        target_width = p["target_width"]
        target_height = p["target_height"]

        # --- 1. Preprocessing (Auto Action) ---
        if p.get("auto_action_enabled"):
            log(f"[{filename}] Auto action ON: preprocessing video...", "info")
            cfg = AutoActionConfig()
            cfg.detector = p.get("action_detector", "person")
            cfg.smoothness = p.get("action_smoothness", 0.98)
            cfg.zoom_max = p.get("action_zoom_max", 2.0)
            cfg.padding = p.get("action_padding", 0.20)
            cfg.intro_duration = float(p.get("action_intro", 1.5))
            cfg.bg_sub_enable = p.get("bg_sub_enable", False)

            cfg.bottom_crop_pct = p.get("action_bottom_crop", 0.0)
            cfg.auto_bottom_crop = p.get("action_auto_bottom_crop", False)
            cfg.top_crop_pct = p.get("action_top_crop", 0.0)
            cfg.auto_top_crop = p.get("action_auto_top_crop", False)
            cfg.vertical_bias = p.get("action_vertical_bias", 0.0)
            cfg.auto_vertical_bias = p.get("action_auto_vertical_bias", False)
            cfg.scene_type = p.get("action_scene_type", "")
            cfg.auto_scene_type = p.get("action_auto_scene_type", False)
            cfg.smart_auto_crop = p.get("action_smart_auto_crop", False)
            
            cfg.target_width = target_width
            cfg.target_height = target_height

            cfg.start_s = start_s
            cfg.end_s = end_s
            
            _cap_dur = p.get("max_duration", 0.0)
            if _cap_dur > 0:
                if cfg.end_s is None:
                    cfg.end_s = (cfg.start_s or 0.0) + _cap_dur
                else:
                    cfg.end_s = min(cfg.end_s, (cfg.start_s or 0.0) + _cap_dur)

            ok_pre, pre_src, pre_msg = preprocess_video_for_dmd(src_path, cfg)
            if not ok_pre or not pre_src:
                log(f"[{filename}] Auto action failed: {pre_msg}", "warning")
            else:
                log(f"[{filename}] {pre_msg}", "info")
                temp_pre_src = pre_src
                src_path = pre_src
                start_s = None
                end_s = None

        # --- 2. Metadata ---
        meta = get_metadata(src_path)
        if not meta:
            msg = f"[{filename}] Failed to read metadata."
            log(msg, "error")
            return False, msg

        w, h = meta["width"], meta["height"]
        if w == 0 or h == 0:
            msg = f"[{filename}] Invalid dimensions: {w}x{h}"
            log(msg, "error")
            return False, msg

        # --- 3. Colors ---
        mode = p["mode"]
        if mode == "custom":
            cont, sat = p["contrast"], p["saturation"]
            bri, gam = p["brightness"], p["gamma"]
            slum, schr = p["sharpen_lum"], p["sharpen_chr"]
        else:
            if _analyze_and_compensate is not None:
                cont, sat, bri, gam, slum, schr, dither_mode = _analyze_and_compensate(original_src, p["fps_max"], mode)
                if p["dither"] != "none":
                    p["dither"] = dither_mode
                log(f"[{filename}] Auto-color ({mode}): C={cont:.2f} S={sat:.2f} B={bri:.2f} G={gam:.2f}", "debug")
            else:
                from .core import _PRESETS
                cont, sat, bri, gam, slum, schr, _ = _PRESETS.get(mode, _PRESETS["pixel_art"])

        # --- 4. Timing ---
        fps_in = meta["fps"]
        target_fps = snap_to_clean_fps(fps_in, min_fps=p["fps_min"], max_fps=p["fps_max"])

        if start_s is not None:
            if start_s < 0: start_s = 0
        if end_s is not None and start_s is not None:
            if end_s <= start_s:
                end_s = None

        _cap_dur = p.get("max_duration", 0.0)
        if _cap_dur > 0:
            if end_s is None:
                end_s = (start_s or 0.0) + _cap_dur
            else:
                end_s = min(end_s, (start_s or 0.0) + _cap_dur)

        dur_s = None
        if start_s is not None and end_s is not None:
            dur_s = end_s - start_s
        elif start_s is not None and meta["duration"] > 0:
            dur_s = meta["duration"] - start_s
            if _cap_dur > 0: dur_s = min(dur_s, _cap_dur)
        elif meta["duration"] > 0:
            dur_s = meta["duration"]
            if _cap_dur > 0: dur_s = min(dur_s, _cap_dur)

        # --- 5. Geometry (DMD Crop) ---
        crop_vf, manual_msg = self._apply_dmd_crop_ffmpeg(w, h, dur_s, p)
        if manual_msg:
            log(f"[{filename}] {manual_msg}", "debug")

        # --- 6. Effects ---
        vf_filters = []
        if crop_vf:
            vf_filters.append(crop_vf)
            
        vf_filters.append(f"scale={target_width}:{target_height}:flags=lanczos")
        vf_filters.append(f"fps={target_fps}")
        vf_filters.append(f"eq=contrast={cont}:saturation={sat}:brightness={bri}:gamma={gam}")

        if slum > 0 or schr > 0:
            vf_filters.append(f"unsharp=5:5:{slum}:5:5:{schr}")

        hue = p.get("hue_shift", 0.0)
        if abs(hue) > 0.1:
            vf_filters.append(f"hue=h={hue}")

        nr = p.get("noise_reduction", 0.0)
        if nr > 0.1:
            vf_filters.append(f"hqdn3d={nr}:{nr}:{nr}:{nr}")

        fg = p.get("film_grain", 0)
        if fg > 0:
            vf_filters.append(f"noise=alls={fg}:allf=t+u")

        if p.get("vignette", False) and not p.get("auto_action_enabled"):
            vf_filters.append("vignette=PI/3")

        # --- 7. Text ---
        pillow_overlay_used = False
        if p.get("text_overlay_enabled") and p.get("text_content"):
            if _check_drawtext():
                from .core import get_ffmpeg_drawtext_filter
                dt = get_ffmpeg_drawtext_filter(p, target_width, target_height)
                if dt:
                    vf_filters.append(dt)
            else:
                pillow_overlay_used = True
                log(f"[{filename}] Missing libfreetype in ffmpeg. Will use Pillow fallback.", "warning")

        # --- 8. Build FFmpeg command ---
        palette_gen = f"{','.join(vf_filters)},palettegen=stats_mode=diff"
        palette_use = f"{','.join(vf_filters)} [x]; [x][1:v] paletteuse=dither={p['dither']}"

        fd, temp_pal = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        
        intermediate_out = out_path if not pillow_overlay_used else tempfile.mktemp(suffix=".gif")

        # Pass 1: Palette
        cmd1 = ["ffmpeg", "-y"]
        if start_s is not None:
            cmd1.extend(["-ss", f"{start_s:.3f}"])
        if end_s is not None:
            dur = end_s - (start_s or 0)
            cmd1.extend(["-t", f"{dur:.3f}"])

        cmd1.extend([
            "-i", src_path,
            "-vf", palette_gen,
            temp_pal
        ])

        # Pass 2: Encode
        cmd2 = ["ffmpeg", "-y"]
        if start_s is not None:
            cmd2.extend(["-ss", f"{start_s:.3f}"])
        if end_s is not None:
            dur = end_s - (start_s or 0)
            cmd2.extend(["-t", f"{dur:.3f}"])

        cmd2.extend([
            "-i", src_path,
            "-i", temp_pal,
            "-filter_complex", palette_use,
            "-f", "gif",
            intermediate_out
        ])

        try:
            r1 = subprocess.run(cmd1, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            if r1.returncode != 0:
                msg = f"[{filename}] palettegen failed:\n{r1.stderr[-200:]}"
                log(msg, "error")
                return False, msg

            r2 = subprocess.run(cmd2, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            if r2.returncode != 0:
                msg = f"[{filename}] encode failed:\n{r2.stderr[-200:]}"
                log(msg, "error")
                return False, msg

            # --- 9. Pillow Fallback ---
            if pillow_overlay_used:
                svc = PillowOverlayService()
                if not svc.apply(intermediate_out, out_path, p):
                    log(f"[{filename}] Pillow fallback failed. Outputting without text.", "warning")
                    import shutil
                    shutil.move(intermediate_out, out_path)

            msg = f"[{filename}] OK ({target_width}x{target_height}, mode={mode})"
            log(msg, "info")
            return True, msg

        except Exception as e:
            msg = f"[{filename}] Conversion exception: {e}"
            log(msg, "error")
            return False, msg

        finally:
            try:
                if os.path.exists(temp_pal):
                    os.remove(temp_pal)
                if pillow_overlay_used and intermediate_out and os.path.exists(intermediate_out):
                    os.remove(intermediate_out)
                if temp_pre_src and os.path.exists(temp_pre_src):
                    os.remove(temp_pre_src)
            except Exception:
                pass

    def _apply_dmd_crop_ffmpeg(self, w: int, h: int, dur_s: Optional[float], p: Dict[str, Any]) -> Tuple[str, str]:
        """Extracted from core.py _apply_dmd_crop_ffmpeg"""
        target_width = p["target_width"]
        target_height = p["target_height"]

        if not p.get("scroll_enabled", True) or p.get("auto_action_enabled"):
            bcp = max(0.0, min(0.9, p.get("bottom_crop_pct", 0.0)))
            tcp = max(0.0, min(0.9, p.get("top_crop_pct", 0.0)))
            if bcp + tcp >= 1.0:
                bcp, tcp = 0.0, 0.0

            avail_h = h * (1.0 - bcp - tcp)
            base_y  = h * tcp

            zoom = p.get("zoom", 1.0)
            if zoom <= 0: zoom = 1.0

            target_aspect = target_width / target_height

            scaled_target_w = w / zoom
            scaled_target_h = scaled_target_w / target_aspect

            if scaled_target_h > avail_h:
                scaled_target_h = avail_h
                scaled_target_w = scaled_target_h * target_aspect

            base_crop_w = int(scaled_target_w)
            base_crop_h = int(scaled_target_h)

            cx = (w - base_crop_w) // 2
            cy = int(base_y + (avail_h - base_crop_h) // 2)

            mx = p.get("manual_x", 0)
            my = p.get("manual_y", 0)
            cx = max(0, min(cx + mx, w - base_crop_w))
            cy = max(0, min(cy + my, h - base_crop_h))

            msg = f"Fixed crop: zoom={zoom}x (offset: {mx},{my})"
            return f"crop={base_crop_w}:{base_crop_h}:{cx}:{cy}", msg

        bcp = p["bottom_crop_pct"]
        tcp = p.get("top_crop_pct", 0.0)
        h_eff_start = int(h * tcp)
        h_eff_end   = int(h * (1.0 - bcp))
        h_eff = h_eff_end - h_eff_start

        target_aspect = target_width / target_height
        crop_w = w
        crop_h = int(w / target_aspect)

        if crop_h >= h_eff:
            cy = h_eff_start + (h_eff - crop_h) // 2
            return f"crop={crop_w}:{crop_h}:0:{max(0, cy)}", ""

        max_y = h_eff_start + h_eff - crop_h
        min_y = h_eff_start

        scroll_dist = max_y - min_y
        if scroll_dist <= 0:
            return f"crop={crop_w}:{crop_h}:0:{min_y}", ""

        if dur_s and dur_s > 0:
            speed = scroll_dist / (dur_s / 2.0)
        else:
            speed = p["scroll_speed"]

        total_cycles = float(p.get("scroll_cycles", 1.5))
        
        fraction = total_cycles % 1.0
        full_cycles = int(total_cycles)
        
        y_stop = min_y + (fraction * scroll_dist)
        
        total_dist_req = (full_cycles * 2 * scroll_dist) + (fraction * scroll_dist)
        req_dur = total_dist_req / max(0.1, speed)
        
        stop_time = req_dur
        
        expr = f"min(t,{stop_time})*{speed}"
        
        y_expr = f"{min_y} + abs(mod({expr} - {scroll_dist}, {2*scroll_dist}) - {scroll_dist})"

        return f"crop={crop_w}:{crop_h}:0:'{y_expr}'", ""
