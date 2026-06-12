# DMD GIF Converter — Changelog

## What is New in v6.2.0?
- **📊 Continuous Scoring Matrix**: Scene detection (Auto Action) no longer relies on a rigid waterfall model. It uses a dynamic, continuous scoring matrix to identify the optimal camera profile (e.g., Platformer, Talking Closeup, Action). The scoreboard is fully visible in the UI logs.
- **🛡️ Auto Detector Fallback (Person → Hybrid)**: When tracking mixed content, if the primary `person` detector fails on a close-up or non-human subject, the engine can now instantly fall back to the `hybrid` detector mid-scene or pre-scan, ensuring a perfect cinematic shot without giving up.
- **🎯 `FIGHTING_2D` Matrix Fix**: Fixed an issue where the Scoring Matrix heavily biased live-action full-body horizontal motion (like panning in a movie) towards the `fighting_2d` preset instead of `action_moving` or `full_body_tall`.
- **🏷️ Semantic Logs for Colorimetry**: Smart Color Boost now tags your scenes directly in the UI logs (e.g., `[Dark + Low Contrast]`, `[Vivid]`) so you know exactly how the AI perceives your footage.
- **🛡️ Thread-Safe Stderr Suppression**: Fixed a critical concurrency bug where multiple parallel conversions would permanently redirect the application's terminal output to `/dev/null`. C-level `stderr` suppression is now fully protected by a `threading.Lock`.
- **📝 UI Log Interception Fix**: Engine `logger.info()` calls (which bypassed the UI and printed directly to the terminal) have been consolidated into the final conversion payload, ensuring that all Auto Action reasoning and scoring matrices appear perfectly inside the application's Log Panel.

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
