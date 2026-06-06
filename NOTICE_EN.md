# DMD GIF Converter - User Manual

Welcome to the DMD GIF Converter! This tool automatically converts your videos, GIFs, and images into highly optimized sequences for low-resolution LED matrix displays (like Pinball DMDs or LED panels).

## Core Philosophy

When converting videos to very low resolutions (e.g. 128x32 or 256x64), the most important thing is **readability**. A perfect 4K tracking algorithm is useless if the subject is too small to recognize on a pixel display. Our engine is designed to focus on the action, stabilize the framing, and guarantee that the result will look great on your LED matrix.

## Key Features

1. **Smart Auto Crop** 🤖: Analyses the video to determine if it should track a character's face, stick to the floor (for platformer games), or ignore the sky.
2. **Platformer Mode** 🎮: Specially tuned for 2D side-scrolling games (like Mario, Sonic, Metroid). It locks the floor to the bottom of the display and smoothly scrolls ahead of the character.
3. **Action Tracking** 🏃: Uses a lightweight AI (YOLO) combined with motion detection to follow the subject seamlessly.
4. **DMD Quality & Readability Scoring** 👁️: The engine will evaluate all generated GIFs and give them a score from 0-100% based on contrast, occupancy, and shape separation.
5. **Smart Conversion Management (GUI)** 📋: The new UI separates your pending files from converted ones. Converted files are automatically sorted by Quality Score, allowing you to use the **Cleanup Assistant** to instantly trash bad conversions and only keep the best ones.
6. **Auto Tuning & Debug** 🛠️: If something looks wrong, you can enable the debug dataset to see exactly what the engine sees.

## Quick Start (Command Line)

To simply convert a video with the smartest defaults:

```bash
python main.py input.mp4 --smart-crop --platformer
```

### Important Flags
- `--smart-crop`: Let the engine decide how to frame the video.
- `--platformer`: Use this for 2D games to keep the floor level.
- `--look-ahead 0.25`: Makes the camera look slightly ahead of where the character is moving.
- `--detect hybrid`: Combines AI person tracking with motion tracking for best results.
- `--intro-duration 1.5`: Shows the full scene for 1.5 seconds before zooming in on the action.

## Troubleshooting

- **The camera is too jittery!** 
  Increase smoothness: `--smoothness 0.95`
- **It keeps zooming in on random background movement.**
  Use a higher confidence limit: `--roi-conf 0.4`
- **I'm playing a fighting game and it only follows one player!**
  Make sure multi-fusion is on (it is by default in smart mode).

For more advanced configuration, you can edit the script directly or pass the additional pipeline arguments described in the developer documentation.
