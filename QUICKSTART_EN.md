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

---

## 💻 2. Using the CLI (No GUI)

If you prefer the command line or want to automate the process, the same "zero config" magic is available via the CLI.

To process a folder called `gifs_MyFolder` with 8 parallel workers, fully automated AI framing/colors, and an automatic trash mechanism for anything scoring below 50%:

```bash
python3 -m src.converter.cli gifs_MyFolder --let-me-handle-it --workers 8 --reject-threshold 50
```

That's it. The script will crunch the videos and delete any `.gif` files that do not meet the 50% visibility threshold.
