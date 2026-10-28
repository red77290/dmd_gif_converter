# 📦 Référence de la Librairie Python Headless & Flux Binaire (`v8.0.8`)

`dmd_gif_converter` est packagé comme une **librairie Python standard (PEP 621)** (`dmd-gif-converter`, `dmd_gif_converter.__version__ == "8.0.8"`) avec une séparation stricte entre son **Moteur Core Headless** (zéro dépendance X11 / Tkinter, prêt pour Docker et les serveurs d'API) et son **Interface Graphique Desktop optionnelle (`[ui]`)**.

---

## 1. Installation

### Installation Serveur / Docker Headless (Sans dépendances GUI)
```bash
# Installer automatiquement la dernière release stable via le tag flottant 'latest' :
pip install "git+https://github.com/red77290/dmd_gif_converter.git@latest"
# Ou figer un tag précis depuis l'onglet GitHub Releases :
pip install "git+https://github.com/red77290/dmd_gif_converter.git@<release-tag>"
# Ou depuis un clone local :
pip install .
```

### Installation Desktop avec Interface Graphique (`CustomTkinter` + Recherche GIF)
```bash
pip install ".[ui]"
```

### Installation Développeur & Suite de Tests
```bash
pip install -e ".[ui,dev]"
```

---

## 2. Démarrage Rapide — `DmdMediaProcessor`

La façade stateless `DmdMediaProcessor` convertit les bandes-annonces vidéo, extraits de gameplay, jaquettes/posters et images de scène en formats optimisés pour matrices LED HUB75 (`.gif`, `.png`, `.rgb565` brut et `.rgb565.stream`) :

```python
from pathlib import Path
from dmd_gif_converter import (
    DmdClipConfig,
    DmdMediaProcessor,
    resolve_panorama_scroll_axis,
    truncate_rgb565_stream,
    __version__,
)

processor = DmdMediaProcessor()

# 1. Convertir une bande-annonce ou un video snap (AI Moments + Auto-Action + Smart Color Boost)
config = DmdClipConfig(
    width=128,
    height=32,
    fps=15,
    max_duration_s=8.0,          # Extrait la meilleure fenêtre de 8 secondes
    skip_intro_pct=0.12,         # Ignore les logos studios au début
    skip_outro_pct=0.15,         # Ignore les crédits de fin
    mode="cinema",               # "pixel_art" | "anime" | "cinema" | "custom"
    use_ai_moments=True,         # Analyse et sélectionne le passage le plus iconique
    use_auto_action=True,        # Recadrage dynamique YOLOv8 / mouvement pour 128x32
    use_smart_color_boost=True,  # Compensation automatique contraste/saturation LED HUB75
)

assets = processor.process_video_trailer(
    input_video=Path("trailer.mp4"),
    output_dir=Path("/tmp/dmd_out"),
    config=config,
    export_gif=True,
    export_rgb565_stream=True,
    stem="blade_runner_1982",
)

# 2. Redimensionner et booster une Jaquette / Affiche (PNG 32x32 + RGB565 brut de 2 Ko)
poster_png, poster_rgb565 = processor.process_poster(
    input_image=Path("poster.jpg"),
    output_dir=Path("/tmp/dmd_out"),
    width=32,
    height=32,
    stem="poster",
)

# 3. Redimensionner un Snapshot / Backdrop pour travelling vertical Ken Burns (128x72 PNG + 18 Ko RGB565)
snap_png, snap_rgb565 = processor.process_pan_backdrop(
    input_image=Path("backdrop.jpg"),
    output_dir=Path("/tmp/dmd_out"),
    width=128,
    height=72,
    stem="snap",
)

# 4. Générer un panorama animé zéro bande noire (.gif + .rgb565.stream) pour dalles YOKO ou TATE
axis = resolve_panorama_scroll_axis(src_w=1920, src_h=1080, target_width=64, target_height=128)
assert axis == "horizontal"  # Les dalles TATE (H > W) défilent toujours de gauche à droite

pan_assets = processor.process_image_panorama(
    input_image=Path("marquee_or_poster.png"),  # Alpha RGBA aplati sur fond noir pur #000000
    output_dir=Path("/tmp/dmd_out"),
    width=64,
    height=128,
    duration_s=5.0,
    fps=20,
    scroll_direction="auto",  # "auto" | "horizontal" | "vertical"
    export_gif=True,
    export_rgb565_stream=True,
    stem="pan_tate",
)
```

### Garanties Panoramiques TATE/YOKO & Cadrage IA (`v8.0.3`–`v8.0.5`)

- **`resolve_panorama_scroll_axis(src_w, src_h, target_width, target_height, scroll_direction="auto") -> str`** :
  - **TATE (`target_height > target_width`)** : Retourne toujours `"horizontal"` (défilement gauche vers droite), centré verticalement en cas de zoom.
  - **YOKO (`target_width > target_height`)** : Retourne toujours `"vertical"` (défilement haut vers bas), centré horizontalement en cas de zoom.
  - **Carrée (`target_width == target_height`)** : Retourne `"horizontal"` si `src_w > src_h` et `"vertical"` sinon.
  - Accepte les forçages explicites (`"horizontal"` / `"left_to_right"` / `"ltr"` / `"x"` et `"vertical"` / `"top_to_bottom"` / `"ttb"` / `"y"`), également disponibles via `DmdClipConfig(scroll_enabled=True, scroll_direction="auto")`.
- **Zoom-to-Cover Uniforme** : Préserve strictement le ratio d'aspect 1:1 (Lanczos) sans aucune bande noire, garantit une amplitude minimale de mouvement en mode panorama, et aplatit la transparence RGBA/palette sur fond noir pur avant l'encodage.
- **Cadrage Auto-Action (`use_auto_action=True`)** : Intègre le suivi de sol bidirectionnel sensible à la posture pour jeux de plateformes 2D (`platformer_floor_ratio=0.90`, ~3 px de sol visible sur dalle 32 px, enveloppe de protection tête/pieds) ainsi que la calibration gros plan yeux-bouche (`closeup_eye_mouth_fractions`).

---

## 3. Spécification du Format Binaire `.rgb565.stream` (`DMDS` v1)

En complément du `.gif` classique, `dmd_gif_converter` génère un flux de frames binaire (`.rgb565.stream`) conçu pour être lu directement par un Raspberry Pi ou un ESP32 et tronqué dynamiquement côté serveur sans aucun ré-encodage.

### En-tête Binaire (16 Octets, Little-Endian `<4sBBHHHHH`)

| Offset Octet | Type | Champ | Description |
| :--- | :--- | :--- | :--- |
| `0..3` | `char[4]` | `magic` | Octets magiques ASCII `"DMDS"` (`0x44 0x4D 0x44 0x53`) |
| `4` | `uint8` | `version` | Version du format (`1`) |
| `5` | `uint8` | `fps` | Cadence en images/seconde (ex: `15`) |
| `6..7` | `uint16_le` | `width` | Largeur en pixels (ex: `128`) |
| `8..9` | `uint16_le` | `height` | Hauteur en pixels (ex: `32`) |
| `10..11` | `uint16_le` | `total_frames` | Nombre total de frames dans le flux |
| `12..13` | `uint16_le` | `frame_delay_ms` | Délai cible par frame en ms (`round(1000 / fps)`) |
| `14..15` | `uint16_le` | `reserved` | Réservé (`0`) |

### Troncature Dynamique Zéro-Réencodage
Lorsqu'un client DMD demande une durée maximale plus courte (`video_max_duration_s = 4.0` sur un extrait pré-calculé de `8.0s`), la fonction `truncate_rgb565_stream(stream_path, max_duration_s=4.0)` découpe instantanément les octets correspondants et met à jour `total_frames` dans l'en-tête en $O(1)$.
