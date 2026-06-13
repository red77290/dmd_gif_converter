import json
import uuid
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class AutoActionDecisionLogger:
    """Handles the formatting of AutoAction decisions into an ASCII table and a JSON file."""

    @staticmethod
    def process_decisions(src_path: str, cfg, analyzer, reader) -> str:
        task_id = uuid.uuid4().hex[:5].upper()
        filename = Path(src_path).name

        # ── Generate Reasons Dictionary ──
        reasons = {}
        codes = getattr(analyzer, "decision_codes", {})
        driver = codes.get("driver", "fallback")
        scene_type = analyzer.scene_profile.scene_type if getattr(analyzer, "scene_profile", None) else "Unknown"

        if driver == "scene_profile":
            reasons["face_priority"] = f"Scene profile ({scene_type}) requires tight framing." if analyzer.face_priority_mode else f"Not required by {scene_type} profile."
            reasons["auto_vertical_bias"] = f"Floor tracking enabled by {scene_type} profile." if getattr(cfg, "auto_vertical_bias", False) else f"Disabled by {scene_type} profile."
            reasons["auto_bottom_crop"] = "Significant gap at the bottom or inherited from face priority."
            reasons["auto_top_crop"] = "Head framing required by scene profile." if getattr(cfg, "auto_top_crop", False) else "No face priority required."
            reasons["strength"] = f"Optimal parameter defined by {scene_type} profile."
            reasons["smoothness"] = f"Optimal smoothness defined by {scene_type} profile."
        elif driver == "tall_subject":
            reasons["face_priority"] = "Very tall subject detected, switching to portrait mode."
            reasons["auto_vertical_bias"] = "Floor tracking disabled (contradictory with portrait mode)."
            reasons["auto_bottom_crop"] = "Bottom crop forced to frame the upper body."
            reasons["auto_top_crop"] = "Top crop forced to frame the head."
            reasons["strength"] = "Reduced strength to stabilize the tall subject."
            reasons["smoothness"] = "Increased smoothness to prevent motion sickness."
        elif driver == "floor_tracking":
            reasons["face_priority"] = "Subject not dominant, face priority disabled."
            reasons["auto_vertical_bias"] = "Floor line detected, tracking enabled."
            reasons["auto_bottom_crop"] = "Significant gap at the bottom of the screen." if getattr(cfg, "auto_bottom_crop", False) else "Feet are close to the bottom edge."
            reasons["auto_top_crop"] = "Unnecessary for standard video games."
            reasons["strength"] = "High strength to track fast action."
            reasons["smoothness"] = "Standard smoothness."
        else:
            reasons["face_priority"] = "Standard subject, no portrait mode required."
            reasons["auto_vertical_bias"] = "No trackable floor detected."
            reasons["auto_bottom_crop"] = "Gap detected at the bottom." if getattr(cfg, "auto_bottom_crop", False) else "Screen is filled."
            reasons["auto_top_crop"] = "Gap detected at the top." if getattr(cfg, "auto_top_crop", False) else "Screen is filled at the top."
            reasons["strength"] = "Standard default strength."
            reasons["smoothness"] = "Standard default smoothness."

        pb_code = codes.get("pillarbox", "disabled")
        if pb_code == "detected":
            reasons["pillarbox"] = "Black margins detected on sides (median > 5%)."
        else:
            reasons["pillarbox"] = "No intrusive black borders detected."

        # ── 1. Create Decision JSON ──
        decision_data = {
            "task_id": task_id,
            "file_info": {
                "filename": filename,
                "video_width": reader.frame_w,
                "video_height": reader.frame_h,
                "duration_frames": reader.total_frames
            },
            "camera_params": {
                "strength": {"value": cfg.strength, "reason": reasons.get("strength", "")},
                "smoothness": {"value": cfg.smoothness, "reason": reasons.get("smoothness", "")}
            }
        }
        
        if getattr(analyzer, "scene_profile", None):
            decision_data["scene_classification"] = {
                "winner": analyzer.scene_profile.scene_type,
                "face_clip_mode": analyzer.scene_profile.face_clip_mode,
                "scoreboard": getattr(analyzer, "scene_scores", {})
            }
        
        if hasattr(analyzer, "scene_signals"):
            decision_data["raw_signals"] = analyzer.scene_signals
            
        decision_data["decisions"] = {
            "face_priority": {
                "value": analyzer.face_priority_mode,
                "reason": reasons.get("face_priority", "")
            },
            "auto_vertical_bias": {
                "value": getattr(cfg, "auto_vertical_bias", False),
                "reason": reasons.get("auto_vertical_bias", "")
            },
            "auto_bottom_crop": {
                "value": getattr(cfg, "auto_bottom_crop", False),
                "reason": reasons.get("auto_bottom_crop", "")
            },
            "auto_top_crop": {
                "value": getattr(cfg, "auto_top_crop", False),
                "reason": reasons.get("auto_top_crop", "")
            },
            "pillarbox": {
                "value": f"L:{analyzer.effective_frame_left}px",
                "reason": reasons.get("pillarbox", "")
            }
        }
        decision_data["auto_crop_margins"] = {
            "top_pct": getattr(analyzer, "tcp", 0.0),
            "bottom_pct": getattr(analyzer, "bcp", 0.0),
        }

        # Save JSON to the same directory as source file
        json_path = Path(src_path).parent / f"{Path(src_path).stem}_decision.json"
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(decision_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Could not save decision JSON: {e}")

        # ── 2. Format ASCII Table ──
        msg_lines = []
        msg_lines.append(f"\n============================================================")
        msg_lines.append(f"🎬 VIDEO : {filename}  |  ID: #{task_id}")
        msg_lines.append(f"🧠 AI DECISION MATRIX (Auto-Action)")
        msg_lines.append(f"============================================================")
        msg_lines.append(f"🎯 SCENE DETECTED       : {scene_type}")
        msg_lines.append(f"------------------------------------------------------------")
        
        def fmt_row(name, val, val_str, reason_key):
            icon = "✅" if val else "❌"
            reason = reasons.get(reason_key, "")
            return f"[{icon}] {name:<18} : {val_str}\n     └─ Reason : {reason}"

        fp_val = analyzer.face_priority_mode
        msg_lines.append(fmt_row("Face Priority", fp_val, "ACTIVE" if fp_val else "INACTIVE", "face_priority"))
        
        vb_val = getattr(cfg, "auto_vertical_bias", False)
        msg_lines.append(fmt_row("Floor Tracking", vb_val, "ACTIVE" if vb_val else "INACTIVE", "auto_vertical_bias"))
        
        bc_val = getattr(cfg, "auto_bottom_crop", False)
        bc_str = f"ACTIVE ({getattr(analyzer, 'bcp', 0.0):.1%})" if bc_val else "INACTIVE"
        msg_lines.append(fmt_row("Bottom Crop", bc_val, bc_str, "auto_bottom_crop"))
        
        tc_val = getattr(cfg, "auto_top_crop", False)
        tc_str = f"ACTIVE ({getattr(analyzer, 'tcp', 0.0):.1%})" if tc_val else "INACTIVE"
        msg_lines.append(fmt_row("Top Crop", tc_val, tc_str, "auto_top_crop"))
        
        right_px = analyzer.frame_w - analyzer.effective_frame_left - analyzer.effective_frame_w
        pb_left = analyzer.effective_frame_left > 0
        pb_right = right_px > 0
        pb_val = pb_left or pb_right
        if pb_val:
            parts = []
            if pb_left:
                parts.append(f"Left: {analyzer.effective_frame_left}px")
            if pb_right:
                parts.append(f"Right: {right_px}px")
            pb_str = f"ACTIVE ({', '.join(parts)})"
        else:
            pb_str = "INACTIVE"
        msg_lines.append(fmt_row("Pillarbox Crop", pb_val, pb_str, "pillarbox"))

        msg_lines.append(f"------------------------------------------------------------")
        msg_lines.append(f"🎥 CAMERA PARAMETERS")
        msg_lines.append(f"Tracking Strength       : {cfg.strength:.2f}  (Reason: {reasons.get('strength', '')})")
        msg_lines.append(f"Smoothness              : {cfg.smoothness:.2f}  (Reason: {reasons.get('smoothness', '')})")
        msg_lines.append(f"============================================================")
        
        return "\n".join(msg_lines)
