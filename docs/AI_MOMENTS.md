# AI Moments & Smart Tracking

![AI Moments Studio Timeline](../media/AI_MOMENT_PREVIEW.png)

DMD GIF Converter includes an advanced **AI Moments** feature designed to automatically analyze long videos and extract the best moments for your physical DMD displays. 

## How it works (Scoring V2 Engine)

The AI Moments engine runs a multi-pass analysis on your video using the **Scoring V2 Engine**, which splits evaluation into Temporal and Spatial domains:

1. **Scene Detection**: Identifies cuts and scene changes using histogram correlation to avoid tracking across camera cuts.
2. **Temporal Signals**: Computes pure mathematical signals for each frame:
   - *Contrast*: Difference between bright and dark areas.
   - *Entropy*: Visual complexity of the frame.
   - *Edge Density*: Sharpness and details (Sobel gradient).
   - *Motion*: Optical flow intensity.
3. **Spatial Evaluator**: Evaluates DMD readability, clutter, and composition (using YOLO for subject detection).
4. **Strategy Weighting**: Dynamically applies weights based on the chosen strategy (`Action`, `Balanced`, `Character`).
5. **Non-Maximum Suppression (NMS)**: Ranks the sequences and extracts the top non-overlapping moments.

## Usage in the UI

1. Open a video in the UI.
2. Go to the **AI Moments** tab.
3. Use the **Studio Timeline** to preview your video.
4. Click **Generate AI Moments** to auto-extract the best scenes, or use the **[ Set IN ]** and **[ Set OUT ]** buttons to manually extract a specific moment.
5. Manually extracted moments and AI moments are automatically added to your conversion queue!

### Studio Timeline & Playback
You can use the **▶ Play Selection** button to endlessly loop your currently selected IN/OUT points, allowing you to perfectly frame your custom cuts before extracting them.

## Usage in the CLI

You can also automate AI Moments extraction from the command line:

```bash
# Analyze all videos in the folder, extract the top 5 moments per video, and convert them to DMD GIFs
./dmd_gif_converter.py my_videos/ --ai-moments --ai-moments-count 5 --ai-moments-strategy Action
```

## Text Magic (Animations)

To complement your AI Moments, you can add Text Overlays with built-in animations!
- Go to the **Text Overlay** settings (the "T" button).
- Choose your text, color, and font.
- Choose a **Magic Animation**:
  - `none`: Static text.
  - `blink`: Classic arcade blinking text.
  - `scroll_left`: Text scrolls smoothly from right to left.
  - `scroll_up`: Text scrolls from bottom to top.

The text overlay animation is applied directly onto the final DMD render, meaning you can adjust it instantly without re-running the heavy AI tracking pipeline.
