# AI Moments & Smart Tracking

DMD GIF Converter includes an advanced **AI Moments** feature designed to automatically analyze long videos and extract the best moments for your physical DMD displays. 

## How it works

The AI Moments engine runs a multi-pass analysis on your video:

1. **Scene Detection**: Identifies cuts and scene changes to avoid tracking across camera cuts.
2. **Subject Detection**: Uses AI (YOLO-based or ONNX) to find faces, people, and objects.
3. **Motion Analysis**: Evaluates how much action is happening.
4. **DMD Quality Prediction**: Simulates the 128x32 downscaling and evaluates contrast, readability, and clutter.
5. **Ranking**: Ranks the scenes based on action, visibility, and length.

## Usage in the UI

1. Open a video in the UI.
2. Go to the **AI Moments** tab.
3. Click "Generate Best Moments". 
4. The system will analyze the video (this may take a few minutes for long videos).
5. A list of the top-ranked moments will appear. Click on any moment to instantly preview it and optionally convert it!

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
