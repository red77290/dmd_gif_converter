# DMD GIF Converter — Changelog

## [7.0.0] - Architecture & Performances (V7)
- **🚀 Fixed Parallel Conversion UX**: Resolved a visualization bottleneck where parallel folder/queue conversions appeared to execute sequentially because the heavy OpenCV/YOLO video preprocessing ran silently without emitting progress reports. Added progressive frame-by-frame callback updates to `preprocess_video_for_dmd` and fixed a keyword parameter signature mismatch in `ConversionController`.
- **🚀 Fixed Anime Close-up Classification**: Falsely classified anime and close-up action scenes (like `visage_anime_1.gif`) as `TOP_DOWN_ISOMETRIC`. We introduced an `effective_floor_in_lower` concept so massive subjects don't trigger "floor found" penalties, relaxed the closeup aspect ratio guard for very large subjects, and unconditionally penalized `TOP_DOWN_ISOMETRIC` when the subject occupies more than 30% of the frame.
- **🚀 Fixed Fallback UnboundLocalError**: Fixed a crash where the `_auto_scene` variable was used before definition if the scan detected no targets.
- **🚀 Decoupled Circular Imports**: Exposed `available_detectors` lazily in `src/engine/auto_action/__init__.py` to allow direct, isolated test execution of individual modules without circular package dependency errors.
- **🚀 Fixed Letterbox Drifting**: Integrated active letterbox cropping boundaries directly into the tracking engine's frame window properties, preventing the camera from panning into black bars (resolving the eye cutoff on characters like Doc/Marty in Back to the Future).
- **🚀 Kept Content Mode Menu Enabled**: The "Content mode" dropdown remains enabled when "Smart Color Boost" / "Let me handle it" is active, allowing users to specify the content genre (e.g. anime) for the auto-action framing engine while keeping color parameters fully automatic.
- **🚀 Fixed `FIGHTING_2D` Scene Profile**: Restored `fighting_2d` and added `platformer_mode=True` to eliminate the flooring bug that previously caused fighting games to lose the floor. 
- **🚀 Fixed Platformer Flooring Bug**: The `platformer` profile now explicitly ignores floating blocks (which falsely created huge bounding boxes), while the `fighting_2d` profile natively shifts the camera up to protect huge character heads. The two genres are now perfectly differentiated in the scoring matrix.
- **🚀 Fixed Ceiling Pareidolia**: YOLO's tendency to mistake ceiling blocks for players in platformers is now blocked. The detector actively rejects tracking boxes in the upper 40% of the screen when establishing an initial floor, and rejects sudden 50% vertical jumps when a floor is already established.
- **🚀 Fixed `WIDE_SHOT` False Positives**: Game characters that are perfectly centered by a follow-camera (having near-zero variance) are no longer misclassified as cinematic wide shots or static menus.
- **🏗️ Strict Type Safety**: Replaced primitive tuples with `NamedTuple` (`CamRect`, `BoundingBox`) to prevent cognitive errors with index positional access.
- **🏗️ Component Composition**: Fully removed UI Mixins (God Object anti-pattern) in favor of strict Composition across all interface panels.
- **⚡ Async I/O Pipeline**: Overhauled the `preprocess_video_for_dmd` pipeline to use a `queue.Queue` Producer/Consumer model, running OpenCV, YOLO, and FFmpeg in dedicated threads.
- **🧠 Configurable AI FPS**: The `ai_moments.py` temporal scoring is no longer hardcoded to 2.0 FPS, allowing finer temporal resolution adjustments via the new `analyze_fps` parameter.

## What is New in v7.0.0?
- **🧠 Scoring V2 Engine**: A complete rewrite of the mathematical scoring system. AI Moments now evaluates pure Temporal Signals (Contrast, Entropy, Edge Density, Motion) and Spatial Composition (Readability, Clutter) separately, then applies dynamic strategy weights (`Action`, `Balanced`, `Character`). This massively improves the reliability of extracted moments.
- **🔬 A/B Testing Runner**: Added a dedicated `ab_runner.py` CLI and A/B Testing UI Panel to directly compare Scoring V1 against Scoring V2 on entire video folders. Generates detailed markdown reports.
- **👁️ Cinematic Rule-of-Thirds Framing**: Refined the Auto Action tracker math for close-ups. It now ignores the top 25% of the bounding box (hair/forehead) and targets the next 35% (face region). We also restored the vertical eye safety cap (`cy = min(cy, y + 0.25 * crop_h)`) in the camera builder. This prevents the camera from cropping below the eyes and starting at the nose, keeping both eyes and mouth beautifully framed even on extra-short 4:1 display matrices.
- **🏗️ Tracker Pipeline Architecture**: The monolithic `TrackingEngine.process_frame()` method was completely refactored into a cleanly decoupled Pipeline pattern (Chain of Responsibility) utilizing 12 modular stages (`DetectionStage`, `FaceClippingStage`, `HistorySynthesisStage`, etc.) connected by a strongly typed `FrameTrackingContext`.
- **📝 Dynamic Log Tags**: The engine now emits real-time `[DYNAMIC]` log tags, allowing users to monitor camera cuts and Continuous Scoring Matrix profile transitions directly in the UI Log Panel.

## What is New in v6.3.0?
- **📊 Continuous Scoring Matrix**: Scene detection (Auto Action) no longer relies on a rigid waterfall model. It uses a dynamic, continuous scoring matrix to identify the optimal camera profile (e.g., Platformer, Talking Closeup, Action). The scoreboard is fully visible in the UI logs.
- **🛡️ Auto Detector Fallback (Person → Hybrid)**: When tracking mixed content, if the primary `person` detector fails on a close-up or non-human subject, the engine can now instantly fall back to the `hybrid` detector mid-scene or pre-scan, ensuring a perfect cinematic shot without giving up.
- **🎯 `FIGHTING_2D` Matrix Fix**: Fixed an issue where the Scoring Matrix heavily biased live-action full-body horizontal motion (like panning in a movie) towards the `fighting_2d` preset instead of `action_moving` or `full_body_tall`.
- **🏷️ Semantic Logs for Colorimetry**: Smart Color Boost now tags your scenes directly in the UI logs (e.g., `[Dark + Low Contrast]`, `[Vivid]`) so you know exactly how the AI perceives your footage.
- **🛡️ Thread-Safe Stderr Suppression**: Fixed a critical concurrency bug where multiple parallel conversions would permanently redirect the application's terminal output to `/dev/null`. C-level `stderr` suppression is now fully protected by a `threading.Lock`.
- **📝 UI Log Interception Fix**: Engine `logger.info()` calls (which bypassed the UI and printed directly to the terminal) have been consolidated into the final conversion payload, ensuring that all Auto Action reasoning and scoring matrices appear perfectly inside the application's Log Panel.
- **✂️ Pre-Cropper Body Amputation Fix**: Fixed a critical bug in `analysis.py` where the pre-cropper artificially truncated detection bounding boxes to the top 28% to signal face-priority mode. The smart auto-crop optimizer misinterpreted this artificial face-box as the true bounds of the subject and permanently cropped out the entire body before tracking even began. The pre-cropper now preserves the full body bounding box, leaving dynamic face zooming to the tracker engine.
- **🔗 Config Injection Tracker Fix**: Fixed the root cause of excessive zooming on character hair. `analyzer.py` was never injecting the detected `scene_profile` into the `AutoActionConfig` instance passed to the `TrackingEngine`. Because of this missing link, the tracker couldn't access custom eye offsets and fell back to microscopic defaults (10% body height). The analyzer now explicitly copies `scene_profile` to the config, properly binding the analysis phase to the tracking phase.
- **⚔️ Combat Animation Decapitation Fix**: Fixed a bug where anime combat scenes (`combat_anime.gif`) were misclassified as `TALKING_CLOSEUP`. The classifier mistook the very wide bounding box (covering both fighters) for a single large face. This misclassification forced the `closeup` tracking mode, which brutally skipped the top 25% of the bounding box (assuming it was hair). Added a penalty in `scene_types.py` so very wide aspect ratios (`< 0.85`) can no longer trigger `TALKING_CLOSEUP`, allowing proper fallback to `FIGHTING_2D` or `PLATFORMER` which frame the full body.

## What is New in v6.1.0?
- **🎯 Close-up Hair Detection Fix**: The auto-action tracker now correctly identifies close-up faces (`roi_h > 40 % of frame height`) and skips the top 25 % of the bounding-box (hair) to lock onto the eye region instead of forehead/hair — eliminating the camera drift bug on anime-style content.
- **📸 Face-Priority Camera Fix**: Corrected a `face_priority_mode` miscalculation in `camera.py` where `cy` was placed ~300 px below the face due to using crop height instead of ROI height. The camera now stays locked on the eye region.
- **🔇 C-Level Stderr Suppression**: OpenCV's `[mp3float @ ...] Header missing` messages (which bypass Python's logging system and write directly to file-descriptor 2) are now silenced via a `_quiet_c_stderr()` context manager using `os.dup2`.
- **📐 UI Layout Fixes**: DMD preview no longer crushes the Source/Auto previews (removed `weight=1` from wrong row). Log panel no longer hides Convert and Generate AI Moment buttons.
- **🚌 EventBus Decoupling**: `FILES_ADDED_TO_QUEUE`, `PREVIEW_SOURCE_CHANGED`, and `PREVIEW_REFRESH_REQUESTED` events now fully decouple AI Moments → Left Panel and Middle Panel → Preview Panel.
- **🔤 Code Cleanup**: All source-code comments translated from French to English throughout the codebase.
- **🧪 Test Coverage Expanded**: New dedicated test files — `test_tracker_closeup.py` (8 tests), `test_camera.py` (18 tests, full rewrite), `test_event_bus_integration.py` (13 tests) — covering every bug fixed in this release.

## What is New in v6.0.0?
- **🤖 AI Iconic Moments**: A brand new dedicated tab to automatically analyze entire videos and extract the absolute best "moments" using advanced criteria (Action, Epic cuts, Character presence, Loopability, and DMD Visibility). It even provides a seamless one-click bridge to open the discovered moment in the Converter! [Read the full guide here.](AI_MOMENTS.md)
- **🎬 Studio Timeline & CLI Extraction**: A massive upgrade to the AI Moments engine. Features a brand new interactive Studio Timeline with IN/OUT points and looping playback. Full CLI parity added via the `--ai-moments` flag.
- **🪄 Text Magic (Text Overlay)**: Added full support for text overlays (Fonts, Styles, Background) with built-in animations (`blink`, `scroll_left`, `scroll_up`) directly in the UI.

## What is New in v5.1.0?
- **🧩 Generic Modularity Extended**: The application's core modular design (interfaces for Converter, Tracker, Detector) is now extended to the GIF Search Engine. A generic `ISearchEngine` interface orchestrates DuckDuckGo, Tenor, and Giphy seamlessly without code duplication, ensuring maximum reusability and scalability across the UI and utility scripts.

## What is New in v5.0.0?
- **🏗️ Under-the-hood Refactoring**: Massive architectural overhaul splitting the monolithic scripts into a modular `src/` package (`auto_action`, `converter`, `ui`) for easier debugging and maintainability.
- **🤖 Let me handle it**: Now explicitly enforces visibility scoring for optimal framing.
- **👁️ DMD Quality Scoring & Smart Conversion**: The UI now separates pending files from converted files. Every generated GIF receives a Quality Score (0-100%). Use the **Cleanup Assistant** to instantly trash bad conversions!

## What is New in v4.0.0?
- **🏗️ Modular UI & Engine**: Refactored the UI application to use Multiple Inheritance Mixins for cleaner logic.
- **🎥 Smooth Tracking**: Fixed camera tracking jitter by smoothing look-ahead jumps and preserving X/Y tracking when visibility scoring fails.

## What is New in v3.1.0?
- **🔍 GIF Search Expansion**: Enhanced GIF search quantity limit to 300.
- **🔄 Folder Refresh**: Added folder refresh functionality to rescan and update files in the UI without restarting.

## What is New in v3.0.0?
- **🌐 Built-in GIF Search**: Introduce GIF Search functionality to download GIFs from DuckDuckGo, Tenor, and Giphy directly from the UI.
- **🚥 LED Simulation**: Added LED pixel simulation feature for DMD preview with toggle option to see exactly how it will look on hardware.

## What is New in v2.1.0?
- **📐 Advanced Crop**: Added auto crop features for top and bottom boundaries in the action camera.
- **⚙️ Per-GIF Configuration**: Implement Per-GIF configuration feature for independent settings per file in the batch list.

## What is New in v2.0.0?
- **🪄 Text Magic**: Added support for text overlay directly in GIF conversion.
- **🎨 Smart Color Boost**: Implemented Smart Color Boost for AI-driven colorimetry analysis, drastically improving dark/night scenes.
- **👤 Background Subtraction**: Added support to remove backgrounds.

## What is New in v1.0.0?
- **🚀 Initial Release**: Base converter engine, GUI, HUB75 colorimetry profiles, ping-pong scrolling, and anti-transparency safeguards.
