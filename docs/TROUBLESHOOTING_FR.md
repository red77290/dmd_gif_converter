# Dépannage

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
| Aperçu LED Sim trop sombre / quadrillé | C'est normal — les écarts noirs simulent les espaces physiques entre LEDs. Désactivez **💡 LED Sim** pour l'aperçu classique |
| Canvas LED Sim très grand | Attendu pour les configs multi-dalle — le zoom 4× est plafonné à 640 px de large |
| Mode manuel montre la mauvaise zone | Augmenter d'abord le Zoom, puis ajuster les curseurs X/Y |
| Auto Action : « OpenCV not installed » | Lancer `pip install opencv-python onnxruntime` ou re-lancer `./launch_ui.sh` (installe automatiquement) |
| Aperçu Auto Action lent à apparaître | Normal — l'analyse IA prend quelques secondes par vidéo ; progression affichée dans le canvas AUTO ACTION |
| Résultat Auto Action incorrect | Essayer un autre **mode de détection** (`motion` ou `hybrid`) — le mode `person` fonctionne mieux avec des silhouettes humaines visibles |
| Sol non visible dans un jeu de plateformes 2D | Activer **Auto floor detect** dans les paramètres avancés Auto Action — il ancre la caméra au niveau du sol détecté |
| La caméra remonte pendant les sauts | Activer **Auto floor detect** — son EMA asymétrique résiste aux mouvements vers le haut pendant les phases aériennes |
| Auto floor detect ne montre toujours pas le sol | Augmenter **Bottom crop %** pour masquer le HUD/sol du détecteur principal, puis réactiver Auto floor detect |
| Smart Color Boost donne de mauvaises couleurs | Désactivez-le et réglez manuellement — fonctionne mieux sur du contenu mal exposé ou hétérogène |
| Smart Color Boost log affiche `fallback` | OpenCV non disponible — lancer `pip install opencv-python` |
| Le texte overlay n'apparaît pas | Vérifiez que **Text Content** n'est pas vide et que le fichier de police existe dans `media/fonts/` |
| `[ERROR] Font file '…' not found` | La police sélectionnée est absente de `media/fonts/` — choisir une autre police dans la liste |
| `[TEXT  ] … ffmpeg drawtext unavailable` | Normal sur macOS avec le ffmpeg Homebrew (compilé sans `--enable-libfreetype`) — **le fallback Pillow est utilisé automatiquement**, aucune action requise |
| Le bouton Recherche GIF est désactivé | Installez les dépendances manquantes : `pip install duckduckgo-search requests` (ou relancez `./launch_ui.sh`) |
| Recherche GIF : 0 résultat | DuckDuckGo peut limiter les requêtes rapides — patientez quelques secondes et réessayez |
| GIFs téléchargés très volumineux | Normal pour les GIFs web — le convertisseur les redimensionne automatiquement en 128×32 |
| Erreurs de timeout pendant le téléchargement | Certains hébergeurs d'images sont lents — augmentez la quantité (jusqu'à 300) pour compenser les URLs ignorées |
| Supprimer plusieurs GIFs en même temps | Maintenez **Ctrl** ou **Shift** puis cliquez pour multi-sélectionner, ensuite **Suppr** ou cliquer **✕ Remove** |
| Config par GIF : les params semblent se mélanger entre fichiers | Vérifiez que vous **cliquez** sur le nouveau fichier (la sauvegarde se déclenche sur l'événement de sélection) |
| Config par GIF : le toggle OFF revient aux mauvais params | Comportement attendu — il restaure l'état exact au moment du toggle ON, pas la config du GIF courant |
| Config par GIF : configs perdues après redémarrage | Les configs sont uniquement en session (RAM) — l'export n'est pas encore supporté |
| Smart Auto Crop donne de mauvais résultats | Désactivez-le et activez chaque option individuellement — utilisez `Auto bottom crop`, `Auto top crop`, `Auto floor detect` indépendamment |
| Smart Auto Crop n'active rien | Pas assez de détections dans le scan de 60 images — essayez un autre mode de détection (`motion` ou `hybrid`) |
| Visage coupé au niveau des épaules | Problème corrigé en v5.0.0 — mettez à jour vers la dernière version ; le moteur utilise désormais la détection au niveau du menton (20 % de la hauteur du corps) avec un rembourrage asymétrique |
| Auto Action échoue avec une source GIF | Corrigé en v5.0.0 — les GIFs sont maintenant pré-convertis via FFmpeg avant le traitement OpenCV pour éviter les problèmes de transparence BGRA |
| `[ACTION] … FFmpeg pipe encoding failed` | Consultez le message complet dans le log (stderr FFmpeg inclus désormais). Cause probable : GIF avec palette de transparence — mettez à jour vers v5.0.0 |
| "Let Me Handle It" grise des curseurs dont j'ai besoin | Désactivez-le pour récupérer le contrôle manuel complet — toutes les valeurs précédentes sont restaurées |
| "Let Me Handle It" activé mais Auto Action ne tourne pas | Vérifiez que OpenCV et onnxruntime sont installés (`pip install opencv-python onnxruntime`) |
