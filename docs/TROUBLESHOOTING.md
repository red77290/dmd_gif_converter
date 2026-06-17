# Troubleshooting

## ❓ Troubleshooting

| Problem | Solution |
|---|---|
| `ffmpeg: command not found` | FFmpeg not in PATH → re-read installation section |
| Preview is blank | FFmpeg must be installed and in PATH |
| `[ERROR] xxx — metadata unreadable` | Corrupted or unsupported file |
| Very slow conversion | Increase `--workers` (use `--no-auto-workers` to override limits) |
| Colours too saturated | Switch to `--mode anime` or lower `--saturation` in custom mode |
| Output too dark | Raise `--brightness` (e.g. `0.05`) or `--gamma` (e.g. `0.95`) |
| Scroll too fast / slow | Adjust `--scroll-speed` (default `24.0`) |
| Stops at wrong position | Adjust `--scroll-cycles` (default `1.5` = centre hold) |
| Banding on gradients | Switch to `anime` or `cinema` — dithering causes streaks with scrolling |
| DMD preview not auto-refreshing | Wait ~2 s after last slider move; make sure a file is selected |
| LED Sim preview looks wrong / too dark | The grid is normal — it shows the physical gap between LEDs. Toggle **💡 LED Sim** off for the classic upscaled view |
| LED Sim canvas is very large | Expected for multi-panel configs — the 4× zoom is clamped at 640 px width |
| Manual mode shows wrong area | Increase Zoom first, then move X/Y sliders |
| Auto Action says "OpenCV not installed" | Run `pip install opencv-python onnxruntime` or re-run `./launch_ui.sh` (installs automatically) |
| Auto Action preview is slow to appear | Normal — AI analysis takes a few seconds per video; progress shown in the AUTO ACTION canvas |
| Auto Action result looks wrong | Try a different **Detection mode** (`motion` or `hybrid`) — `person` mode works best with visible human silhouettes |
| Auto Action: "model download failed" | No internet access — place `yolov8n.onnx` manually in `~/.cache/dmd_gif_converter/`. Falls back to motion detection automatically |
| Smart Auto Crop gives wrong results | Disable it and activate each option individually — use `Auto bottom crop`, `Auto top crop`, `Auto floor detect` independently |
| Smart Auto Crop activates nothing | Not enough detections in the 60-frame scan — try a different detector mode (`motion` or `hybrid`) |
| Face cut off at shoulder level | Known issue fixed in v5.0.0 — update to the latest version; the engine now uses chin-level detection (20 % of body height) with asymmetric padding |
| Auto Action fails with GIF source | Fixed in v5.0.0 — GIFs are now pre-converted via FFmpeg before OpenCV processing to avoid BGRA transparency issues |
| `[ACTION] … FFmpeg pipe encoding failed` | Check the log for the full FFmpeg stderr message (now included). Most likely cause: GIF with transparency palette — update to v5.0.0 which pre-converts GIFs automatically |
| Floor not visible in 2-D platformer | Enable **Auto floor detect** in the Auto Action advanced settings — it anchors the camera to the detected ground level |
| Camera pans up during jumps | Enable **Auto floor detect** — it uses an asymmetric EMA that resists upward movement during airtime |
| Auto floor detect still not showing floor | Increase **Bottom crop %** to hide the HUD/floor area from the main detector, then re-enable Auto floor detect |
| Smart Color Boost makes colours look wrong | Disable it and tune manually — it works best on heterogeneous or poorly-exposed footage |
| Smart Color Boost log shows `fallback` | OpenCV unavailable — run `pip install opencv-python` |
| Text overlay not appearing | Make sure **Text Content** is not empty and the font file exists in `media/fonts/` |
| `[ERROR] Font file '…' not found` | The selected font is missing from `media/fonts/` — choose a different font in the dropdown |
| `[TEXT  ] … ffmpeg drawtext unavailable` | Normal on macOS Homebrew ffmpeg (compiled without `--enable-libfreetype`) — **Pillow fallback is used automatically**, no action required |
| GIF Search button is disabled | Install missing deps: `pip install duckduckgo-search requests` (or re-run `./launch_ui.sh`) |
| GIF Search returns 0 results | DuckDuckGo may throttle rapid searches — wait a few seconds and retry |
| Downloaded GIFs are very large | Normal for web GIFs — the converter will resize them to 128×32 automatically |
| GIF Search timeout errors | Some image hosts are slow — increase quantity (up to 300) to compensate for skipped URLs |
| Want to remove multiple GIFs at once | Hold **Ctrl** or **Shift** then click to multi-select, then press **Del** or click **✕ Remove** |
| Per-GIF Config: params seem to bleed between files | Make sure to **click** the new file (not just hover) — the save triggers on the selection-change event |
| Per-GIF Config: toggle OFF reverts to wrong params | Expected — it restores the exact state at the moment you toggled ON, not the current GIF's config |
| Per-GIF Config: configs lost after restart | Configs are session-only (RAM) — export is not yet supported |
| "Let Me Handle It" grays out sliders I need | Toggle it OFF to get full manual control again — all previous values are restored |
| "Let Me Handle It" ON but Auto Action not running | Check that OpenCV and onnxruntime are installed (`pip install opencv-python onnxruntime`) |
