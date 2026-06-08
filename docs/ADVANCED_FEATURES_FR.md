# Fonctionnalités Avancées & Architecture

## 🤖 Auto Action Framing — caméra cinématique par IA

> **En bref — activez-le, laissez tourner, admirez le résultat.**  
> Accessible dans **🔧 Advanced Settings → 🎯 Auto Action Framing** · désactivé par défaut.

C'est la fonctionnalité la plus puissante du convertisseur. Au lieu d'un crop statique ou d'un simple scroll vertical, le moteur **Auto Action** analyse chaque image de votre vidéo source avec de la **vision par ordinateur (OpenCV)** et génère automatiquement des **mouvements de caméra de qualité cinématique** avant de transmettre le résultat à ffmpeg :

```
Vidéo source  ──[analyse IA]──▶  crop 4:1 cinématique  ──[ffmpeg]──▶  GIF DMD 128×32
                     ↑
         Détection de personnes (ONNX YOLOv8 nano)
         Détection de mouvement (soustraction de fond MOG2)
         Caméra virtuelle à lissage exponentiel
         Plan large d'introduction panoramique
         Suivi automatique du sol (jeux de plateformes 2D)
```

### Ce que ça fait automatiquement

| Phase | Ce qui se passe |
|---|---|
| **Panoramique intro** | Commence par un plan large (1,5 s par défaut) pour que le spectateur comprenne la scène |
| **Détection IA** | Détecte les personnes (ONNX YOLOv8 nano) et/ou les mouvements image par image |
| **Cadrage cinématique** | Calcule la fenêtre de crop 4:1 idéale centrée sur l'action, avec un padding configurable |
| **Caméra lissée** | Applique un lissage exponentiel pour simuler un vrai caméraman — pas de saccades |
| **Extension queue** | Si la vidéo est trop courte pour que la caméra finisse son mouvement, la dernière image est prolongée jusqu'à convergence |

### Pourquoi c'est désactivé par défaut

Auto Action effectue une **analyse d'image intensive en CPU** sur chaque frame (détection de personnes via **ONNX YOLOv8 nano**, soustraction de fond MOG2). C'est nettement plus lourd qu'une simple passe ffmpeg :

- **Charge CPU :** 2 à 5× plus élevée que la conversion standard
- **Temps de traitement par fichier :** approximativement doublé
- **Mémoire :** chaque worker charge la vidéo entière en frames brutes
- **Premier lancement :** télécharge le modèle YOLOv8n ONNX (~6 Mo) dans `~/.cache/dmd_gif_converter/` — les lancements suivants utilisent le cache

Pour les bibliothèques de sprites rétro ou de GIFs pixel art, le pipeline scroll standard est déjà optimal.  
**Pour de la vidéo live, du sport, des clips, ou toute vidéo avec une personne ou un sujet en mouvement → activez Auto Action et obtenez un résultat professionnel entièrement automatisé.**

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
| `action_strength` | Action strength | `0.65` | `0` = cadrage large · `1` = zoom serré sur le sujet |
| `action_auto_strength` | Auto strength | `OFF` | Adapte automatiquement la force en fonction du type de contenu (0.55 anime, 0.65 jeux) |
| `action_smoothness` | Camera smooth | `0.65` | `0` = instantané · `0.98` = caméra très lente |
| `action_auto_smoothness`| Auto smooth | `OFF` | Adapte automatiquement le lissage en fonction du type de contenu (0.85 anime, 0.70 jeux) |
| `action_zoom_max` | Zoom max | `1,8×` | Zoom dynamique maximum que la caméra IA peut appliquer |
| `action_padding` | ROI padding | `0,20` | Espace de respiration autour du sujet détecté |
| `action_bottom_crop` | Bottom crop % | `0 %` | Exclut les N % inférieurs du frame de la détection (manuel — ignoré si auto actif) |
| `action_auto_bottom_crop` | Auto bottom crop | `OFF` | **Détecte automatiquement** la limite basse du sujet. Active le mode **Face Priority** 👤 quand le corps est plus grand que la fenêtre DMD — recadre sur la région menton (~20 % du corps depuis le haut) avec un rembourrage asymétrique pour que **le visage soit centré, pas coupé aux épaules** |
| `action_top_crop` | Top crop % | `0 %` | Exclut les N % supérieurs du frame de la détection (manuel — ignoré si auto actif) |
| `action_auto_top_crop` | Auto top crop | `OFF` | **Détecte automatiquement** la limite haute du sujet (tête / ciel) — adapte la marge selon face ou corps entier |
| `action_vertical_bias` | Vertical bias | `0,0` | Décalage vertical manuel : `+1,0` = caméra vers le bas (sol visible), `-1,0` = caméra vers le haut |
| `action_auto_vertical_bias` | Auto floor detect | `OFF` | **Détecte automatiquement** le niveau du sol via un EMA asymétrique — résiste aux sauts, suit les atterrissages. Écrase le bias manuel. Idéal pour les jeux de plateformes 2D. |
| `action_smart_auto_crop` | 🧠 Smart Auto Crop | `OFF` | **Le moteur analyse 60 images et active la combinaison optimale** via 3 groupes mutuellement exclusifs. GROUPE 1 (personnage très grand > 80 %) → face priority (top+bottom, pas de sol). GROUPE 2 (sol stable et détectable) → suivi du sol + bottom optionnel. GROUPE 3 (normal) → top+bottom ensemble. Résout automatiquement la contradiction face-priority ↔ floor-tracking. |
| **🚀 Let Me Handle It** | Mode full-auto en un clic — active les 5 systèmes IA (Smart Color Boost + Auto Action + Smart Auto Crop + Soustraction de fond + DMD Visibility Score) et grise les réglages non pertinents |

### Modes de détection

| Mode | Idéal pour |
|---|---|
| `person` ★ défaut | Vidéos avec des personnes — ONNX YOLOv8 nano, repli sur la détection de mouvement si indisponible |
| `motion` | Sport, véhicules, action rapide sans silhouette humaine claire |
| `hybrid` | Fusionne les boîtes person + motion — couverture la plus large |
| `center` | Pas de détection — caméra centrée (panoramique intro uniquement) |

### Auto floor detect — suivi dynamique du sol

> **Idéal pour les jeux de plateformes 2D** et tout contenu où le niveau du sol change.

Quand **Auto floor detect** est activé, la caméra utilise un **EMA asymétrique** (Exponential Moving Average) pour mémoriser le niveau du sol image par image :

| Situation | Comportement |
|---|---|
| Personnage **atterrit** / descend sur une plateforme plus basse | L'estimation du sol se met à jour rapidement (α = 0,28 — atteint le nouveau sol en ~10 images) |
| Personnage **saute** ou monte | L'estimation du sol bouge à peine (α = 0,02 — < 30 px de dérive sur 8 frames en l'air) |
| Sujet **hors-champ** (pas de détection) | La caméra maintient le dernier niveau de sol connu — pas de dérive |

La caméra reste ainsi ancrée au sol pendant les sauts et suit naturellement le personnage quand il atterrit sur une nouvelle plateforme (plus basse).

**Règles de priorité :**
1. `auto_vertical_bias = True` → suivi auto du sol actif, `vertical_bias` manuel ignoré
2. `auto_vertical_bias = False` + `vertical_bias ≠ 0` → décalage manuel appliqué
3. Les deux désactivés → la caméra suit le centre du ROI (comportement par défaut)

**Flag CLI :**
```bash
python auto_action_cli.py input.mp4 --auto-floor-detect
```

### Auto crop haut / bas — cadrage automatique du sujet

> **Pour tout type de contenu** : animations de visage en gros plan, personnages en pied, sprites 2D.

#### Auto bottom crop

Analyse un échantillon de frames (~40) et détecte où **le sujet se termine en bas** (pieds, sol, ligne de sol).
Élimine automatiquement le HUD, les barres de sous-titres et les dalles de sol vides qui feraient descendre la caméra.

##### 👤 Mode Face Priority (automatique) — amélioré en v5.0.0

Quand le personnage détecté est **plus grand que la fenêtre DMD** (hauteur ROI > 80 % de `largeur_frame / ratio_cible`), le système bascule automatiquement en **mode Face Priority** :

- La limite basse effective est calculée au niveau du **menton** (~20 % de la hauteur du corps depuis le haut de la tête — et non 32 % au niveau des épaules comme dans les versions précédentes)
- Le rembourrage est **asymétrique** : `+10 % de marge au-dessus` (front) + `+3 % tampon sous le menton` — le visage est centré avec de l'espace naturel
- **La caméra utilise les limites complètes de la frame** (pas la zone de détection restreinte) — empêche la caméra d'être bloquée au niveau des épaules
- Le tag `[face priority 👤]` apparaît dans le journal de conversion quand ce mode s'active


#### Auto top crop

Détecte où **le sujet commence en haut** (tête, bout des cheveux, pointe d'arme).
Élimine le ciel, le plafond ou les bandes noires au-dessus du personnage.

#### Adaptation au type de contenu

Le ratio d'aspect médian de la bounding box détectée permet d'inférer si le sujet est un **visage/gros plan** ou un **corps entier**, et d'ajuster la marge en conséquence :

| Ratio h/w | Type de sujet | Marge ajoutée |
|-----------|---------------|---------------|
| < 1,3 | Gros plan / visage | 15 % de la hauteur du frame |
| 1,3 – 2,5 | Buste / haut du corps | 10 % de la hauteur du frame |
| > 2,5 | Corps entier | 6 % de la hauteur du frame |

#### Bascule Manuel ↔ Auto

Les deux crops disposent d'une **case à cocher indépendante** et d'un curseur manuel :

- **Auto activé** → le curseur est grisé ; la valeur est calculée automatiquement à chaque rendu.
- **Auto désactivé** → le curseur est actif ; vous fixez le pourcentage manuellement.

Les deux modes sont totalement indépendants — auto bas + manuel haut est valide.

**Flags CLI :**
```bash
# Auto sur les deux bornes
python auto_action_cli.py input.mp4 --auto-bottom-crop --auto-top-crop

# Crop manuel bas + auto haut
python auto_action_cli.py input.mp4 --bottom-crop 0.10 --auto-top-crop

# Crop manuel haut et bas (comportement d'origine)
python auto_action_cli.py input.mp4 --top-crop 0.05 --bottom-crop 0.15
```

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
