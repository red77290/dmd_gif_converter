# Auto Action Framing (Experimental)

This feature runs **before** the regular ffmpeg conversion pipeline.
It creates an intermediate 4:1 video that follows action/person areas, then the normal DMD conversion runs on it.

## Detection Modes

- `person` (default): prioritize person detection, fallback to motion
- `motion`: prioritize moving regions, fallback to person
- `hybrid`: merge person + motion when both are found
- `center`: disable detection and keep center framing

## UI Usage

1. Open `🔧 Advanced Settings`
2. Enable `Auto Action Framing (pre-ffmpeg)`
3. Keep detector at `person` (default) or choose another mode
4. Tune strength / smoothness / zoom max / padding

## CLI Runner

```bash
python auto_action_cli.py input.mp4 --detector person --out preprocessed.mp4
```

## Notes

- Requires OpenCV (`opencv-python`)
- If OpenCV is missing, conversion falls back to normal pipeline
- Default settings keep this feature disabled, so existing behavior is unchanged

