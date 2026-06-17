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
| `action_smart_auto_crop` | 🧠 Smart Auto Crop | `OFF` | **Le moteur analyse 60 images et active le profil de caméra optimal** via une **Matrice de Score Continue**. Il évalue 9 types de scènes (ex: `talking_closeup`, `platformer`, `action_horizontal`) sur la base du ratio de hauteur, variance X/Y, et dimensions de la boîte. La scène avec le meilleur score l'emporte, configurant automatiquement les crops, le suivi du sol et la marge. Les logs UI affichent un `=== Scene Classification Scoreboard ===` détaillant comment l'IA a pris sa décision. |
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

### 🧠 Matrice de Score Continue (v6.3.0)

> Remplace le modèle en cascade rigide pour classifier intelligemment les scènes et assigner le profil de caméra parfait.

Quand **Smart Auto Crop** est activé, le moteur évalue les 60 premières images de votre vidéo face à 9 profils de scènes distincts (ex: `talking_closeup`, `platformer`, `action_horizontal`, `tall_character`).

Plutôt qu'un simple arbre de décision IF/ELSE, chaque image rapporte des points à une **Matrice de Score Continue** basée sur :
1. **Ratio d'aspect (`h/w`)** : Le sujet est-il grand et fin, ou large et court ?
2. **Taille de la boîte (`roi_h`)** : Le sujet remplit-il tout l'écran, ou est-ce un petit sprite ?
3. **Variance de mouvement (`var_x`, `var_y`)** : Le sujet bouge-t-il rapidement à l'horizontale (comme un jeu de plateforme) ou reste-t-il relativement fixe (comme un visage qui parle) ?
4. **Stabilité du sol** : Y a-t-il un niveau de sol constant détecté par le tracker EMA ?

Le profil de scène avec le score total le plus élevé dicte le comportement final de la caméra. Il existe **12 types de scènes possibles** dans le système, que vous pouvez également forcer manuellement via la CLI en utilisant l'argument `--scene-type` :

#### 🎮 Profils de Jeu & Action
- **`platformer`** : Pour les jeux 2D avec un sol stable (ex: Mario, Sonic). Active le suivi automatique du sol pour verrouiller la caméra sur le terrain.
- **`top_down_isometric`** : Pour Zelda, Pokémon et les jeux isométriques. Se concentre sur le suivi horizontal et vertical sans contrainte de gravité. Le zoom est restreint pour préserver le contexte.
- **`first_person`** : Pour Doom, Minecraft et l'action centrée. Verrouille fermement la caméra au centre et empêche le zoom pour éviter de couper le HUD ou les armes.

- **`action_horizontal`** : Pour les jeux à défilement horizontal (beat 'em ups). Active le biais vertical automatique pour maintenir le niveau du sol cohérent pendant que la caméra défile vers la droite.
- **`action_moving`** : Pour les RPG ou les jeux où le sujet se déplace librement dans toutes les directions. Utilise un suivi fluide standard sans verrouiller le sol.
- **`wide_shot`** : Pour les scènes avec de petits sujets et beaucoup d'arrière-plan. Utilise un suivi très lâche (force 0.40) et une fluidité élevée (0.90) pour éviter que la caméra ne tressaute de manière agressive.
- **`menu_static`** : Pour les écrans titres, les menus et les scènes très statiques. Verrouille la caméra et lisse fortement les micro-mouvements pour garder l'écran stable.

#### 👤 Profils Humains & Dialogue
- **`talking_closeup`** : Pour les animes, vlogs ou dialogues où le visage remplit le cadre. Active le **Mode Priorité Visage**. La caméra ignore le bas du corps et se verrouille rigidement sur la région des yeux (en sautant les 25% supérieurs pour les cheveux, et en ciblant les 35% suivants pour le visage) pour que le visage ne rebondisse pas pendant la prise de parole.
- **`talking_medium`** : Pour les présentateurs de journaux ou les plans taille-tête. Active le Mode Priorité Visage, calculant la tête comme les 22% supérieurs de la boîte englobante du corps visible.
- **`full_body_tall`** : Pour les personnages debout ou les grands sprites d'anime. Active le Mode Priorité Visage, calculant la tête comme les 22% supérieurs du corps, ce qui garantit que le visage est centré plutôt que de couper le sujet aux épaules.
- **`full_body_medium`** : Suivi générique standard pour les sujets en pied sans Priorité Visage. Utilise des marges de suivi plus serrées.

### 🎥 Détection Dynamique de Scène (Par Plan)

Lors de la génération de "AI Moments" ou du traitement de montages, les vidéos coupent souvent entre plusieurs angles de caméra (ex: d'un plan large à un gros plan de visage).

Activez la case **Dynamic Scene Detection** (ou `--dynamic-scene` dans la CLI) pour demander au moteur de suivi de réévaluer le profil de scène à la volée. Lorsqu'une coupe de caméra est détectée, le moteur rassemble l'historique de quelques images et bascule automatiquement vers le Profil de Scène le plus approprié pour le nouveau plan.

Vous pouvez inspecter exactement comment l'IA prend sa décision en consultant le tableau `=== Scene Classification Scoreboard ===` affiché dans le panneau de logs de l'interface pour chaque vidéo traitée.

### 🔄 Auto Detector Fallback (Détecteur de Secours)

Lorsque vous traitez du contenu mixte, le détecteur principal `person` peut échouer sur des gros plans très serrés ou des sujets non humains.

Activez la case **Auto Detector Fallback** (ou `--action-auto-detector-fallback` dans la CLI) pour permettre au moteur de basculer dynamiquement sur le détecteur `hybrid` si aucune personne n'est trouvée. Combiné avec la Détection Dynamique de Scène, cela permet au moteur de suivre une personne sur le premier plan, et de basculer de manière transparente sur le suivi des mouvements et des visages sur le plan suivant si la personne disparaît.

### 🛠️ Forçage Manuel via CLI
Si vous souhaitez contourner la Matrice de Score Continue et forcer explicitement l'un des 9 profils, vous pouvez utiliser l'argument `--scene-type`. Cela désactive la phase d'analyse de l'IA et applique immédiatement les règles de suivi du profil choisi :

```bash
# Force le profil Platformer (verrouille la caméra sur le sol)
python3 -m src.engine.conversion.cli gifs_Sonic --scene-type "platformer"

# Force le profil Gros plan avec Priorité Visage
python3 -m src.engine.conversion.cli input.mp4 --scene-type "talking_closeup"
```

---

## 🎨 Smart Color Boost — colorimétrie heuristique par IA

> **En bref — une case à cocher, des couleurs parfaites sur toutes les sources, y compris les scènes sombres.**  
> Dans le panneau **⚙️ Parameters** → section **🎨 Content mode → Smart Color Boost** · désactivé par défaut.

Les dalles LED matricielles ont des caractéristiques d'affichage très différentes des écrans : lumière diffusée, profondeur de bits limitée, luminosité perçue élevée. Un contenu parfait sur écran peut apparaître délavé, trop sombre ou sur-saturé sur un panel HUB75 128×32.

**Smart Color Boost** résout ça automatiquement. Il analyse **trois keyframes représentatives** de chaque vidéo source (à 25 %, 50 %, 75 % de la durée) et calcule le profil colorimétrique optimal pour ce contenu spécifique, sans aucune intervention manuelle.

```
Vidéo source  ──[keyframes × 3]──▶  analyse heuristique  ──▶  paramètres optimaux  ──▶  ffmpeg
                                              ↑
                                  Luminance (niveau de gris moyen)
                                  Dynamique (écart-type)
                                  Saturation couleur (canal S HSV)
                                  🌑 Détection scène sombre (lum < 80)
```

### Ce qu'il analyse et corrige

| Mesure | Ce qui est détecté | Correction appliquée |
|---|---|---|
| **Luminance moyenne** | Sous-exposé (sombre) · sur-exposé (clair) | Boost/réduction du **Gamma** |
| **Écart-type** | Image terne / délavée (faible dynamique) | Multiplicateur de **Contraste** |
| **Saturation HSV** | Désaturé · quasi-niveaux de gris | Boost de **Saturation** |
| **Scène sombre** `lum < 80` | Nuit / cinéma / donjon | Contraste **capé** + gamma et brightness plus agressifs |

### 🌑 Détection des scènes sombres (amélioration v6.x)

Pour les contenus avec une luminance moyenne inférieure à 80/255 (cinéma sombre, scènes nocturnes, donjons), les versions précédentes appliquaient un contraste élevé qui **écrasait les détails sombres**, rendant les personnages invisibles sur la dalle LED. C'est maintenant corrigé :

| Paramètre | Comportement si `lum < 80` | Effet |
|---|---|---|
| **Gamma** | Jusqu'à **1,70** (était capé à 1,40) | Élève les tons moyens ; personnages visibles |
| **Brightness** | **+0,04 à +0,07** (était ≈ 0) | Décale toute la plage tonale vers le haut |
| **Contraste** | **Capé à 1,40–1,60** (était non capé) | Évite d'écraser les détails sombres |

> **Exemple** — *Retour vers le futur II* scène sombre (`lum=67 std=51`) :  
> - Avant : `contrast=1.79 gamma=1.10 bri=+0.004` → personnages à peine visibles  
> - Après  : `contrast=1.57 gamma=1.21 bri=+0.036 🌑dark` → personnages clairement visibles

Le log affiche désormais le tag `🌑dark` (ainsi que d'autres tags sémantiques comme `[Vivid]`, `[Washed Out]`) quand le mode scène correspondant est déclenché :
```
[COLOR  ] scene.mkv — auto-color (1 frame) [Dark + Low Contrast]: lum=67 std=51 sat=138 → contrast=1.57 (+−0.03) …
```

### Quels modes profitent de cette amélioration ?

> **Smart Color Boost fonctionne de la même façon pour TOUS les modes de contenu** (pixel_art, anime, cinema, custom) car il remplace entièrement le preset par `mode="custom"` une fois activé.

| Mode | Sans Smart Color Boost | Avec Smart Color Boost |
|---|---|---|
| `pixel_art` | gamma=0.85, contrast=1.60 (fixe) | S'adapte au contenu source |
| `anime` | gamma=0.87, contrast=1.50 (fixe) | S'adapte au contenu source |
| `cinema` | gamma=0.95, contrast=1.35 (fixe) | S'adapte au contenu source |
| `custom` | Curseurs manuels | **Smart Color Boost prend le relais** |

**Pour du pixel art sombre, de l'anime nocturne, ou du cinéma obscur → activez Smart Color Boost.**  
Les presets statiques ne peuvent pas détecter les scènes sombres ; seul Smart Color Boost le peut.

### Exemples de compensation (mis à jour)

| Type de source | lum | std | → contraste | saturation | gamma | notes |
|---|---|---|---|---|---|---|
| Scène cinéma sombre | 67 | 51 | **1,57** | 2,15 | **1,21** | 🌑dark cap appliqué |
| Scène nocturne / donjon | 31 | 22 | **1,40** | 2,45 | **1,65** | 🌑dark cap appliqué |
| Sprite arcade normal | 116 | 62 | 1,20 | 1,90 | 0,93 | |
| Surexposé / trop lumineux | 190 | 20 | 1,60 | 3,46 | **0,60** | |
| Déjà contrasté et vivid | 120 | 75 | 1,20 | 1,50 | 0,89 | |
| Quasi N&B | 129 | 54 | 1,20 | **3,00** ↑↑ | 0,81 | |

### Pourquoi c'est désactivé par défaut

Smart Color Boost **remplace les curseurs de colorimétrie manuelle** et les grise dans l'UI pour éviter les conflits.

**Activez-le pour :**
- Des bibliothèques hétérogènes avec des expositions très différentes d'un fichier à l'autre
- Des vidéos live ou cinéma dont l'exposition source est inconnue
- **Tout contenu sombre (scènes nocturnes, donjons, cinéma) quel que soit le preset**
- Tout contenu qui ne rend pas bien avec les presets standards

### Comment l'activer

1. Lancez l'interface avec `./launch_ui.sh`
2. Dans le panneau **⚙️ Parameters** → section **🎨 Content mode**
3. Cochez **"🎨 Smart Color Boost — IA auto-colorimetry"**
4. Les curseurs de colorimétrie manuelle se grisent automatiquement
5. Lancez la conversion — le log affiche les valeurs calculées :  
   `[COLOR ] lum=XX std=XX → contrast=X.XX …` (+ `🌑dark` si scène sombre détectée)

### Prérequis

Smart Color Boost utilise le même **OpenCV + NumPy** qu'Auto Action — aucune dépendance supplémentaire. L'analyse est rapide (<0,5 s par fichier) et négligeable par rapport au temps de conversion ffmpeg.

En l'absence d'OpenCV, le fallback silencieux s'applique — **pas de crash, pas de perte de données**.

---

## ⚡ Conversion parallèle — multithreading

### Identifiants worker dans les logs

Lors d'un **Convert All** avec plusieurs workers, chaque message de log est maintenant préfixé par un tag `[W{n}]` permettant d'identifier quel worker a produit quelle sortie :

```
🚀  Convert 3 file(s) using 2 worker(s)…
[W1] [ACTION ] clip_a.mkv — Auto action OK (303 frames…)
[W2] [ACTION ] clip_b.mkv — Auto action OK (241 frames…)
[W1] [COLOR  ] clip_a.mkv — lum=67 … 🌑dark
[W2] [COLOR  ] clip_b.mkv — lum=146 …
[W1] [OK    ] clip_a.mkv
[W2] [OK    ] clip_b.mkv
[W1] [OK    ] clip_c.mkv   ← W1 traite le 3e fichier
✅  3 conversion(s) done.
```

### Correction du deadlock pipe stderr (v6.x)

Un deadlock de buffer pipe causait silencieusement l'apparence d'une conversion séquentielle ou d'un gel lors de conversions longues :

- **Cause racine :** ffmpeg écrit des stats de progression sur stderr. Sans lecture continue, le buffer OS (~64 Ko) se remplit. ffmpeg se bloque en tentant d'écrire, `poll()` ne revient jamais → tous les workers parallèles se gelent simultanément.
- **Correction :** un thread daemon de drainage lit stderr en chunks de 4 Ko en permanence. La boucle de polling et d'annulation n'est pas affectée.

Ce correctif s'applique à :
- `process_file()` (fichier unique, UI ou CLI)
- `process_folder()` (dossier batch)
- `FFmpegWriter.close()` (pipe de prétraitement auto-action)

---

## 📟 Logs terminal

### Lancement UI

Les scripts `./launch_ui.sh` (macOS/Linux), `launch_ui.bat` (Windows), et `launch_ui.ps1` (PowerShell) routent maintenant correctement les logs Python vers le terminal.

```bash
./launch_ui.sh
# Sortie :
# 10:42:31 [INFO   ] [UI] DMD Converter starting…
# 10:42:35 [INFO   ] … [ACTION ] clip.mkv — Auto action OK …
# 10:42:36 [INFO   ] … [COLOR  ] clip.mkv — lum=67 🌑dark …
```

**Si les logs n'apparaissent pas dans votre terminal**, assurez-vous de lancer via le script :

```bash
# ✅ Correct — logging configuré par launcher.py
./launch_ui.sh

# ⚠️  Invocation directe — fonctionne aussi
python -m src.ui.launcher

# ❌ Pas de logs terminal (contourne la configuration logging)
python -m src.ui.app
```

### Contrôle du niveau de log (UI)

Utilisez le menu **Filter** dans le bas du panneau log :

| Niveau | Affiche |
|---|---|
| `DEBUG` | Tout, y compris la sortie brute ffmpeg |
| `INFO` | Messages de conversion normaux (défaut) |
| `WARNING` | Seulement avertissements et erreurs |
| `ERROR` | Seulement les erreurs |

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

## Performances et Sous-échantillonnage

Pour optimiser l'utilisation du processeur pendant l'inférence YOLO, deux paramètres vous permettent d'équilibrer le temps de traitement et la précision :

1. **Auto-Action Subsample Frames** (Tracking) :
   - Ignore l'inférence YOLO sur N images pendant le tracking Auto-Action normal.
   - *Exemple* : `3` signifie que le moteur lance l'inférence toutes les 3 images et interpole la zone de détection entre elles.
   - *CLI* : `--action-subsample-frames 3`

2. **Auto Fast Tracking** (Tracking Dynamique) :
   - Écrase le paramètre manuel de sous-échantillonnage et l'ajuste automatiquement en fonction des FPS de la vidéo d'entrée. Cible ~5 inférences YOLO par seconde pour garantir de hautes performances sur les gros fichiers 60fps/120fps sans réglage manuel.
   - *CLI* : `--auto-fast-tracking`

3. **Analyze FPS** (AI Moments) :
   - Définit le nombre d'images par seconde que le moteur AI Moments analyse.
   - *Exemple* : `5.0` signifie que 5 images par seconde sont analysées. Une valeur plus basse accélère l'analyse mais réduit la précision. Une valeur plus haute détecte les micro-mouvements mais prend plus de temps.
   - *CLI* : `--ai-moments-analyze-fps 5.0`


## Accélération Matérielle (GPU Encoders)

Le moteur tente automatiquement d'utiliser les encodeurs vidéo à accélération matérielle lors du processus de rendu interne FFmpeg pour accélérer considérablement les temps de traitement et réduire l'utilisation du processeur. 
Il effectue une détection dynamique au démarrage dans `src.engine.conversion.hardware_accel` :

- **macOS (Apple Silicon / Intel)** : `h264_videotoolbox`
- **NVIDIA GPUs** : `h264_nvenc`
- **Intel GPUs** : `h264_qsv`
- **Repli (Fallback)** : `libx264`

L'accélération matérielle est appliquée automatiquement sans aucune configuration requise par l'utilisateur, à condition que la machine hôte dispose du GPU et des pilotes appropriés installés.
