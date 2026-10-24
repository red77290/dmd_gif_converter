# 📦 Référence de la Librairie Python Headless & Flux Binaire

`dmd_gif_converter` est packagé comme une **librairie Python standard (PEP 621)** (`dmd-gif-converter`) avec une séparation stricte entre son **Moteur Core Headless** (zéro dépendance X11 / Tkinter, prêt pour Docker et les serveurs d'API) et son **Interface Graphique Desktop optionnelle (`[ui]`)**.

---

## 1. Installation

### Installation Serveur / Docker Headless (Sans dépendances GUI)
```bash
# Installer un tag de release depuis l'onglet GitHub Releases (recommandé en production) :
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
```

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
