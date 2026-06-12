# 🎞️ DMD GIF Converter — v6.2.0

Convertit **n'importe quel GIF animé ou fichier vidéo** (MP4, MKV, MOV, AVI, WEBM…) en un format optimisé pour une **dalle LED HUB75 128×32 pixels** pilotée par un ESP32 (compatible [Retro Pixel LED Lite](https://github.com/fjgordillo86/RetroPixelLED-Lite) et la bibliothèque [AnimatedGIF](https://github.com/bitbank2/AnimatedGIF)).

Désormais livré avec une **interface graphique complète multi-plateforme** — aucune ligne de commande nécessaire.

---

## 🌟 Découvrez la puissance du DMD GIF Converter

Marre de recadrer manuellement vos vidéos pour votre matrice LED basse résolution ? Ce moteur automatise l'intégralité du processus grâce à l'IA et la vision par ordinateur.

- **🤖 AI Iconic Moments** : Analyse automatiquement de longues vidéos pour trouver et extraire les scènes les plus épiques, spécialement optimisées pour un affichage 128x32.
- **🎥 Caméra Cinématique par IA** : Utilise YOLOv8 pour suivre les sujets, effectuer des panoramiques dynamiques et recadrer intelligemment le sol et le plafond afin de garder l'action centrée.
- **🎨 Smart Color Boost** : Détecte automatiquement les scènes sombres ou délavées et injecte la quantité parfaite de luminosité, de contraste et de saturation pour que vos GIFs soient éclatants.
- **🧠 Matrice de Score Continue** : Évalue intelligemment chaque scène (Platformer, Talking Closeup, Action) pour sélectionner le profil de caméra parfait sans aucune intervention manuelle.
- **🪄 Magie du Texte** : Ajoutez des superpositions de texte en pixel-art avec des animations intégrées (défilement, clignotement) directement sur vos vidéos.

> **Curieux de savoir ce qui a changé récemment ?** Consultez le [Journal des mises à jour (Changelog)](docs/CHANGELOG_FR.md).

## Table des matières
- [🖥️ Interface graphique](#interface-graphique)
- [✨ Fonctionnalités (Aperçu)](#fonctionnalités-aperçu)
- [🚀 Démarrage rapide](#démarrage-rapide)
- [🎩 Commandes Magiques (CLI)](#commandes-magiques-cli)
- [📚 Documentation Complète](#documentation-complète)
- [📋 Prérequis](#prérequis)
- [📄 Licence & Remerciements](#licence--remerciements)


---

## 🖥️ Interface graphique

### Captures d'écran

![DMD GIF Converter UI Demo](media/UI_PREVIEW.gif)

### Fonctionnalités (Aperçu)

| Fonctionnalité | Détails |
|---|---|
| **Import par fichier ou dossier** | ➕ fichiers individuels, 📂 dossier entier — tous les formats vidéo acceptés |
| **Multi-sélection dans la liste** | Ctrl+clic / Shift+clic pour sélectionner plusieurs fichiers · Suppr les efface tous d'un coup |
| **Listes de Conversion Intelligentes** | Les fichiers passent de **En attente** à **Fichiers Convertis** automatiquement à la fin de la conversion. |
| **DMD Quality Score** | Les fichiers convertis reçoivent un Score de Qualité (0-100%) coloré (de Rouge à Vert Premium) basé sur le contraste, l'occupation et la séparation des formes. |
| **Assistant de Nettoyage** | Mettez instantanément à la corbeille les mauvaises conversions (ex: <=30%, <=50%, ou seuil personnalisé) en un clic. Les fichiers et métadonnées sont physiquement supprimés du disque. |
| **Liste Triable** | Cliquez sur les en-têtes de colonnes `File`, `Score` ou `Category` de la liste des Fichiers Convertis pour trier les éléments par ordre croissant ou décroissant. |
| **Dossier Temporaire Intelligent** | Si aucun dossier de destination n'est défini, les fichiers sont créés dans un sous-dossier `dmd_tmp/` au sein du dossier source, évitant de mélanger les sources avec les conversions. |
| **Batch Auto-Cleanup** | Quand vous traitez un dossier complet, vous pouvez demander au programme de mettre à la corbeille automatiquement les conversions qui n'atteignent pas un certain score. |
| **🔍 Recherche de GIFs** | Cherchez et téléchargez des GIFs depuis DuckDuckGo — mot-clé + quantité (jusqu'à 300), remplit automatiquement la liste |
| **🤖 AI Iconic Moments** | Extrait automatiquement les meilleurs moments des longues vidéos en se basant sur 5 métriques IA et les envoie directement vers le Convertisseur |
| **Triple aperçu en direct** | SOURCE (gauche) + AUTO ACTION intermédiaire (centre) + RENDU DMD (droite) |
| **Diagnostic DMD** | Cliquez sur un fichier converti pour voir son score, son classement, et les raisons expliquant son score. |
| **💡 LED Sim** | Superpose une grille pixel sur la preview DMD — simule l'aspect physique d'une dalle HUB75 · **activé par défaut** |
| **Auto-refresh DMD** | L'aperçu DMD se regénère automatiquement ~2 s après le dernier déplacement de curseur |
| **Trim / extrait** | Définit un début et une fin — mode fichier unique uniquement |
| **⏱ Max Duration** | Limite la durée et place la fenêtre n'importe où dans la source |
| **🎨 Smart Color Boost** | Colorimétrie IA en un clic — ajuste automatiquement contraste, saturation et gamma |
| **🎞️ Config par GIF** | Toggle global — quand activé, chaque fichier stocke sa propre copie indépendante de tous les ~50 paramètres · config sauvegardée instantanément au changement de sélection |
| **Tous les paramètres standards** | Curseurs et menus pour le mode, le scroll, les FPS, la colorimétrie |
| **🔧 Paramètres avancés** | Panneau rétractable — masqué par défaut, valeurs par défaut = sortie identique à v2.0 |
| **Batch dossier** | Convertit un dossier entier en un clic |
| **Convertir toute la liste** | Un clic pour traiter tous les fichiers listés |
| **Journal en temps réel** | Progression visible dans l'interface |
| **Multi-plateforme** | macOS · Windows · Linux |

---

## 🚀 Démarrage rapide

```bash
git clone https://github.com/red77290/dmd_gif_converter.git
cd dmd_gif_converter
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

## 📚 Documentation Complète

Pour garder ce README clair, nos fonctionnalités les plus puissantes disposent de guides dédiés. Découvrez tout le potentiel du moteur :

### [🤖 AI Moments & Studio Timeline](docs/AI_MOMENTS_FR.md)
Fatigué de chercher manuellement le meilleur passage dans un film de 2 heures ? Le moteur **AI Moments** analyse votre vidéo pour trouver les scènes les plus épiques, pleines d'action, et parfaitement lisibles sur votre DMD. Découpez-les à la perfection grâce à la lecture en boucle de la **Studio Timeline**, ou laissez la CLI extraire les 5 meilleurs moments de façon 100% automatique !
👉 **[Lire le Guide AI Moments](docs/AI_MOMENTS_FR.md)**

### [🎥 Caméra Cinématique par IA (Auto-Action)](docs/ADVANCED_FEATURES_FR.md#auto-action-framing)
Lorsqu'on réduit une vidéo 1080p vers une matrice 128x32, les sujets deviennent microscopiques. Le **Auto-Action Framing** utilise l'IA YOLOv8 ONNX pour suivre dynamiquement les sujets, faire des travellings, et rogner intelligemment le sol/plafond pour garder l'action centrée et visible !
👉 **[Lire le Guide des Fonctionnalités Avancées](docs/ADVANCED_FEATURES_FR.md)**

### [🎨 Smart Color Boost & Filtres](docs/ADVANCED_FEATURES_FR.md#smart-color-boost)
Les matrices LED délavent les couleurs sombres et saturent les couleurs claires. Le **Smart Color Boost** utilise une analyse heuristique pour injecter automatiquement la quantité parfaite de luminosité, contraste et saturation dans votre GIF.
👉 **[Lire le Guide des Fonctionnalités Avancées](docs/ADVANCED_FEATURES_FR.md)**

### [💻 Maîtrise de l'Automatisation CLI](docs/CLI_MANUAL_FR.md)
Tout ce que vous pouvez faire dans l'interface est automatisable dans le Terminal. Téléchargez des GIFs via DuckDuckGo, traitez des dossiers complets en parallèle, ajoutez du texte pixel-art, et envoyez automatiquement à la corbeille les mauvaises conversions !
👉 **[Lire le Manuel CLI](docs/CLI_MANUAL_FR.md)**

### [❓ Dépannage & Installation](docs/TROUBLESHOOTING_FR.md)
Un problème avec OpenCV ou FFmpeg ? Besoin d'aide pour l'installation sur un OS spécifique ?
👉 **[Lire le Guide de Dépannage](docs/TROUBLESHOOTING_FR.md)**


---

## 📋 Prérequis

### 1 — Système : Python 3.8+ et FFmpeg

#### 🍎 macOS

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
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
pip install customtkinter Pillow "darkdetect==0.7.1" opencv-python onnxruntime duckduckgo-search requests
```

> `dmd_gif_converter.py` (moteur CLI) **n'a aucune dépendance externe** — bibliothèque standard Python uniquement.  
> `opencv-python` et `onnxruntime` sont optionnels — uniquement nécessaires pour la fonctionnalité **Auto Action** IA. En leur absence, Auto Action est silencieusement ignoré.  
> Le modèle YOLOv8n ONNX (~6 Mo) est téléchargé automatiquement dans `~/.cache/dmd_gif_converter/` au premier lancement.

---

---

## 📄 Licence & Remerciements

MIT — libre d'utilisation, modification et distribution.

---

## 🙏 Remerciements

- **[FFmpeg](https://ffmpeg.org/)** — moteur de traitement vidéo
- **[CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)** — interface graphique moderne multi-plateforme
- **[Pillow](https://python-pillow.org/)** — gestion des images pour l'aperçu et le fallback text overlay
- **[DuckDuckGo](https://duckduckgo.com/)** — API de recherche d'images utilisée par la fonction Recherche GIF (sans clé API)
- **[duckduckgo-search](https://github.com/deedy5/duckduckgo_search)** — bibliothèque Python pour l'API de recherche DuckDuckGo
- **[Requests](https://docs.python-requests.org/)** — bibliothèque HTTP utilisée pour le téléchargement des GIFs
- **[Bitbank2](https://github.com/bitbank2/AnimatedGIF)** — bibliothèque AnimatedGIF pour ESP32
- **[Mrfaptastic](https://github.com/mrfaptastic/ESP32-HUB75-MatrixPanel-DMA)** — moteur DMA HUB75 pour ESP32
- Projet **[Retro Pixel LED Lite](https://github.com/fjgordillo86/RetroPixelLED-Lite)**
- **[Pixel Fonts Pack par ovate](https://github.com/ovate/Pixel-Fonts-Pack)** — polices TTF pixel-perfect incluses dans `media/fonts/`
