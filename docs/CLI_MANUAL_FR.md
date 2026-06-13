# Manuel CLI & Paramètres

Vous préférez utiliser le script sans interface ? Voici les commandes les plus puissantes.
*Placez le script à côté de dossiers nommés `gifs_*` (ex: `gifs_Arcade/`)*.

```bash
# 1. Télécharger des GIFs et les convertir en mode tout-automatique !
python3 -m src.engine.conversion.cli --search-keyword "arcade" --let-me-handle-it

# 2. Convertir un dossier avec la caméra cinématique par IA
python3 -m src.engine.conversion.cli gifs_Arcade --auto-action-enabled

# 3. Ajouter un texte en pixel-art avec bordure sur une vidéo
python3 -m src.engine.conversion.cli input.mp4 --text-overlay --text-content "PLAYER 1" --text-color yellow
```

## ⚙️ Paramètres

Tous les paramètres sont accessibles via **curseurs et listes déroulantes dans l'interface**, et via **flags `--arg` en ligne de commande**.

### Mode de contenu

| Mode | Pour quel contenu | contraste | saturation | gamma | Sharpening |
|---|---|---|---|---|---|
| `pixel_art` | Sprites rétro, arcade, consoles ★ défaut | `1.60` | `2.20` 🔥 max | `0.85` | `1.8` agressif |
| `anime` | Anime / cartoon (plus doux) | `1.50` | `1.90` ✨ vif | `0.87` | `1.3` net |
| `cinema` | Films live, vidéos réelles | `1.35` ¹ | `1.30` 🎞️ naturel | `0.95` ¹ | `0.8` doux |
| `custom` | Réglage manuel de chaque valeur | libre | libre | libre | libre |

> ¹ **Preset cinema v6.x** — contraste réduit (1.40 → 1.35), gamma relevé (0.90 → 0.95), brightness à 0.00 pour ne pas écraser les scènes sombres.  
> Pour du contenu sombre quel que soit le preset, activez **Smart Color Boost** (`--auto-color-enabled`) qui adapte automatiquement les corrections.

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
| `dither` | `--dither` | `none` | Recommandé `none` pour le contenu défilant |

### Sortie & Logs
| Paramètre | Flag | Par défaut | Description |
|-----------|------|---------|-------------|
| `log-level` | `--log-level` | `WARNING` | Définit le niveau de log (DEBUG, INFO, WARNING, ERROR). Par défaut WARNING (affiche la barre de progression). |
| `verbose` | `--verbose` / `-v` | `False` | Alias pour `--log-level DEBUG`. Affiche les logs détaillés de FFMPEG. |

> **Note :** Les balises `[DYNAMIC]` dans les logs affichent en temps réel les changements de plan caméra, les transitions de profil (ex: `scene_change_detected`), et les ajustements de cadrage effectués par le moteur Auto Action.

### Extraction AI Moments

| Paramètre | Flag | Défaut | Description |
|-----------|------|---------|-------------|
| `ai_moments` | `--ai-moments` | `False` | Extrait les meilleurs moments des vidéos ET les convertit automatiquement en GIFs. |
| `ai_moments_only`| `--ai-moments-only`| `False` | Extrait les meilleurs moments (en MP4) mais NE LES CONVERTIT PAS en GIFs. |
| `ai_moments_count` | `--ai-moments-count` | `10` | Nombre maximum de moments à extraire par vidéo. |
| `ai_moments_strategy` | `--ai-moments-strategy` | `Balanced` | Stratégie à prioriser (`Action`, `Balanced`, `Character`). |
| `ai_moments_dur_min` | `--ai-moments-dur-min` | `2.0` | Durée minimale d'un moment extrait en secondes. |
| `ai_moments_dur_max` | `--ai-moments-dur-max` | `5.0` | Durée maximale d'un moment extrait en secondes. |

### A/B Testing Engine (Validation Scoring V2)

Pour valider et tester le moteur de Scoring localement, utilisez le nouveau lanceur A/B Testing :
```bash
python3 -m src.engine.testing.ab_runner tests/videos/
```
Cela exécutera le pipeline de prétraitement Auto Action sur toutes les vidéos du dossier cible, et générera un rapport Markdown détaillé (`report.md`) comparant le Scoring V1 et le Scoring V2 côte à côte.

**Paramètres avancés** (UI et CLI) :

| Paramètre | Drapeau CLI | Défaut | Description |
|---|---|---|---|
| `prefix` | `--prefix` | `gifs_` | Préfixe du dossier source |
| `no_scroll` | `--no-scroll` | `False` | `True` = désactive le défilement auto (active le mode crop manuel) |
| `zoom` | `--zoom` | `1.0` | Multiplicateur d'échelle avant recadrage (mode manuel) |
| `manual_x` | `--manual-x` | `0` | Décalage horizontal du recadrage en px (mode manuel) |
| `manual_y` | `--manual-y` | `0` | Décalage vertical du recadrage en px (mode manuel) |
| `hue_shift` | `--hue-shift` | `0.0` | Rotation de la teinte en degrés |
| `noise_reduction` | `--noise-reduction` | `0.0` | Force hqdn3d |
| `film_grain` | `--film-grain` | `0` | Quantité de bruit additif |
| `vignette` | `--vignette` | `False` | Assombrissement des bords |
| `max_duration` | `--max-duration` | `0.0` | Limite de durée du clip en secondes (`0` = sans limite) |
| `auto_color` | `--auto-color` | `False` | 🎨 Smart Color Boost — colorimétrie heuristique par IA |
| `auto_action` | `--auto-action` | `False` | 🤖 Caméra cinématique IA — voir la section dédiée |
| `action_detector` | `--action-detector` | `person` | `person` / `motion` / `hybrid` / `center` |
| `action_intro` | `--action-intro` | `1.5` | Durée du plan d'établissement en secondes |
| `action_strength` | `--action-strength` | `0.65` | Précision du cadrage autour du sujet |
| `action_smoothness` | `--action-smoothness`| `0.65` | Lissage exponentiel de la caméra |
| `action_zoom_max` | `--action-zoom-max` | `1.8` | Facteur de zoom IA maximum |
| `action_padding` | `--action-padding` | `0.20` | Marge autour du ROI détecté |
| `bg_sub_enable` | `--bg-sub-enable` | `False` | Remplace le fond par du noir (maximise le contraste du sujet) |
| `action_bottom_crop` | `--action-bottom-crop`| `0.0` | Exclut les N % inférieurs du cadre (manuel, 0 = désactivé) |
| `action_auto_bottom_crop`| `--action-auto-bottom-crop`| `False` | Détecte auto la limite basse du sujet (pieds / sol) |
| `action_top_crop` | `--action-top-crop` | `0.0` | Exclut les N % supérieurs du cadre (manuel, 0 = désactivé) |
| `action_auto_top_crop`| `--action-auto-top-crop`| `False` | Détecte auto la limite haute du sujet (tête / ciel) |
| `action_vertical_bias`| `--action-vertical-bias`| `0.0` | Décalage vertical manuel de la caméra (`+1.0` = sol, `-1.0` = plafond) |
| `action_auto_vertical_bias`| `--action-auto-vertical-bias`| `False` | Suivi automatique du sol — EMA asymétrique, écrase le bias manuel |
| `action_scene_type` | `--action-scene-type`| `""` | Force manuellement l'un des 9 profils de la Matrice Continue : `platformer` / `talking_closeup` / `full_body_tall` / `fighting_2d` / `action_horizontal` / `talking_medium` / `full_body_medium` / `wide_shot` / `action_moving`. Écrase l'auto-détection. |
| `action_auto_scene_type`| `--action-auto-scene-type`| `False` | Détection automatique du type de scène (écrase `--action-scene-type`). |
| `action_smart_auto_crop` | `--smart-auto-crop`| `False` | 🧠 Smart Auto Crop — analyse 60 images et active le profil de caméra optimal via une matrice de score continue de 9 scènes ; résout la contradiction face-priority ↔ floor-tracking |
| `reject_threshold` | `--reject-threshold`| `0` | Déplace automatiquement les GIFs générés vers la corbeille si leur DMD Visibility Score est strictement inférieur à N% (0-100). Défaut : 0 (désactivé). |
| `dmd_visibility_score_enabled` | `N/A` | `False` | 🔬 DMD Visibility Score — simule le recadrage proposé à la résolution DMD cible. (Implicitement activé par reject_threshold ou let_me_handle_it) |
| `let_me_handle_it` | `--let-me-handle-it`| `False` | 🚀 Laisse-moi gérer ça — mode tout-automatique : active Smart Color Boost + Auto Action + Smart Auto Crop + Soustraction de fond + DMD Visibility Score simultanément |
| `target_width` | `--target-width` | `128` | Largeur de sortie en pixels (tiling multi-dalle) |
| `target_height` | `--target-height` | `32` | Hauteur de sortie en pixels (tiling multi-dalle) |
| `text_overlay_enabled` | `--text-overlay` | `False` | 💬 Graver un texte dans le GIF de sortie |
| `text_content` | `--text-content` | `""` | Chaîne de texte à afficher |
| `text_font_size` | `--text-font-size` | `8` | Taille de la police en pixels |
| `text_color` | `--text-color` | `white` | Couleur du texte (`white` / `yellow` / `red` / `green` / `blue` / hex) |
| `text_position` | `--text-position` | `bottom_center`| Une des 9 positions d'ancrage |
| `text_font_file` | `--text-font-file` | `HelvetiPixel.ttf`| Fichier de police dans `media/fonts/` |
| `text_style` | `--text-style` | `outline` | Style de rendu du texte : `none` / `bold` / `outline` / `shadow` |
| `text_bg` | `--text-bg` | `False` | Dessiner une boîte d'arrière-plan semi-transparente sombre derrière le texte |
| `text_bg_opacity` | `--text-bg-opacity`| `150` | Opacité de la boîte d'arrière-plan 0-255 |

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
| MacBook Pro M-series (10+ cœurs) | `6`–`8` |
| Desktop SSD, 8+ cœurs, 16 Go+ | `6`–`8` |
| Desktop SSD, 4 cœurs, 8 Go | `3`–`4` |
| Laptop ou disque dur (HDD) | `2` |

> Les workers sont limités par le CPU (génération de palette + dithering ffmpeg). Au-delà de 8 workers le gain est faible et la pression mémoire augmente.  
> En mode UI, chaque log de worker parallèle est préfixé par `[W1]`, `[W2]`, etc. pour faciliter le filtrage.

### Logs terminal — launcher vs invocation directe

Pour obtenir **les logs Python dans votre terminal**, utilisez toujours le script fourni :

```bash
# ✅ Logs complets — src.ui.launcher configure logging.basicConfig
./launch_ui.sh         # macOS / Linux
launch_ui.bat          # Windows
./launch_ui.ps1        # PowerShell

# ⚠️  Fonctionne aussi — format plus simple
python -m src.ui.launcher

# ❌ Pas de logs terminal (contourne la configuration logging)
python -m src.ui.app
```

Contrôle de la verbosité en CLI :
```bash
--log-level INFO     # tous les messages
--log-level WARNING  # silencieux (seulement la barre de progression, défaut)
--verbose / -v       # alias pour --log-level DEBUG (affiche la sortie brute de ffmpeg)
```

## 📖 Exemples Complets par Cas d'Usage

Voici des exemples pour les principaux cas d'utilisation, montrant comment combiner ou séparer les différentes fonctionnalités de l'IA via la ligne de commande.

### 1. Conversion de Dossier Basique
Analyse tous les dossiers commençant par `gifs_` dans le répertoire courant et les convertit en GIFs DMD en utilisant les paramètres standards.
```bash
python3 -m src.engine.conversion.cli
```

### 2. Le Mode Magique "Let Me Handle It"
La commande ultime sans configuration. Elle applique la colorimétrie IA, le cadrage Auto Action, la soustraction de fond et l'évaluation de visibilité DMD tout en même temps sur un dossier spécifique.
```bash
python3 -m src.engine.conversion.cli gifs_MonGameplay --let-me-handle-it --workers 8
```

### 3. Superposition de Texte (Watermark / Tags Joueur)
Grave un tag jaune "PLAYER 1" en haut à gauche du GIF avec un contour pour la lisibilité.
```bash
python3 -m src.engine.conversion.cli gifs_DossierSource --text-overlay --text-content "PLAYER 1" --text-color "yellow" --text-position "top_left"
```

### 4. Smart Color Boost pour les Scènes Sombres
Convertit une scène de film très sombre (ex: Batman) en s'assurant qu'elle soit visible sur les panneaux LED grâce à la colorimétrie heuristique.
```bash
python3 -m src.engine.conversion.cli gifs_Batman --auto-color
```

### 5. Recherche Web & Téléchargement
Recherche "arcade fighting" sur DuckDuckGo, télécharge les 5 meilleurs résultats, et les convertit immédiatement en utilisant le profil de caméra de combat 2D.
```bash
python3 -m src.engine.conversion.cli --search-keyword "arcade fighting" --search-limit 5 --action-scene-type "fighting_2d"
```

### 6. AI Moments : Pipeline complet (Extraction + Conversion)
Prend une vidéo de gameplay de 10 minutes, trouve les 5 meilleurs moments d'action, et convertit immédiatement ces 5 extraits en GIFs 128x32.
```bash
python3 -m src.engine.conversion.cli gifs_GameplayBrut --ai-moments --ai-moments-count 5 --ai-moments-strategy "Action" --let-me-handle-it
```

### 7. AI Moments : Extraction UNIQUEMENT
Si vous souhaitez juste utiliser l'IA pour trouver les meilleurs moments et les sauvegarder en fichiers `.mp4` *sans* encore générer de GIFs.
```bash
python3 -m src.engine.conversion.cli gifs_GameplayBrut --ai-moments-only --ai-moments-count 10
```

### 8. Forçage Manuel de la Caméra
Désactive la détection de scène IA et force explicitement la caméra à se verrouiller sur le sol (mode Platformer) pendant la conversion.
```bash
python3 -m src.engine.conversion.cli gifs_SonicGameplay --auto-action --action-scene-type "platformer"
```

### 9. Mise à la corbeille automatique des mauvaises conversions
Lance une conversion par lot massive mais supprime automatiquement tout GIF résultant qui obtient un score de lisibilité LED inférieur à 60%.
```bash
python3 -m src.engine.conversion.cli --let-me-handle-it --reject-threshold 60
```
