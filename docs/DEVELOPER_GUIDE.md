# 🛠️ Developer Guide — DMD GIF Converter

Welcome to the DMD GIF Converter codebase! This guide will help you understand the architecture, how the different components communicate, and how to extend the application with new features.

---

## 🏗️ Architecture Overview

The application follows a strict **Model-View-Controller (MVC) and layered architecture**, designed around a **CLI-First** principle. This means the engine is completely decoupled from the graphical interface, and everything the UI can do must be achievable via the Command Line Interface (`main.py`).

The codebase is divided into two main domains:
1. **`src/engine/`**: The core processing logic (FFmpeg wrappers, AI tracking, Video decoding). It has **zero dependencies** on Tkinter or the UI and can be run entirely headlessly.
2. **`src/ui/`**: The graphical interface built with `CustomTkinter`. It acts strictly as a visual wrapper that configures and dispatches commands to the engine.

### The 3 Core Layers

#### 1. The Model Layer (`src/ui/models/`)
The `ApplicationState` acts as the single source of truth for the UI. It stores all user preferences, slider values, and toggles using `tkinter.Variable` objects. The UI panels observe these variables, and the controllers read them when a task starts.

#### 2. The Engine & Plugin Layer (`src/engine/`, `src/plugins/`)
This is where the magic happens. It is subdivided into:
- **`api.py` (`dmd_gif_converter` public facade)**: Exposes the stateless `DmdMediaProcessor`, `DmdClipConfig`, `DMDS` `.rgb565.stream` utilities, and `resolve_panorama_scroll_axis()` with zero Tkinter/X11 dependencies.
- **`conversion/`**: Handles FFmpeg filter-graph construction (`core.py`), orientation-aware panorama scaling/scrolling, hardware encoder selection (`hardware_accel.py`), and multithreaded batch execution (`concurrent.futures.ThreadPoolExecutor`).
- **`auto_action/` & `src/plugins/`**: Contains the YOLOv8 ONNX + `FFmpegPipeReader` pipeline (`pipeline.py`), camera geometry (`camera.py`), floor/scene analysis (`analysis/analysis.py`), and modular plugins:
  - `IDetector` (`src/plugins/detectors/detector.py`): Runs YOLOv8 ONNX (with context-aware thread allocation) and MOG2 motion segmentation.
  - `ITracker` (`src/plugins/trackers/tracker.py`): Runs the 12-stage `TrackingEngine` pipeline (`DetectionStage`, `FloorEstimationStage`, `FaceClippingStage`, etc.).
  - `IRenderer` (`src/engine/auto_action/renderer.py`): Crops frames cleanly for downstream FFmpeg encoding.

#### 3. Event Bus and Controllers (`src/ui/core/event_bus.py`, `src/ui/controllers/`)
The UI is decoupled from the engine using an `EventBus`. UI components publish events (e.g. "FilesAdded", "PreviewRequested") rather than holding direct references to controllers. Controllers subscribe to these events and spawn background threads to communicate with the Engine.

---

## 🚦 Application Flow (How a Conversion Works)

1. **User Action**: The user clicks "Convert All" in the `LeftPanel`.
2. **Controller Dispatch**: The UI triggers `ConversionController.on_action("convert_all")`.
3. **Multithreading**: The controller spawns a `concurrent.futures.ThreadPoolExecutor` based on the user's CPU core count (`max(1, min(16, os.cpu_count() // 2))`).
4. **Engine Execution**: The worker pool calls `process_file()` in `src/engine/conversion/core.py` concurrently for multiple files.
5. **AI Processing**: If Auto-Action is enabled, `core.py` first calls the `auto_action/pipeline.py` which spawns `FFmpegPipeReader` for non-blocking I/O video decoding.
6. **FFmpeg Encoding**: `core.py` builds the complex FFmpeg `-filter_complex` string based on the `ApplicationState` (colorimetry, zoom, pixel-art text) and executes it.
7. **Updates**: Throughout the process, the Engine triggers callbacks passed by the Controller, which then safely updates the UI using `widget.after(0, ...)`.

---

## 🧩 How to Extend the Application

### 1. Adding a New AI Model / Tracker
If you want to replace YOLOv8 with a different model (e.g., MediaPipe or a different ONNX model):
- Create a new class in `src/engine/auto_action/` that implements the `IDetector` interface.
- Implement the `detect(frame)` method to return a list of `CamRect` (bounding boxes).
- Update the Factory or `pipeline.py` to instantiate your new detector instead of the YOLO detector.

### 2. Adding a New Video Filter (FFmpeg)
If you want to add a new visual effect (e.g., a VHS glitch filter):
1. Add a new `BooleanVar` or `DoubleVar` to `ApplicationState`.
2. Create a UI toggle or slider in `src/ui/settings/advanced_settings.py` and bind it to your variable.
3. In `src/engine/conversion/core.py`, inside the `process_file()` function, read your variable from the configuration dictionary.
4. Append your specific FFmpeg filter string to the `filter_graph` variable.

### 3. Adding UI Components
All UI components are modular and contained in `src/ui/panels/` or `src/ui/settings/`.
- Never put heavy computation inside a UI class.
- If your UI needs to trigger an action, use `EventBus.publish()`.
- If your UI needs to react to an action, use `EventBus.subscribe()`.

---

## 🎯 Camera, Panorama & Tracker Invariants (v8.0.11)

When modifying conversion geometry (`core.py`), camera framing (`camera.py`), floor estimation (`analysis.py`), or sprite detection (`detector.py`), preserve the following deterministic invariants:

1. **Orientation-Aware Panorama Axis & Uniform Zoom-to-Cover (`resolve_panorama_scroll_axis`)**:
   - Defined in `src/engine/conversion/core.py` and re-exported at top level (`dmd_gif_converter.resolve_panorama_scroll_axis`).
   - Under `scroll_direction="auto"`:
     - **TATE panels** (`target_height > target_width`, e.g. `64×128`, `32×128`) **always** pan `"horizontal"` (left-to-right), centering vertically if zoomed.
     - **YOKO panels** (`target_width > target_height`, e.g. `128×32`, `128×64`, `256×64`) **always** pan `"vertical"` (top-to-bottom), centering horizontally if zoomed.
     - **Square panels** (`target_width == target_height`, e.g. `64×64`) pan `"horizontal"` when `src_w > src_h` and `"vertical"` otherwise.
   - Scaling uses uniform 1:1 Lanczos zoom-to-cover (`force_original_aspect_ratio=increase` followed by exact crop) with guaranteed minimum pan travel in `force_panorama_scroll` mode and zero black bars. RGBA/LA/palette-transparent PIL inputs in `DmdMediaProcessor.process_image_panorama` are alpha-composited onto pure `#000000` black before FFmpeg runs.

2. **Close-Up Eye-to-Mouth Framing (`closeup_eye_mouth_fractions`)**:
   - Defined in `src/engine/auto_action/camera.py` and consumed by both `camera.py` (`_build_camera_rect`) and `src/plugins/trackers/tracker.py` (`TrackingEngine._clip_to_face_roi`).
   - YOLOv8 `person` close-up boxes (`aspect = rh / rw <= 1.4`) span from crown/hair down to neck/upper shoulders. `closeup_eye_mouth_fractions(aspect)` returns `(0.23, 0.38)` (`[0.23..0.61]*rh`, midpoint `0.42*rh`) for `aspect <= 1.0`, and scales smoothly upward via `1.0 / (1.0 + 0.50 * max(0.0, aspect - 1.0))` across bust shots (`1.0 < aspect <= 1.4`) so 4:1 and 2:1 DMD strips capture both eyes and mouth without drifting up into the forehead or down onto the chin.

3. **Stance-Aware Bidirectional & Lower-Envelope Floor Tracking (`_FloorEstimator`, `ValidationStage` & `_smooth_platformer_camera`)**:
   - Defined in `src/engine/analysis/analysis.py`. Replaces one-way downward-only locking with response regimes fed **exclusively** on fresh detector frames (`context.fresh_detection = True` in `FloorEstimationStage`):
     - `_ALPHA_ATTACK = 0.28` / `_ALPHA_DROP = 0.58` (`0.80` on 2nd+ consecutive lower sample): Smooth convergence on same-level ripples and brisk downward step-down onto lower platforms (`rb > floor_y + 0.055 * frame_h`), coupled with `roi_history` flush on `> 8%` downward drops and bounded platformer smoothing (`_smooth_platformer_camera`).
     - `_ALPHA_RELEASE_JUMP = 0.01`: Rock-steady hold during transient same-platform jump arcs (`< 1 px` drift).
     - `_ALPHA_RELEASE_STANCE = 0.38` + **Lower-Envelope Chain-Jump Adaptation (`0.24`)**: Upward re-anchoring onto a confirmed higher platform once `>= 4..6` fresh samples have tight foot spread while elevated, OR progressively toward the 80th-percentile lower foot envelope when `>= 5` consecutive fresh samples remain `>= 12.5%` above `_floor_y` during continuous multi-platform chain-jumping/climbing without standing still.
   - `ValidationStage` enforces a kinematic target-switch probation gate (`2..3` corroborated fresh detections required before switching to a spatially disjoint sprite), preventing 1–2 frame enemy/firebar/projectile spikes from hijacking camera focus or corrupting `_FloorEstimator`.
   - `CameraBuilderStage` and `_smooth_platformer_camera` ramp upward pursuit continuously across the upper `24%` of the strip (with bounded per-frame vertical step `<= 0.20..0.24 * ch`) and suppress vertical jump look-ahead (`eff_scroll_vy = 0.0`), eliminating both late freeze and sudden catapult jumps.

4. **Unified Sprite-Priority & Imaginary Floor Line Framing (`_build_camera_rect`, `FloorEstimationStage` & `platformer_floor_ratio = 0.90`)**:
   - Default `platformer_floor_ratio` is `0.90` (~3.2 px ground strip on a 32 px DMD — strictly 3 to 4 pixels of ground) paired with `_PLATFORMER_HEAD_PAD_RATIO = 0.11` (~3.5 px top headroom) across both `platformer` and `fighting_2d`.
   - Small/normal sprites (`standing_h <= 0.79 * crop_h`) stay locked on the true platform floor line (`imaginary_raise = 0`), while tall sprites (`standing_h > 0.79 * crop_h`) raise an imaginary floor line up to the knees/thighs (`active_floor_y = floor_y - (standing_h - max_fit_h)`) until the face sits cleanly with ~3.5 DMD px headroom. That imaginary floor line stays locked across crouches, jumps, and landings until a platform change updates `_FloorEstimator`.

5. **Scroll-Compensated Motion, 2D Subject Continuity & Projectile/Hazard Filtering (`_FrameDetector`)**:
   - In `src/plugins/detectors/detector.py`, platformer motion detection estimates global 2D camera scroll via Hanning-windowed `cv2.phaseCorrelate` (`_build_scroll_compensated_mask`) to cancel scrolling background pipes/clouds/walls and isolate screen-centered jumping sprites, while stripping wide horizontal ground/HUD slabs (`>= 38%` frame width).
   - Both YOLOv8 (`0.36` default platformer confidence floor when `roi_confidence_min == 0.0`) and motion platformer scorers combine 2D trajectory continuity (`expected_cx`, `expected_cy`) with airborne hero floor-penalty protection, `expected_h` projectile/bubble scale demotion (`< 48%` hero height), and chromatic sprite salience so grounded enemies, sawblades, and projectiles never hijack an airborne hero.

---

## 🛡️ Engineering Rules

- **CLI-First Principle**: Everything the application can do via the UI must be possible via the CLI interface. The UI is just a convenience wrapper.
- **No UI in the Engine**: Files inside `src/engine/` must **never** import `tkinter` or `customtkinter`. The engine must remain fully runnable via the terminal without a graphical environment.
- **Thread Safety**: Never update a Tkinter widget directly from a background thread. Always use `EventBus` and `widget.after()` or a thread-safe queue to schedule UI updates on the main thread.
- **Hardware Acceleration**: Always rely on `hardware_accel.py` to get the H.264 encoder. Do not hardcode `libx264` unless it's the explicit fallback.

Happy coding! 🚀
