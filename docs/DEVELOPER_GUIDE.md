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

#### 2. The Engine Layer (`src/engine/`)
This is where the magic happens. It is subdivided into:
- **`conversion/`**: Handles the FFmpeg command building (`core.py`) and execution. It uses hardware acceleration (`hardware_accel.py`) and utilizes massive multithreading via `concurrent.futures.ThreadPoolExecutor` for parallel processing.
- **`auto_action/`**: Contains the YOLOv8 and FFmpegPipeReader pipeline (`pipeline.py`). It uses a strict interface-driven approach:
  - `IDetector`: Runs the YOLO ONNX model (now using dynamic threads depending on batch vs standalone execution).
  - `ITracker`: Handles subject smoothing, zooming, and bounding box logic.
  - `IRenderer`: Crops the frames using fast resizing instead of heavy OpenCV operations.

#### 3. The Controllers (`src/ui/controllers/`)
Instead of an Event Bus, the UI is decoupled from the engine through Controllers (`ConversionController`, `AutoController`, `SourceController`). The UI sends user actions to the controllers, which then spawn background threads to communicate with the Engine.

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

- **CLI-First Principle**: Everything the application can do via the UI must be possible via the CLI interface. The UI is just a convenience wrapper.
- **No UI in the Engine**: Files inside `src/engine/` must **never** import `tkinter` or `customtkinter`. The engine must remain fully runnable via the terminal without a graphical environment.
- **Thread Safety**: Never update a Tkinter widget directly from a background thread. Always use `EventBus` and `widget.after()` or a thread-safe queue to schedule UI updates on the main thread.
- **Hardware Acceleration**: Always rely on `hardware_accel.py` to get the H.264 encoder. Do not hardcode `libx264` unless it's the explicit fallback.

Happy coding! 🚀
