# 🎞️ DMD GIF Converter — v3.0.0

Convertit **n'importe quel GIF animé ou fichier vidéo** (MP4, MKV, MOV, AVI, WEBM…) en un format optimisé pour une **dalle LED HUB75 128×32 pixels** pilotée par un ESP32 (compatible [Retro Pixel LED Lite](https://github.com/fjgordillo86/RetroPixelLED-Lite) et la bibliothèque [AnimatedGIF](https://github.com/bitbank2/AnimatedGIF)).

Désormais livré avec une **interface graphique complète multi-plateforme** — aucune ligne de commande nécessaire.

---

## 🔍 Recherche de GIFs — téléchargez des GIFs directement depuis l'UI  *(nouveau en v3.0.0)*

> **En bref — tapez un mot-clé, choisissez une quantité, appuyez sur ⬇ DL, et les GIFs apparaissent dans la liste prêts à convertir.**  
> Disponible dans le panneau **📁 Fichiers source** à gauche, entre les boutons de fichiers et la liste.

Le panneau de recherche GIF permet de rechercher des GIFs animés sur DuckDuckGo et de les télécharger directement dans un dossier temporaire géré. Chaque GIF téléchargé est immédiatement ajouté à la liste — sans navigation manuelle dans les dossiers.

```
Mot-clé + quantité  ──[recherche images DuckDuckGo]──▶  dossier temp  ──▶  liste  ──▶  Convertir
```

### Fonctionnalités

| Fonctionnalité | Détails |
|---|---|
| **Recherche par mot-clé** | N'importe quel texte — supporte la touche `Entrée` pour lancer la recherche |
| **Quantité configurable** | 1 à 50 GIFs par recherche (défaut : 10) |
| **Progression en temps réel** | La barre de progression principale se met à jour à chaque fichier téléchargé |
| **Alimentation fichier par fichier** | Chaque GIF téléchargé apparaît dans la liste immédiatement |
| **Bouton Annuler** | Apparaît pendant le téléchargement — s'arrête après le fichier en cours |
| **Gestion des erreurs** | Timeouts, URLs invalides et mauvais types MIME sont ignorés avec des entrées dans le log |
| **Gestion du dossier temp** | Tous les GIFs téléchargés vont dans un dossier temporaire géré, nettoyé à la fermeture |
| **Repli gracieux** | Si `duckduckgo-search` ou `requests` sont absents, le panneau affiche un avertissement et le bouton est désactivé — pas de crash |

### Comment l'utiliser

1. Dans le panneau **📁 Fichiers source** → trouvez la section **🔍 GIF Search**
2. Tapez un mot-clé (ex. `pac-man`, `pixel art fire`, `retro arcade`)
3. Définissez la quantité (défaut : 10, max : 50)
4. Appuyez sur **⬇ DL** ou Entrée
5. Les GIFs se téléchargent un par un et apparaissent dans la liste
6. Sélectionnez-en un, ajustez les paramètres, et convertissez !

### Prérequis

```bash
pip install duckduckgo-search requests
# déjà inclus dans requirements_ui.txt — installé automatiquement par ./launch_ui.sh
```

---

## 🤖 Auto Action Framing — caméra cinématique par IA

> **En bref — activez-le, laissez tourner, admirez le résultat.**  
> Accessible dans **🔧 Advanced Settings → 🎯 Auto Action Framing** · désactivé par défaut.

C'est la fonctionnalité la plus puissante du convertisseur. Au lieu d'un crop statique ou d'un simple scroll vertical, le moteur **Auto Action** analyse chaque image de votre vidéo source avec de la **vision par ordinateur (OpenCV)** et génère automatiquement des **mouvements de caméra de qualité cinématique** avant de transmettre le résultat à ffmpeg :

```
Vidéo source  ──[analyse IA]──▶  crop 4:1 cinématique  ──[ffmpeg]──▶  GIF DMD 128×32
                     ↑
         Détection de personnes (HOG/SVM)
         Détection de mouvement (soustraction de fond + flux optique)
         Caméra virtuelle à lissage exponentiel
         Plan large d'introduction panoramique
```

### Ce que ça fait automatiquement

| Phase | Ce qui se passe |
|---|---|
| **Panoramique intro** | Commence par un plan large (1,5 s par défaut) pour que le spectateur comprenne la scène |
| **Détection IA** | Détecte les personnes (HOG/SVM) et/ou les mouvements image par image |
| **Cadrage cinématique** | Calcule la fenêtre de crop 4:1 idéale centrée sur l'action, avec un padding configurable |
| **Caméra lissée** | Applique un lissage exponentiel pour simuler un vrai caméraman — pas de saccades |
| **Extension queue** | Si la vidéo est trop courte pour que la caméra finisse son mouvement, la dernière image est prolongée jusqu'à convergence |

### Pourquoi c'est désactivé par défaut

Auto Action effectue une **analyse d'image intensive en CPU** sur chaque frame (détection HOG de personnes, soustraction de fond, flux optique). C'est nettement plus lourd qu'une simple passe ffmpeg :

- **Charge CPU :** 2 à 5× plus élevée que la conversion standard
- **Temps de traitement par fichier :** approximativement doublé
- **Mémoire :** chaque worker charge la vidéo entière en frames brutes

Pour les bibliothèques de sprites rétro ou de GIFs pixel art, le pipeline scroll standard est déjà optimal.  
**Pour de la vidéo live, du sport, du cinéma, ou toute vidéo avec une personne ou un sujet en mouvement → activez Auto Action et obtenez un résultat professionnel entièrement automatisé.**

### Comment l'activer

1. Lancez l'interface avec `./launch_ui.sh`
2. Sélectionnez un fichier vidéo
3. Descendez dans le panneau **⚙️ Parameters** → cliquez sur **🔧 Advanced Settings ▼**
4. En haut du panneau : **🎯 Auto Action Framing**
5. Cochez **"Enable cinematic auto-framing before ffmpeg"**
6. Le canvas de prévisualisation **AUTO ACTION** (milieu) se génère immédiatement

### Paramètres

| Paramètre | Curseur UI | Défaut | Description |
|---|---|---|---|
| `auto_action_enabled` | Case à cocher | `OFF` | Interrupteur principal — active le cadrage IA |
| `action_detector` | Mode de détection | `person` | `person` · `motion` · `hybrid` · `center` |
| `action_intro` | Intro panoramique | `1,5 s` | Durée du plan large ajouté en préfixe (première image gelée, source rejouée intégralement) |
| `action_strength` | Action strength | `0,65` | `0` = cadrage large · `1` = zoom serré sur le sujet |
| `action_smoothness` | Camera smooth | `0,85` | `0` = instantané · `0,98` = caméra très lente |
| `action_zoom_max` | Zoom max | `1,8×` | Zoom dynamique maximum que la caméra IA peut appliquer |
| `action_padding` | ROI padding | `0,20` | Espace de respiration autour du sujet détecté |

### Modes de détection

| Mode | Idéal pour |
|---|---|
| `person` ★ défaut | Vidéos avec des personnes — HOG/SVM, repli sur le mouvement si aucune silhouette détectée |
| `motion` | Sport, véhicules, action rapide sans silhouette humaine claire |
| `hybrid` | Fusionne les boîtes person + motion — couverture la plus large |
| `center` | Pas de détection — caméra centrée (panoramique intro uniquement) |

### Dépendance requise

Auto Action nécessite **OpenCV** (installé automatiquement par `launch_ui.sh`) :

```bash
pip install opencv-python   # ou : pip install -r requirements_ui.txt
```

Si OpenCV n'est pas installé, la fonctionnalité est silencieusement ignorée et le pipeline standard s'exécute à la place — **pas de crash, pas de perte de données**.

---

## 🎨 Smart Color Boost — colorimétrie heuristique par IA

> **En bref — une case à cocher, des couleurs parfaites sur toutes les sources.**  
> Dans le panneau **⚙️ Parameters** → section **🎨 Content mode → Smart Color Boost** · désactivé par défaut.

Les dalles LED matricielles ont des caractéristiques d'affichage très différentes des écrans : lumière diffusée, profondeur de bits limitée, luminosité perçue élevée. Un contenu parfait sur écran peut apparaître délavé, trop sombre ou sur-saturé sur un panel HUB75 128×32.

**Smart Color Boost** résout ça automatiquement. Il analyse une keyframe représentative de chaque vidéo source et calcule le profil colorimétrique optimal pour ce contenu spécifique, sans aucune intervention manuelle.

```
Vidéo source  ──[keyframe @ 50%]──▶  analyse heuristique  ──▶  paramètres optimaux  ──▶  ffmpeg
                                              ↑
                                  Luminance (niveau de gris moyen)
                                  Dynamique (écart-type)
                                  Saturation couleur (canal S HSV)
```

### Ce qu'il analyse et corrige

| Mesure | Ce qui est détecté | Correction appliquée |
|---|---|---|
| **Luminance moyenne** | Sous-exposé (sombre) · sur-exposé (clair) | Boost/réduction du **Gamma** |
| **Écart-type** | Image terne / délavée (faible dynamique) | Multiplicateur de **Contraste** |
| **Saturation HSV** | Désaturé · quasi-niveaux de gris | Boost de **Saturation** |
| Décalage résiduel | Fine correction de luminosité | **Brightness** fine-tune |

### Exemples de compensation

| Type de source | lum | std | → contraste | saturation | gamma |
|---|---|---|---|---|---|
| Scène nocturne / donjon | 31 | 22 | **2.50** ↑↑ | 2.45 | **1.40** ↑↑ |
| Brumeux / délavé | 55 | 18 | **2.50** ↑↑ | **3.00** ↑↑ | **1.40** ↑↑ |
| Sprite arcade normal | 116 | 62 | 1.20 | 1.90 | 0.93 |
| Surexposé / trop lumineux | 190 | 20 | **2.50** ↑↑ | **3.46** ↑↑ | **0.55** ↓↓ |
| Déjà contrasté et vivid | 120 | 75 | 1.20 | 1.50 | 0.89 |
| Quasi N&B | 129 | 54 | 1.20 | **3.00** ↑↑ | 0.81 |

### Pourquoi c'est désactivé par défaut

Smart Color Boost **remplace les curseurs de colorimétrie manuelle** (contraste, saturation, gamma, luminosité) et les grise dans l'UI pour éviter les conflits. Les utilisateurs qui préfèrent régler leurs propres presets, ou qui utilisent les modes `pixel_art` / `anime` / `cinema` déjà calibrés à la main, doivent le laisser désactivé.

**Activez-le pour :**
- Des bibliothèques hétérogènes avec des expositions très différentes d'un fichier à l'autre
- Des vidéos live ou cinéma dont l'exposition source est inconnue
- Tout contenu qui ne rend pas bien avec les presets standards

### Comment l'activer

1. Lancez l'interface avec `./launch_ui.sh`
2. Dans le panneau **⚙️ Parameters** → section **🎨 Content mode**
3. Cochez **"🎨 Smart Color Boost — IA auto-colorimetry"**
4. Les curseurs de colorimétrie manuelle se grisent automatiquement
5. Lancez la conversion — le log affiche les valeurs calculées : `[COLOR ] lum=XX std=XX → contrast=X.XX …`

### Prérequis

Smart Color Boost utilise le même **OpenCV + NumPy** qu'Auto Action — aucune dépendance supplémentaire. L'analyse est rapide (<0,5 s par fichier) et négligeable par rapport au temps de conversion ffmpeg.

En l'absence d'OpenCV, le fallback silencieux s'applique — **pas de crash, pas de perte de données**.

---

## ✨ Ce que fait le script

| Situation | Comportement |
|---|---|
| GIF / vidéo **plus haut que 32 px** (personnage, scène) | Scroll N cycles (bas→haut), puis s'arrête à une position configurable |
| GIF / vidéo **plus large que haut** (logo, bannière) | Centrage statique, durée naturelle respectée |

**Pipeline de traitement :**
1. *(optionnel)* **🤖 Auto Action** — crop cinématique IA à résolution native (pré-ffmpeg)
2. *(optionnel)* **🎨 Smart Color Boost** — analyse heuristique de keyframe, injecte la colorimétrie optimale
3. Fond noir composite (élimine la transparence → plus d'horloge qui transparaît)
4. Mise à l'échelle proportionnelle à 128 px de large, `bottom_crop_pct` % du bas ignorés
5. Colorimétrie boostée pour dalle LED (contraste, saturation, gamma, sharpening)
6. Crop 128×32 avec scroll intelligent (nombre de cycles + position d'arrêt)
7. Génération de palette sur les pixels réellement affichés (256 couleurs)
8. Encodage GIF sans transparence ni delta encoding

---

## 🖥️ Interface graphique

### Captures d'écran

![DMD GIF Converter UI](media/UI_PREVIEW.png)

### Fonctionnalités

| Fonctionnalité | Détails |
|---|---|
| **Import par fichier ou dossier** | ➕ fichiers individuels, 📂 dossier entier — tous les formats vidéo acceptés |
| **🔍 Recherche GIF** | Recherche & téléchargement de GIFs depuis DuckDuckGo — mot-clé + quantité, alimente la liste automatiquement |
| **Triple aperçu en direct** | SOURCE (gauche) + intermédiaire AUTO ACTION (milieu) + SORTIE DMD (droite) |
| **Auto-refresh DMD** | L'aperçu DMD se regénère automatiquement ~2 s après le dernier déplacement de curseur |
| **Trim / extrait** | Définit un début et une fin — mode fichier unique uniquement |
| **⏱ Max Duration** | Limite la durée et place la fenêtre n'importe où dans la source |
| **🎨 Smart Color Boost** | Colorimétrie IA en un clic — ajuste automatiquement contraste, saturation et gamma |
| **Tous les paramètres standards** | Curseurs et menus pour le mode, le scroll, les FPS, la colorimétrie |
| **🔧 Paramètres avancés** | Panneau rétractable — masqué par défaut, valeurs par défaut = sortie identique à v2.0 |
| **Batch dossier** | Convertit un dossier entier en un clic |
| **Convertir toute la liste** | Un clic pour traiter tous les fichiers listés |
| **Journal en temps réel** | Progression visible dans l'interface |
| **Multi-plateforme** | macOS · Windows · Linux |

### 🔧 Panneau Paramètres Avancés (nouveau en v2.1)

Cliquer sur le bouton **🔧 Advanced Settings ▼** en bas du panneau Paramètres.  
Toutes les valeurs par défaut = « aucun effet » — la sortie standard est identique à v2.0.

#### 🎨 Smart Color Boost — colorimétrie heuristique IA

> Voir la section dédiée en tête de ce README pour le guide complet.

- Accessible directement dans le bloc **🎨 Content mode** du panneau Paramètres (pas dans Advanced)
- Analyse une **keyframe à 50 %** de la source et calcule automatiquement contraste / saturation / gamma / luminosité
- **Grise les curseurs de colorimétrie manuelle** quand activé pour éviter les conflits
- Coût négligeable (<0,5 s par fichier) — utilise OpenCV + NumPy
- Fallback silencieux sur le preset standard si OpenCV n'est pas installé

#### 🎯 Auto Action Framing — caméra IA

> Voir la section dédiée en tête de ce README pour le guide complet.

- **Désactivé par défaut** — à activer pour tout contenu vidéo live avec de l'action
- Effectue une **passe de vision par ordinateur** (OpenCV) sur chaque image avant ffmpeg
- Génère un clip intermédiaire à **résolution native 4:1** qui suit l'action
- Le canvas de prévisualisation **AUTO ACTION** (panneau central) montre le résultat en temps réel
- Repli automatique sur la conversion standard si OpenCV n'est pas installé

| Curseur | Défaut | Effet |
|---|---|---|
| Case à cocher | `OFF` | Interrupteur principal |
| Mode de détection | `person` | `person` / `motion` / `hybrid` / `center` |
| **Intro panoramique** | `1,5 s` | Plan large en préfixe (première image gelée, source rejouée intégralement) |
| Action strength | `0,65` | Serrage du cadre autour du sujet |
| Camera smooth | `0,85` | Lissage exponentiel — plus élevé = caméra plus lente |
| Zoom max | `1,8×` | Zoom maximum autorisé |
| ROI padding | `0,20` | Espace de respiration autour du sujet détecté |

#### ⏱ Max Duration

Limite la durée du clip de sortie (défaut **2:00 min**).  
Déplacer le curseur **Start** du trim pour placer la fenêtre de 2 minutes où vous le souhaitez dans la vidéo.  
Mettre à `0` ou décocher pour désactiver.

#### 📍 Positionnement

| Contrôle | Description | Défaut |
|---|---|---|
| **Auto vertical scroll** ✅ | Coché = comportement de défilement standard (inchangé) | ✅ coché |
| **Zoom** | Multiplicateur de mise à l'échelle avant crop (1.0 = ajusté à 128 px) | `1.0×` |
| **X offset** | Décalage horizontal du crop en pixels (mode manuel uniquement) | `0 px` |
| **Y offset** | Décalage vertical du crop en pixels (mode manuel uniquement) | `0 px` |

> Décocher **Auto vertical scroll** pour activer le mode manuel. Augmenter d'abord le Zoom,
> puis régler X/Y pour choisir exactement quelle fenêtre 128×32 extraire.
> L'aperçu DMD se met à jour automatiquement ~2 s après l'arrêt du glissement.

#### 🖼️ Multi-Dalle / Tiling

Configurer la résolution de sortie pour les configurations multi-dalles.

| Contrôle | Défaut | Description |
|---|---|---|
| **Dimensions Preset** | `128×32 (1×1)` | Presets rapides : `128×32`, `256×32`, `128×64` ou Custom |
| **Custom Width** | `128` | Largeur en pixels (éditable uniquement avec preset = Custom) |
| **Custom Height** | `32` | Hauteur en pixels (éditable uniquement avec preset = Custom) |

> Le moteur Auto Action utilise toujours le bon ratio cible.

#### 💬 Text Overlay — texte incrusté

Graver un texte directement dans le GIF de sortie. Le texte est **toujours appliqué sur le GIF 128×32 final** (après toute mise à l'échelle / recadrage), ce qui maximise la lisibilité.

> **Deux moteurs de rendu** — utilisés de façon transparente :
> - **ffmpeg `drawtext`** quand ffmpeg est compilé avec `libfreetype` (Linux typique)
> - **Pillow post-traitement** fallback automatique sans libfreetype (ffmpeg Homebrew macOS)  
>   Les deux produisent des résultats identiques ; le log indique le moteur utilisé.

| Contrôle | Défaut | Description |
|---|---|---|
| **Enable Text Overlay** | ☐ off | Interrupteur principal |
| **Text Content** | `""` | Texte à afficher sur chaque frame |
| **Font Size** | `8 px` | Taille en pixels (4–32 px) |
| **Text Color** | `white` | `white` / `yellow` / `red` / `green` / `blue` |
| **Text Position** | `bottom_center` | 9 positions (top/middle/bottom × left/center/right) |
| **Font** | `HelvetiPixel.ttf` | Police pixel depuis `media/fonts/` |
| **Text Style** | `outline` | Style de rendu — voir tableau ci-dessous |
| **Background box** | ☐ off | Boîte sombre semi-transparente derrière le texte |
| **Box opacity** | `60 %` | 10–100 % (visible uniquement quand Background box est actif) |

**Styles de texte** (optimisés pour la lisibilité sur 128×32) :

| Style | Effet | Meilleure utilisation |
|---|---|---|
| `outline` ★ défaut | Contour noir 1 px autour du glyphe | Lisibilité maximale sur n'importe quel fond |
| `bold` | Contour couleur 1 px → glyphe plus épais | Texte clair sur contenu sombre |
| `shadow` | Ombre portée décalée 1 px | Effet de profondeur |
| `none` | Texte brut, sans effet | Contenu clair uniquement |

**Polices disponibles** (toutes optimisées pour les dalles DMD 128×32) :

| Fichier | Style |
|---|---|
| `HelvetiPixel.ttf` | Sans-serif pixel lisible ★ défaut |
| `PixelMordred.ttf` | Gothique pixel gras |
| `BitCasual.ttf` | Rétro décontracté |
| `CursivePixel.ttf` | Cursive pixel |
| `justabit.ttf` | Style 1-bit minimaliste |
| `KarenBook.ttf` | Pixel lisible book |
| `OldWizard.ttf` | Fantaisie médiévale |
| `OrdinaryBasis.ttf` | Pixel neutre |
| `Quintet.ttf` | Pixel compact |
| `TimesNewPixel.ttf` | Serif pixel |

> Les polices doivent être dans `media/fonts/`. Si la police choisie est introuvable, l'overlay est désactivé avec un avertissement dans le log.

**Flags CLI :**

```bash
./dmd_gif_converter.py --text-overlay --text-content "JOUEUR 1" \
  --text-font-size 10 --text-color yellow --text-position top_center \
  --text-font-file HelvetiPixel.ttf --text-style outline \
  --text-bg --text-bg-opacity 60
```

#### ✨ Effets visuels

| Effet | Filtre | Défaut |
|---|---|---|
| **Hue shift** (décalage de teinte) | ffmpeg `hue=h=…` | `0°` (inactif) |
| **Noise reduction** (réduction de bruit) | ffmpeg `hqdn3d` | `0` (inactif) |
| **Film grain** (grain de film) | ffmpeg `noise=alls=…` | `0` (inactif) |
| **Vignette** | ffmpeg `vignette` | ☐ décoché |

Tous les effets sont désactivés par défaut. Une valeur non nulle ajoute des passes de filtres ffmpeg *après* la chaîne de colorimétrie standard.

### Lancer l'interface

```bash
./launch_ui.sh          # macOS / Linux  (recommandé — gère le venv automatiquement)
python3 dmd_gif_converter_ui.py   # si le venv est déjà activé
```

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
pip install customtkinter Pillow "darkdetect==0.7.1" opencv-python duckduckgo-search requests
```

> `dmd_gif_converter.py` (moteur CLI) **n'a aucune dépendance externe** — bibliothèque standard Python uniquement.  
> `opencv-python` est optionnel — uniquement nécessaire pour la fonctionnalité **Auto Action** IA. En son absence, Auto Action est silencieusement ignoré.

---

## 🚀 Démarrage rapide

```bash
git clone hhttps://github.com/red77290/dmd_gif_converter.git
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
# Par défaut : mode pixel_art, détecte automatiquement les dossiers gifs_*
./dmd_gif_converter.py

# Changer le mode ou le nombre de workers
./dmd_gif_converter.py --mode anime --workers 6

# Traiter des dossiers spécifiques
./dmd_gif_converter.py gifs_Arcade gifs_Consoles

# Colorimétrie custom complète
./dmd_gif_converter.py --mode custom --saturation 2.8 --contrast 1.7

# Régler le scroll
./dmd_gif_converter.py --scroll-speed 32 --scroll-cycles 1.75

# Aide
./dmd_gif_converter.py --help
```

Les dossiers de sortie sont créés automatiquement (`Arcade/`, `Consoles/`…).

**Exemple de log :**
```
12:34:01 [INFO   ] === gifs_Arcade → Arcade  (42 file(s)) | mode=pixel_art ===
12:34:02 [INFO   ] [SCROLL ] mslug.gif | src 320x240 → 128x96 | scroll_dist=64px | cycles=1.5 (full=1 frac=0.50 stop=32px) | fps=12.5 | total=4.54s
12:34:04 [INFO   ] [OK    ] mslug.gif
```

---

## ⚙️ Paramètres

Tous les paramètres sont accessibles via **curseurs et listes déroulantes dans l'interface**, et via **flags `--arg` en ligne de commande**.

### Mode de contenu

| Mode | Pour quel contenu | Saturation | Sharpening |
|---|---|---|---|
| `pixel_art` | Sprites rétro, arcade, consoles ★ défaut | `2.2` 🔥 max | `1.8` agressif |
| `anime` | Anime / cartoon (plus doux) | `1.9` ✨ vif | `1.3` net |
| `cinema` | Films live, vidéos réelles | `1.3` 🎞️ naturel | `0.8` doux |
| `custom` | Réglage manuel de chaque valeur | libre | libre |

### Référence complète des paramètres

| Paramètre | Flag CLI | Défaut | Description |
|---|---|---|---|
| `max_workers` | `--workers` | `2` | Processus ffmpeg en parallèle |
| `scroll_speed` | `--scroll-speed` | `24.0` | Vitesse de défilement (px/s) |
| `bottom_crop_pct` | `--bottom-crop` | `0.15` | Part du bas ignorée (pieds, sol) |
| `scroll_cycles` | `--scroll-cycles` | `1.5` | Nombre de cycles + position d'arrêt (voir ci-dessous) |
| `fps_min` | `--fps-min` | `10.0` | FPS minimum (upsampling si source plus lent) |
| `fps_max` | `--fps-max` | `25.0` | FPS maximum (plafond ESP32) |
| `contrast` | `--contrast` | `1.6` | Mode custom — 0.5 à 2.5 |
| `saturation` | `--saturation` | `2.2` | Mode custom — 0.0 à 4.0 |
| `brightness` | `--brightness` | `-0.03` | Mode custom — compensation dalle LED |
| `gamma` | `--gamma` | `0.85` | Mode custom — correction gamma |
| `sharpen_lum` | `--sharpen-lum` | `1.8` | Netteté luminance |
| `sharpen_chr` | `--sharpen-chr` | `0.5` | Netteté chroma |
| `dither` | `--dither` | `none` | `none` recommandé pour contenu défilant |

**Paramètres avancés** (interface uniquement — tous défaut = aucun changement) :

| Paramètre | Défaut | Description |
|---|---|---|
| `scroll_enabled` | `True` | `False` = mode crop manuel |
| `zoom` | `1.0` | Multiplicateur de mise à l'échelle avant crop |
| `manual_x` | `0` | Décalage horizontal du crop en px (mode manuel) |
| `manual_y` | `0` | Décalage vertical du crop en px (mode manuel) |
| `hue_shift` | `0.0` | Rotation de teinte en degrés |
| `noise_reduction` | `0.0` | Force du filtre hqdn3d |
| `film_grain` | `0` | Quantité de bruit additif |
| `vignette` | `False` | Assombrissement des bords |
| `max_duration` | `0.0` | Durée maximale du clip en secondes (`0` = pas de limite) |
| `auto_color_enabled` | `False` | 🎨 Smart Color Boost — colorimétrie heuristique IA |
| `auto_action_enabled` | `False` | 🤖 Caméra IA cinématique — voir section dédiée |
| `action_detector` | `person` | `person` / `motion` / `hybrid` / `center` |
| `action_intro` | `1.5` | Durée du plan large d'introduction en secondes |
| `action_strength` | `0.65` | Serrage du cadre autour du sujet |
| `action_smoothness` | `0.85` | Facteur de lissage exponentiel de la caméra |
| `action_zoom_max` | `1.8` | Zoom IA maximum |
| `action_padding` | `0.20` | Marge autour du ROI détecté |
| `bg_sub_enable` | `False` | Remplace le fond par du noir (maximise le contraste du sujet) |
| `target_width` | `128` | Largeur de sortie en pixels (tiling multi-dalle) |
| `target_height` | `32` | Hauteur de sortie en pixels (tiling multi-dalle) |
| `text_overlay_enabled` | `False` | 💬 Graver un texte dans le GIF de sortie |
| `text_content` | `""` | Chaîne de texte à afficher |
| `text_font_size` | `8` | Taille de la police en pixels |
| `text_color` | `white` | Couleur du texte (`white` / `yellow` / `red` / `green` / `blue` / hex) |
| `text_position` | `bottom_center` | Une des 9 positions d'ancrage |
| `text_font_file` | `HelvetiPixel.ttf` | Fichier de police dans `media/fonts/` |

### `scroll_cycles` expliqué

La partie entière = nombre d'**allers-retours complets** (bas→haut) ; la partie fractionnaire × `scroll_dist` = **position d'arrêt** où l'image se fige jusqu'à la fin de la source :

| Valeur | Comportement |
|---|---|
| `0.5` | Descend à mi-chemin, s'arrête au centre |
| `1.0` | 1 aller-retour, s'arrête en haut |
| `1.5` ★ défaut | 1 aller-retour puis s'arrête au centre (50 %) |
| `1.75` | 1 aller-retour puis s'arrête aux ¾ |
| `2.0` | 2 allers-retours, s'arrête en haut |

### Réglage de `--workers`

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
[cycle 1]  haut ──bas──▶ fond ──haut──▶ haut
[partiel]  haut ──bas──▶ stop_pos ──pause jusqu'à fin source──▶ (boucle)
```

- **`scroll_cycles = 1.5`** (défaut) : 1 aller-retour complet puis descend jusqu'au centre (50 % de la distance), s'arrête là
- **Crop du bas** (`bottom_crop_pct`) : les 15 % inférieurs (pieds, sol) sont ignorés → distance de scroll réduite
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
| Conversion très lente | Augmenter `--workers` (SSD + multi-cœurs recommandé) |
| Couleurs trop saturées | Passer en `--mode anime` ou baisser `--saturation` en mode custom |
| GIF trop sombre | Augmenter `--brightness` (ex. `0.05`) ou `--gamma` (ex. `0.95`) |
| Scroll trop rapide / lent | Ajuster `--scroll-speed` (défaut : `24.0`) |
| Arrêt à la mauvaise position | Ajuster `--scroll-cycles` (défaut `1.5` = arrêt au centre) |
| Banding sur les dégradés | Passer en mode `anime` ou `cinema` — le dithering crée des raies avec du contenu défilant |
| L'aperçu DMD ne se rafraîchit pas | Attendre ~2 s après le dernier déplacement de curseur ; vérifier qu'un fichier est sélectionné |
| Mode manuel montre la mauvaise zone | Augmenter d'abord le Zoom, puis ajuster les curseurs X/Y |
| Auto Action : « OpenCV not installed » | Lancer `pip install opencv-python` ou re-lancer `./launch_ui.sh` (installe automatiquement) |
| Aperçu Auto Action lent à apparaître | Normal — l'analyse IA prend quelques secondes par vidéo ; progression affichée dans le canvas AUTO ACTION |
| Résultat Auto Action incorrect | Essayer un autre **mode de détection** (`motion` ou `hybrid`) — le mode `person` fonctionne mieux avec des silhouettes humaines visibles |
| Smart Color Boost donne de mauvaises couleurs | Désactivez-le et réglez manuellement — fonctionne mieux sur du contenu mal exposé ou hétérogène |
| Smart Color Boost log affiche `fallback` | OpenCV non disponible — lancer `pip install opencv-python` |
| Le texte overlay n'apparaît pas | Vérifiez que **Text Content** n'est pas vide et que le fichier de police existe dans `media/fonts/` |
| `[ERROR] Font file '…' not found` | La police sélectionnée est absente de `media/fonts/` — choisir une autre police dans la liste |
| `[TEXT  ] … ffmpeg drawtext unavailable` | Normal sur macOS avec le ffmpeg Homebrew (compilé sans `--enable-libfreetype`) — **le fallback Pillow est utilisé automatiquement**, aucune action requise |
| Le bouton Recherche GIF est désactivé | Installez les dépendances manquantes : `pip install duckduckgo-search requests` (ou relancez `./launch_ui.sh`) |
| Recherche GIF : 0 résultat | DuckDuckGo peut limiter les requêtes rapides — patientez quelques secondes et réessayez |
| GIFs téléchargés très volumineux | Normal pour les GIFs web — le convertisseur les redimensionne automatiquement en 128×32 |
| Erreurs de timeout pendant le téléchargement | Certains hébergeurs d'images sont lents — augmentez la quantité pour compenser les URLs ignorées |

---

## 📄 Licence

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
