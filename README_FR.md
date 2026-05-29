# 🎞️ DMD GIF Converter — v2.0

Convertit **n'importe quel GIF animé ou fichier vidéo** (MP4, MKV, MOV, AVI, WEBM…) en un format optimisé pour une **dalle LED HUB75 128×32 pixels** pilotée par un ESP32 (compatible [Retro Pixel LED Lite](https://github.com/fjgordillo86/RetroPixelLED-Lite) et la bibliothèque [AnimatedGIF](https://github.com/bitbank2/AnimatedGIF)).

Désormais livré avec une **interface graphique complète multi-plateforme** — aucune ligne de commande nécessaire.

## ✨ Ce que fait le script

| Situation | Comportement |
|---|---|
| GIF / vidéo **plus haut que 32 px** (personnage, scène) | Scroll **haut → bas → centre → pause** puis boucle |
| GIF / vidéo **plus large que haut** (logo, bannière) | Centrage statique, durée naturelle respectée |

**Pipeline de traitement :**
1. Fond noir composite (élimine la transparence → plus d'horloge qui transparaît)
2. Mise à l'échelle proportionnelle à 128 px de large, `bottom_crop_pct` % du bas ignorés
3. Colorimétrie boostée pour dalle LED (contraste, saturation, gamma, sharpening)
4. Crop 128×32 avec scroll intelligent : haut → bas → centre → pause
5. Génération de palette sur les pixels réellement affichés (256 couleurs)
6. Encodage GIF sans transparence ni delta encoding

---

## 🖥️ Interface graphique — nouveauté v2.0

### Fonctionnalités

| Fonctionnalité | Détails |
|---|---|
| **Import par fichier ou dossier** | ➕ fichiers individuels, 📂 dossier entier — tous les formats vidéo acceptés |
| **Prévisualisation source animée** | Lit le fichier source directement dans l'application |
| **Aperçu DMD** | Lance le pipeline complet et affiche le rendu 128×32 agrandi ×5 |
| **Trim / extrait** | Définit un début et une fin dans l'aperçu — mode fichier unique uniquement |
| **Tous les paramètres accessibles** | Curseurs et listes déroulantes pour chaque réglage |
| **Batch dossier** | Convertit un dossier entier en un clic |
| **Convertir toute la liste** | Un clic pour traiter tous les fichiers listés |
| **Journal en temps réel** | Progression visible dans l'interface |
| **Multi-plateforme** | macOS · Windows · Linux |

### Lancer l'interface

```bash
python3 dmd_gif_converter_ui.py      # macOS / Linux
python  dmd_gif_converter_ui.py      # Windows
```

---

## 📋 Prérequis

### 1 — Système : Python 3.8+ et FFmpeg

#### 🍎 macOS

```bash
# Installer Homebrew si pas déjà installé
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Installer FFmpeg
brew install ffmpeg
```

> Python est préinstallé sur macOS. Si besoin : `brew install python`

#### 🪟 Windows

```powershell
winget install Gyan.FFmpeg
```

Ou télécharger manuellement depuis [ffmpeg.org](https://ffmpeg.org/download.html) et ajouter `C:\ffmpeg\bin` au **PATH** :
- Rechercher « Variables d'environnement » dans le menu Démarrer
- `Variables système` → `Path` → `Modifier` → `Nouveau` → `C:\ffmpeg\bin`

#### 🐧 Linux

**Debian / Ubuntu / Mint**
```bash
sudo apt update && sudo apt install python3 ffmpeg
```

**Fedora**
```bash
sudo dnf install https://download1.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm
sudo dnf install python3 ffmpeg
```

**Arch Linux**
```bash
sudo pacman -S python ffmpeg
```

**Vérification :**
```bash
python3 --version   # 3.8+
ffmpeg -version
```

---

### 2 — Dépendances Python (interface graphique uniquement)

```bash
pip install -r requirements_ui.txt
```

Ou directement :
```bash
pip install customtkinter Pillow
```

> `dmd_gif_converter.py` (moteur CLI) **n'a aucune dépendance externe** — bibliothèque standard Python uniquement.

---

## 🚀 Démarrage rapide

```bash
git clone https://github.com/fjgordillo86/RetroPixelLED-Lite.git
cd RetroPixelLED-Lite/dmd_gif_converter
```

Lancez ensuite le script correspondant à votre OS — **tout est configuré automatiquement à la première exécution** (création du venv, installation des dépendances) :

| OS | Commande |
|---|---|
| 🍎 macOS / 🐧 Linux | `./launch_ui.sh` |
| 🪟 Windows (double-clic) | `launch_ui.bat` |
| 🪟 Windows (PowerShell) | `.\launch_ui.ps1` |

> **Pourquoi un script de lancement ?**  
> Sur macOS, le Python système (CommandLineTools) embarque Tcl/Tk 8.5 qui **plante sur macOS 15+ / 26 (Tahoe)**. Le script utilise automatiquement le Python 3.13 de Homebrew (Tk 9.0) dans un venv isolé.  
> Sur Linux, assurez-vous que `python3-tk` est installé :  
> `sudo apt install python3-tk` · `sudo dnf install python3-tkinter` · `sudo pacman -S tk`

---

## ▶️ Utilisation en ligne de commande (sans interface)

Placez le script dans le dossier contenant vos dossiers `gifs_*` :

```
mon_dossier/
├── dmd_gif_converter.py
├── gifs_Arcade/
│   ├── mslug.gif
│   └── kof98.mp4        ← MP4, MKV, MOV, AVI, WEBM… aussi acceptés
└── gifs_Consoles/
    └── mario.gif
```

```bash
cd mon_dossier
python3 dmd_gif_converter.py    # macOS / Linux
python  dmd_gif_converter.py    # Windows
```

Les dossiers de sortie sont créés automatiquement (`Arcade/`, `Consoles/`…).

**Exemple de log :**
```
12:34:01 [INFO   ] === Processing: gifs_Arcade → Arcade (42 file(s)) | mode=pixel_art ===
12:34:02 [INFO   ] [SCROLL ] mslug.gif | src 320x240 → 128x96 | scroll=50px | fps=12.5 | total=4.54s
12:34:04 [INFO   ] [OK    ] mslug.gif
```

---

## ⚙️ Paramètres

Tous les paramètres sont accessibles via **curseurs et listes déroulantes dans l'interface**, et sous forme de constantes en haut du script pour l'usage CLI.

### Mode de contenu

| Mode | Pour quel contenu | Saturation | Sharpening |
|---|---|---|---|
| `pixel_art` | Sprites rétro, arcade, consoles ★ défaut | `2.2` 🔥 max | `1.8` agressif |
| `anime` | Anime / cartoon (plus doux) | `1.9` ✨ vif | `1.3` net |
| `cinema` | Films live, vidéos réelles | `1.3` 🎞️ naturel | `0.8` doux |
| `custom` | Réglage manuel de chaque valeur | libre | libre |

### Référence complète des paramètres

| Paramètre | Défaut | Description |
|---|---|---|
| `max_workers` | `2` | Processus ffmpeg en parallèle |
| `scroll_speed` | `24.0` | Vitesse de défilement (px/s) |
| `bottom_crop_pct` | `0.15` | Part du bas ignorée (pieds, sol) |
| `pause_center_s` | `1.5` | Pause au centre avant de recommencer (s) |
| `fps_min` | `10.0` | FPS minimum (upsampling si source plus lent) |
| `fps_max` | `25.0` | FPS maximum (plafond ESP32) |
| `contrast` | `1.6` | Mode custom — 0.5 à 2.5 |
| `saturation` | `2.2` | Mode custom — 0.0 à 4.0 |
| `brightness` | `-0.03` | Mode custom — compensation dalle LED |
| `gamma` | `0.85` | Mode custom — correction gamma |
| `sharpen_lum` | `1.8` | Netteté luminance |
| `sharpen_chr` | `0.5` | Netteté chroma |
| `dither` | `none` | `none` recommandé pour contenu défilant |

### Réglage de `max_workers`

| Machine | Recommandé |
|---|---|
| MacBook Pro M3 Pro (11 cœurs, 36 Go) | `8` |
| Desktop SSD, 8+ cœurs, 16 Go+ | `6`–`8` |
| Desktop SSD, 4 cœurs, 8 Go | `3`–`4` |
| Laptop ou disque dur (HDD) | `2` |

---

## 🔍 Comportement détaillé

### Contenu haut — scroll intelligent

```
haut (y=0) ──scroll bas──▶ bas ──scroll haut──▶ centre ──pause──▶ (retour en haut)
```

- **Crop du bas** : les 15 % inférieurs (pieds, sol, fond vide) sont ignorés → réduit la distance de scroll
- **Pause au centre** : 1,5 s de pause avant de recommencer le cycle
- Vitesse **constante en px/seconde** indépendamment du FPS source
- FPS de sortie snappé sur les valeurs propres GIF (10, 12,5, 20, 25 fps) — zéro judder

### Contenu large — centrage statique

L'image est **centrée verticalement** sur les 32 px de la dalle. Durée source respectée (minimum 1 s).

### Élimination de la transparence

| Couche | Mécanisme |
|---|---|
| `color=black` + `overlay` | Fond noir composite — alpha source → noir |
| `-gifflags -offsetting-transdiff` | Désactive le delta encoding GIF |

---

## ❓ Dépannage

| Problème | Solution |
|---|---|
| `ffmpeg: command not found` | FFmpeg non installé ou pas dans le PATH |
| Aperçu vide | FFmpeg doit être installé et accessible dans le PATH |
| `[ERROR] xxx — metadata unreadable` | Fichier corrompu ou format non supporté |
| Conversion très lente | Augmenter `max_workers` (SSD + multi-cœurs recommandé) |
| Couleurs trop saturées | Passer en mode `anime` ou baisser `saturation` en mode `custom` |
| GIF trop sombre | Augmenter `brightness` (ex. `0.05`) ou `gamma` (ex. `0.95`) |
| Scroll trop rapide / lent | Ajuster `scroll_speed` (défaut : `24.0`) |
| Banding sur les dégradés | Passer en mode `anime` ou `cinema` — le dithering crée des raies avec du contenu défilant |

---

## 📄 Licence

MIT — libre d'utilisation, modification et distribution.

---

## 🙏 Remerciements

- **[FFmpeg](https://ffmpeg.org/)** — moteur de traitement vidéo
- **[CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)** — interface graphique moderne multi-plateforme
- **[Pillow](https://python-pillow.org/)** — gestion des images pour l'aperçu
- **[Bitbank2](https://github.com/bitbank2/AnimatedGIF)** — bibliothèque AnimatedGIF pour ESP32
- **[Mrfaptastic](https://github.com/mrfaptastic/ESP32-HUB75-MatrixPanel-DMA)** — moteur DMA HUB75 pour ESP32
- Projet **[Retro Pixel LED Lite](https://github.com/fjgordillo86/RetroPixelLED-Lite)**

