# 🎞️ dmd_gif_converter.py — Convertisseur GIF pour dalles LED DMD 128×32

Convertit n'importe quel GIF animé en un format optimisé pour une **dalle LED HUB75 128×32 pixels** (ESP32 + bibliothèque AnimatedGIF / Retro Pixel LED).

## ✨ Ce que fait le script

| Situation | Comportement |
|---|---|
| GIF **plus haut que 32px** (personnage, scène) | Scroll vertical **ping-pong** (haut→bas→haut) à vitesse constante |
| GIF **plus large que haut** (logo, bannière) | Centrage statique, durée naturelle du GIF respectée |

**Pipeline de traitement :**
1. Fond noir composite (élimine la transparence → plus d'horloge qui transparaît)
2. Mise à l'échelle proportionnelle à 128px de large
3. Colorimétrie boostée pour dalle LED (contraste, saturation, gamma, sharpening)
4. Crop 128×32 avec scroll ping-pong (onde triangulaire)
5. Génération de palette sur les pixels réellement affichés (256 couleurs)
6. Encodage GIF sans transparence ni delta encoding

---

## 📋 Prérequis

### Dépendances système

Le script nécessite **Python 3.8+** et **FFmpeg** (avec `ffprobe`).

---

### 🍎 macOS

**Option A — Homebrew (recommandé)**
```bash
# Installer Homebrew si pas déjà installé
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Installer FFmpeg
brew install ffmpeg
```

**Option B — MacPorts**
```bash
sudo port install ffmpeg
```

**Vérification :**
```bash
python3 --version   # 3.8+
ffmpeg -version
ffprobe -version
```

> Python est préinstallé sur macOS. Si besoin : `brew install python`

---

### 🪟 Windows

**1. Python**

Télécharger et installer depuis [python.org](https://www.python.org/downloads/).  
⚠️ Cocher **"Add Python to PATH"** pendant l'installation.

**2. FFmpeg**

**Option A — winget (Windows 10/11)**
```powershell
winget install Gyan.FFmpeg
```

**Option B — Manuel**
1. Télécharger la version *full build* sur [ffmpeg.org/download.html](https://ffmpeg.org/download.html) → Windows → gyan.dev
2. Extraire l'archive (ex. `C:\ffmpeg\`)
3. Ajouter `C:\ffmpeg\bin` à la variable d'environnement **PATH** :
   - Rechercher "Variables d'environnement" dans le menu Démarrer
   - `Variables système` → `Path` → `Modifier` → `Nouveau` → `C:\ffmpeg\bin`

**Vérification (PowerShell ou cmd) :**
```powershell
python --version
ffmpeg -version
ffprobe -version
```

---

### 🐧 Linux

**Debian / Ubuntu / Mint**
```bash
sudo apt update
sudo apt install python3 python3-pip ffmpeg
```

**Fedora / RHEL / CentOS**
```bash
sudo dnf install python3 ffmpeg
# Si ffmpeg n'est pas dans les dépôts officiels :
sudo dnf install https://download1.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm
sudo dnf install ffmpeg
```

**Arch Linux**
```bash
sudo pacman -S python ffmpeg
```

**Vérification :**
```bash
python3 --version
ffmpeg -version
ffprobe -version
```

---

## 🚀 Installation du script

### Dépendances Python

`moving_gif_V0.py` **n'utilise aucune bibliothèque externe** — uniquement la bibliothèque standard Python (`os`, `subprocess`, `math`, `json`, `logging`, `concurrent.futures`).

> ⚠️ Le fichier `requirements.txt` présent dans ce dépôt concerne d'**autres scripts** du projet (versions plus anciennes utilisant Pillow/numpy/imageio). Il n'est **pas nécessaire** pour `moving_gif_V0.py`.

Aucun `pip install` n'est requis. Vous pouvez toutefois utiliser un environnement virtuel si vous le souhaitez :

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
# Aucun pip install nécessaire — lancer directement :
python3 moving_gif_V0.py
```

**Windows (PowerShell)**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
# Aucun pip install nécessaire — lancer directement :
python moving_gif_V0.py
```

### Récupérer le script

```bash
git clone https://github.com/fjgordillo86/RetroPixelLED-Lite.git
cd RetroPixelLED-Lite
```

Ou simplement télécharger `moving_gif_V0.py` seul depuis la page GitHub.

---

## 📁 Structure des dossiers

Le script détecte automatiquement tous les dossiers commençant par `gifs_` dans le **répertoire courant** et crée un dossier de sortie du même nom sans le préfixe.

```
mon_dossier/
├── moving_gif_V0.py
├── gifs_Arcade/          ← dossier source (préfixe "gifs_")
│   ├── mslug.gif
│   ├── kof98.gif
│   └── ...
├── gifs_Consoles/        ← autre dossier source
│   ├── mario.gif
│   └── ...
│
│   (après exécution)
│
├── Arcade/               ← sortie générée (même nom sans "gifs_")
│   ├── mslug.gif
│   └── kof98.gif
└── Consoles/
    └── mario.gif
```

---

## ▶️ Utilisation

```bash
# Placer le script dans le dossier contenant vos dossiers gifs_*
cd /chemin/vers/mon_dossier

# Lancer la conversion
python3 moving_gif_V0.py
```

**Exemple de log de sortie :**
```
12:34:01 [INFO   ] === Traitement : gifs_Arcade → Arcade (42 fichier(s)) ===
12:34:02 [INFO   ] [PINGPONG] mslug.gif | src 320x240 → 128x96 (crop→128x32) | scroll=64px | fps_src=12.0 → rendu=12.5fps (8cs/frame) | pas=3px | vitesse≈37px/s | cycle=10.67s×1=10.67s
12:34:04 [INFO   ] [OK]     mslug.gif
12:34:02 [INFO   ] [CENTRE]  logo.gif  | src 640x80  → 128x16 (centré) | fps_src=10.0 → rendu=10 | durée=3.00s
12:34:05 [INFO   ] [OK]     logo.gif
```

---

## ⚙️ Configuration

Tous les paramètres sont regroupés **en haut du fichier** et documentés :

### Mode de contenu (`MODE`)

**C'est le seul paramètre à changer selon vos sources.** Il ajuste automatiquement toute la colorimétrie et le dithering :

```python
MODE = "pixel_art"   # "pixel_art" | "anime" | "cinema" | "custom"
```

| Mode | Pour quel contenu | Saturation | Sharpening | Dithering |
|---|---|---|---|---|
| `"pixel_art"` | Sprites rétro, arcade, consoles, **anime** ★ défaut | `2.2` 🔥 max | `1.8` agressif | `none` |
| `"anime"` | Alternative plus douce si `pixel_art` est trop agressif | `1.9` ✨ vif | `1.3` contours nets | `none` |
| `"cinema"` | Films live action, photos réelles | `1.3` 🎞️ naturel | `0.8` doux | `none` |
| `"custom"` | Réglage manuel de chaque constante | libre | libre | libre |

> ✅ **`"pixel_art"` est le mode par défaut et produit un rendu identique à `moving_gif_V0.py`** — mêmes valeurs de contraste, saturation, gamma, sharpening et filtregraphe identique. Si vos GIFs anime étaient parfaits en V0, gardez ce mode.  
> Le preset `"anime"` est uniquement une alternative optionnelle plus douce à essayer si un contenu spécifique semble trop saturé ou trop sharpé.  
> Le dithering Bayer applique son motif dans les **coordonnées de l'écran de sortie** (fixe). Quand le contenu défile, le même pixel apparaît à une position Y différente à chaque frame tandis que la grille Bayer reste immobile → **raies verticales persistantes dans le sens du scroll**.  
> L'error-diffusion (`sierra2_4a`) génère un bruit temporel qui "rampe" frame à frame.  
> À 128×32 avec 256 couleurs, la quantization pure (`"none"`) donne des résultats plus propres que n'importe quel dithering pour du contenu qui défile.  
> Si votre GIF ne défile jamais (logo/bannière, `distance ≤ 0`), vous pouvez utiliser `DITHER = "bayer:bayer_scale=1"` en mode `"custom"` pour lisser les dégradés.

### Paramètres détaillés

```python
# ── Parallélisme ──────────────────────────────────────────────────────────────
MAX_WORKERS = 2        # Nombre de conversions en parallèle
                       # SSD + 8 cœurs + 16Go → 6-8 | HDD ou laptop → 2

# ── Scroll ─────────────────────────────────────────────────────────────────────
VITESSE_SCROLL_PX_S = 32.0   # Vitesse de défilement (px/seconde)

# ── FPS de rendu ────────────────────────────────────────────────────────────────
FPS_MIN_RENDU = 10.0   # FPS minimum (upsampling si source plus lent)
FPS_MAX_RENDU = 25.0   # FPS maximum (plafond ESP32)

# ── Colorimétrie manuelle (MODE = "custom" uniquement) ─────────────────────────
CONTRASTE    = 1.6     # 0.5–2.0  Séparation plans sombre/clair
SATURATION   = 2.2     # 0.0–3.0  Vivacité des couleurs
LUMINOSITE   = -0.03   # -1–+1    Compensation dalle LED
GAMMA        = 0.85    # 0.1–2.0  Correction gamma (< 1 = midtones plus sombres)
SHARPEN_LUMA = 1.8     # Netteté des contours (luminance)
SHARPEN_CHR  = 0.5     # Netteté chroma (léger pour éviter les halos)
DITHER       = "none"  # "none" | "bayer:bayer_scale=1" | "bayer:bayer_scale=2"
```

### Réglage de `MAX_WORKERS` selon votre machine

| Machine | `MAX_WORKERS` |
|---|---|
| MacBook Pro M3 Pro (11c, 36GB) | `8` |
| Desktop SSD, 8+ cœurs, 16GB+ | `6` à `8` |
| Desktop SSD, 4 cœurs, 8GB | `3` à `4` |
| Laptop ou disque dur (HDD) | `2` |

---

## 🔍 Comportement détaillé

### GIF avec personnage (hauteur > 32px après mise à l'échelle)

Le script crée un **scroll ping-pong** : le personnage défile de haut en bas puis revient, en boucle. L'action au centre de l'image est vue deux fois par cycle (aller et retour).

- La vitesse est **constante en px/seconde** (indépendamment du FPS source)
- Le FPS de sortie est snappé sur les valeurs **propres GIF** (10, 12.5, 20, 25fps) pour éviter le judder par quantification centiseconde
- La durée du GIF de sortie couvre au moins un cycle complet **ET** la durée naturelle du GIF source

### GIF logo / bannière (largeur >> hauteur)

Le GIF est **centré verticalement** sur les 32px de la dalle. La durée naturelle du GIF source est respectée (minimum 1 seconde).

### Anti-transparence

Le script élimine toute transparence à deux niveaux :
1. **Composite sur fond noir** dans ffmpeg → les pixels transparents du source deviennent noirs
2. **`-gifflags -offsetting-transdiff`** → désactive le delta encoding du muxeur GIF qui marquerait les pixels inchangés comme transparents (ce qui laisse l'horloge ESP32 "transparaître")

---

## ❓ Dépannage

| Problème | Solution |
|---|---|
| `ffmpeg: command not found` | FFmpeg n'est pas dans le PATH → relire la section installation |
| `[ERREUR] xxx.gif - Lecture metadata impossible` | GIF corrompu ou format non supporté → vérifier le fichier |
| Aucun dossier trouvé | Vérifier que vos dossiers sources commencent bien par `gifs_` et que vous lancez le script depuis le bon répertoire |
| Conversion très lente | Augmenter `MAX_WORKERS` si vous avez un SSD et plusieurs cœurs |
| Couleurs trop saturées | Passer en `MODE = "anime"` ou baisser `SATURATION` en mode `"custom"` |
| GIF semble trop sombre | Augmenter `LUMINOSITE` (ex. `0.05`) ou `GAMMA` (ex. `0.95`) |
| Scroll trop rapide/lent | Ajuster `VITESSE_SCROLL_PX_S` |
| Banding sur dégradés (ciel, ombres) | Passer en `MODE = "anime"` ou `MODE = "cinema"` pour une colorimétrie plus douce — le dithering ne peut pas être utilisé avec du contenu qui défile (crée des raies) |

---

## 📄 Licence

MIT — libre d'utilisation, modification et distribution.

---

## 🙏 Remerciements

- **[FFmpeg](https://ffmpeg.org/)** — moteur de traitement vidéo
- **[Bitbank2](https://github.com/bitbank2/AnimatedGIF)** — bibliothèque AnimatedGIF pour ESP32
- **[Mrfaptastic](https://github.com/mrfaptastic/ESP32-HUB75-MatrixPanel-DMA)** — moteur DMA HUB75 pour ESP32
- Projet **[Retro Pixel LED Lite](https://github.com/fjgordillo86/RetroPixelLED-Lite)**

