# Manuel CLI & Paramètres

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
| `dither` | `--dither` | `none` | Recommandé `none` pour le contenu défilant |

### Sortie & Logs
| Paramètre | Flag | Par défaut | Description |
|-----------|------|---------|-------------|
| `log-level` | `--log-level` | `WARNING` | Définit le niveau de log (DEBUG, INFO, WARNING, ERROR). Par défaut WARNING (affiche la barre de progression). |
| `verbose` | `--verbose` / `-v` | `False` | Alias pour `--log-level DEBUG`. Affiche les logs détaillés de FFMPEG. |

### Extraction AI Moments

| Paramètre | Flag | Défaut | Description |
|-----------|------|---------|-------------|
| `ai_moments` | `--ai-moments` | `False` | Extrait automatiquement les meilleurs moments des vidéos avant la conversion. |
| `ai_moments_count` | `--ai-moments-count` | `10` | Nombre maximum de moments à extraire par vidéo. |
| `ai_moments_strategy` | `--ai-moments-strategy` | `Balanced` | Stratégie à prioriser (`Action`, `Balanced`, `Character`). |
| `ai_moments_dur_min` | `--ai-moments-dur-min` | `2.0` | Durée minimale d'un moment extrait en secondes. |
| `ai_moments_dur_max` | `--ai-moments-dur-max` | `5.0` | Durée maximale d'un moment extrait en secondes. |

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
| `action_detector` | `person` | `person` · `motion` · `hybrid` · `center` |
| `action_intro` | `1.5` | Durée du plan large d'introduction en secondes |
| `action_strength` | `0.65` | Force de zoom autour du sujet |
| `action_auto_strength` | `False` | Force automatique basée sur le contenu |
| `action_smoothness` | `0.65` | Lissage exponentiel de la caméra |
| `action_auto_smoothness`| `False` | Lissage automatique basé sur le contenu |
| `action_zoom_max` | `1.8` | Facteur de zoom IA maximum |
| `action_padding` | `0.20` | Marge autour du ROI détecté |
| `bg_sub_enable` | `False` | Remplace le fond par du noir (maximise le contraste du sujet) |
| `action_bottom_crop` | `0.0` | Exclut les N % inférieurs du cadre (manuel, 0 = désactivé) |
| `action_auto_bottom_crop` | `False` | Détecte auto la limite basse du sujet (pieds / sol) |
| `action_top_crop` | `0.0` | Exclut les N % supérieurs du cadre (manuel, 0 = désactivé) |
| `action_auto_top_crop` | `False` | Détecte auto la limite haute du sujet (tête / ciel) |
| `action_vertical_bias` | `0.0` | Décalage vertical manuel de la caméra (`+1.0` = sol, `-1.0` = plafond) |
| `action_auto_vertical_bias` | `False` | Suivi automatique du sol — EMA asymétrique, écrase le bias manuel |
| `action_smart_auto_crop` | `False` | 🧠 Smart Auto Crop — moteur analyse 60 images et active la combinaison optimale via 3 groupes mutuellement exclusifs ; résout la contradiction face-priority ↔ floor-tracking |
| `let_me_handle_it` | `False` | 🚀 Laisse-moi gérer ça — mode tout-automatique : active Smart Color Boost + Auto Action + Smart Auto Crop + Soustraction de fond + DMD Visibility Score et grise tous les réglages non pertinents |
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
