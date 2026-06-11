# Quickstart: Let's Start Converting

Welcome to the DMD GIF Converter. This tool makes it trivial to convert folders of videos into 128x32 pixel GIFs optimized for Retro Pixel LED Lite.

## 🖥️ 1. Using the GUI

To launch the graphical interface:
- **Windows**: Double-click `launch_ui.bat`
- **Mac/Linux**: Run `./launch_ui.sh`

### The Ultimate "Zero Config" Workflow:
1. Look at the top right of the application (in the `⚙️ Parameters` panel).
2. Check the **`🚀 Let Me Handle It ✓`** box.
   *(This instantly turns on all 5 AI systems: Auto-Action, Smart Crop, Auto-Colorimetry, Background Subtraction, and DMD Scoring).*
3. Ensure **`Workers`** is set to a high number (e.g. `8` if you have a modern computer) to convert files much faster.
4. Set the **`Cleanup Assistant`** slider to `50%` (or your preferred rejection threshold). The system will automatically discard low-quality results!
5. Click **`Batch Convert Folder`** on the left panel, pick a folder, and grab a coffee.

### Extracting the Best Moments:
Have a long video? Switch to the **`AI Moments`** tab! 
Click **`Generate Best Moments`** to let the AI automatically find, score, and rank the best scenes from your video. You can then preview and convert these highlights directly. Read more in the [AI Moments Guide](docs/AI_MOMENTS.md).

---

## 💻 2. Using the CLI (No GUI)

If you prefer the command line or want to automate the process, the same "zero config" magic is available via the CLI.

To process a folder called `gifs_MyFolder` with 8 parallel workers, fully automated AI framing/colors, and an automatic trash mechanism for anything scoring below 50%:

```bash
python3 -m src.engine.conversion.cli gifs_MyFolder --let-me-handle-it --workers 8 --reject-threshold 50
```

That's it. The script will crunch the videos and delete any `.gif` files that do not meet the 50% visibility threshold.

---

---

## 🔍 3. Download and Convert in One Step

Thanks to the modular architecture, GIF search (via DuckDuckGo, Tenor, or Giphy) is directly integrated into the tool! No need to download your media manually. You can do everything in a single command:

```bash
python3 -m src.engine.conversion.cli --search-keyword "arcade" --search-engine DuckDuckGo --search-limit 5 --let-me-handle-it
```

This command will download 5 GIFs related to "arcade", and then automatically convert them on the fly using all the AI parameters!

---

## 📝 4. Monitoring and Logs (UI & CLI)

The graphical interface now features a **dynamic log panel** (click on "📝 Show / Hide Logs").
There you will find a dropdown menu to adjust the verbosity level on the fly:
- **INFO**: (Default) Displays quality scores, conversion summaries, and warnings.
- **DEBUG**: Displays absolutely all internal processing, including complex FFMPEG outputs (very useful for analyzing a specific issue).

If you are using the CLI, you can get the exact same level of detail with the `--log-level DEBUG` argument (or simply `--verbose`).

---

## 🤖 5. Discovering AI Iconic Moments

Have a 10-minute long gameplay video or movie and want to extract the absolute best 3-second segments for your LED panel without watching the whole thing? 

1. Go to the new **`AI Moments`** tab at the top of the UI.
2. Select your video and choose how many moments you want to extract (e.g., Top 5).
3. Toggle your preferred detection criteria (Action, Epic, Character, Loopable, DMD).
4. Click **`Generate AI Moments`**. The AI Engine will process the video at blazing speed and present you with a grid of the best moments, ranked by score.
5. Click **`Details`** on a moment, and hit **`Open In Converter`**. This will instantly bridge you back to the Conversion tab with the exact timestamps and Auto Action framing perfectly configured for you!
