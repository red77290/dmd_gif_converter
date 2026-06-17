# DMD GIF Converter — Historique des versions (Changelog)

## [V7.1.0] - 2026-06-17 (AI Moments V2, Thread Safety, Refonte UI, Tests)
### Corrigé
- **Scoring AI Moments** : Restauration de l'intégration complète des sliders de l'interface (`w_action`, `w_character`, `w_epic`, `w_dmd`, `w_loopable`). Le moteur construit désormais dynamiquement sa stratégie de score (`ScoringStrategy`) pour correspondre aux paramètres de l'utilisateur plutôt que d'utiliser un preset codé en dur, ce qui permet de pénaliser explicitement les textes/génériques.
- **Race Conditions de la Preview DMD** : Correction d'un problème critique de multithreading où le passage rapide d'une vidéo à l'autre poussait les processus FFmpeg en arrière-plan à écraser l'état de l'interface avec "Error opening input files". Remplacement des interruptions `threading.Thread` par des jetons d'ID de génération (`_dmd_gen_id`).
- **Vitesse d'extraction AI Moments** : Restauration de l'extraction instantanée des moments vers les fichiers temporaires grâce à l'utilisation correcte de la copie de flux (`-c copy`) et du fast-seek (`-ss` placé avant `-i`).


### Ajouté
- **Auto Fast Tracking** : Nouvelle fonctionnalité d'optimisation des performances qui ajuste dynamiquement le sous-échantillonnage de suivi YOLO en fonction du framerate (FPS) de la vidéo. Cible ~5 inférences par seconde pour réduire drastiquement la charge CPU sur les gros fichiers 60fps/120fps. Activé par défaut avec le mode "Let me handle it".
- **Nouvelles stratégies AI Moments** : Ajout des stratégies `Emotion` (focus sur les gros plans statiques hyper-centrés pour les dialogues intenses) et `Epic` (mouvement cinématique à fort contraste).
- **Dédoublonnage NMS par Signature Visuelle** : AI Moments calcule désormais une empreinte visuelle active des scènes extraites. Les scènes extrêmement similaires sont supprimées pour garantir une grande diversité visuelle (particulièrement critique pour la stratégie `Emotion` qui favorise les plans fixes).
- **Biais de centrage YOLO** : Ajout d'un multiplicateur de distance dynamique aux scores de détection YOLO pour privilégier lourdement les sujets centrés dans l'image par rapport aux personnages secondaires en bordure.
- Infobulles exhaustives pour tous les paramètres de l'interface utilisateur dans Conversion Settings et Advanced Settings.
- Verrouillage visuel dans les Paramètres Avancés : Les sliders manuels (Zoom, X/Y Offset) et les paramètres de défilement (Scroll) sont automatiquement grisés et désactivés lorsque l'Auto Action est activée.

### Corrigé
- **Cadrage du visage YOLO & Coupe au niveau de la tête** : Correction d'un bug critique dans `talking_closeup` où le tracker appliquait une chute verticale de 25% codée en dur, coupant les têtes. Il respecte désormais correctement le `face_head_frac` configuré (0.40 pour les détections de personnes standard) garantissant que les yeux restent parfaitement alignés dans le tiers supérieur de l'image.
- **Interface du panneau AI Moments** : Correction de la disposition de la grille responsive et du chevauchement des curseurs lors de l'activation de la stratégie 'Custom'.
- **Scoring AI Moments** : Restauration de l'intégration complète des sliders de l'interface (`w_action`, `w_character`, `w_epic`, `w_dmd`, `w_loopable`). Le moteur construit dynamiquement sa stratégie de score (`ScoringStrategy`) pour correspondre aux paramètres de l'utilisateur, ce qui permet de pénaliser explicitement les textes/génériques.

### Refactorisé
- `PreviewPanel` entièrement restructuré dans une architecture MVC modulaire :
  - `PreviewPanel` : Agit en tant que conteneur de disposition global.
  - `PreviewPlayer` : Gère le chargement des médias, le cache, et le rendu du simulateur LED Matrix.
  - `PreviewControls` : Isole tous les widgets de l'interface, boutons et barres de progression.

### Tests & Stabilité
- **✅ 100% de réussite aux tests** : Résolution de tous les crashs de la suite de tests (notamment le `SIGABRT` macOS causé par la concurrence entre Tkinter et OpenCV) grâce à un mocking complet de Tkinter dans `conftest.py`.
- **✅ 53% de Couverture de code** : Vérification que la logique du pipeline central et de l'auto-action est couverte, avec 455 tests passant avec succès au total.

### Modifié
- **🚀 Restauration du Multithreading Massif** : La conversion de masse (batch processing) utilise de nouveau un pool de workers (`concurrent.futures.ThreadPoolExecutor`), réduisant massivement le temps de traitement pour les gros répertoires.
- **🚀 Allocation Intelligente des Cœurs (Auto-Workers)** : Par défaut, l'application analyse désormais votre processeur et réserve une marge de sécurité (`max(1, min(16, os.cpu_count() // 2))`) pour empêcher le PC de figer pendant les lourdes conversions.
- **🚀 Optimisation de l'UX des conversions parallèles** : Résolution d'un problème d'affichage où les conversions en parallèle (dossier ou liste) semblaient s'exécuter de manière séquentielle, car le prétraitement OpenCV/YOLO s'exécutait en arrière-plan sans retour visuel. Ajout de rapports de progression image par image via un callback dans `preprocess_video_for_dmd` et correction d'une incohérence de signature dans `ConversionController`.
- **🚀 Correction du profil `FIGHTING_2D`** : Restauration de `fighting_2d` avec l'activation de `platformer_mode=True` pour éliminer le bug d'ancrage de la caméra. Les jeux de combat restent désormais cloués au sol comme les jeux de plateforme.
- **🚀 Résolution du bug de ciblage de plateforme** : Le profil `platformer` ignore désormais les blocs flottants (fausses détections géantes), tandis que le profil `fighting_2d` décale naturellement la caméra vers le haut pour garantir que la tête des personnages géants reste visible. La matrice de scoring différencie désormais parfaitement les deux genres.
- **🚀 Protection contre les faux plafonds** : YOLO ne peut plus confondre les blocs du plafond avec le joueur. Le détecteur rejette désormais les détections dans les 40% supérieurs de l'écran lors de l'initialisation du sol, et ignore les sauts verticaux impossibles (>50% de l'écran).
- **🚀 Faux positifs `WIDE_SHOT` corrigés** : Les jeux avec une caméra de suivi parfaite (variance quasi-nulle) ne sont plus pénalisés et pris à tort pour des plans larges cinématiques ou des menus statiques.
- **🚀 Parité Globale des Logs** : Intégration d'un système de log unifié via `EventBus` qui réplique parfaitement les logs terminaux dans l'UI `LogConsole` (y compris les décisions internes de l'Auto-Action) en temps réel.
- **🚀 Cache des Décisions (Bypass)** : L'application récupère désormais correctement le fichier `_decision.json` préexistant lors du bypass d'une vidéo déjà traitée, affichant la matrice de décision dans la console sans avoir besoin de relancer l'inférence YOLO.
- **🚀 UI Log Console Améliorée** : La console de log intégrée dans l'interface est désormais 3 fois plus grande par défaut (hauteur augmentée de 90px à 250px) pour une meilleure lisibilité.
- **🚀 Correction Zoom LED (Simulateur)** : Résolution d'un saut de taille ("zoom in") indésirable sur la prévisualisation vidéo lors de l'activation/désactivation du mode LED Simulator.
- **🚀 Bug de Performance AI Moments (YOLO)** : Correction d'une régression du moteur Scoring V2 où le détecteur YOLO était exécuté sur toutes les frames même lorsque l'option "Character" était désactivée, ralentissant l'extraction. La vitesse a été restaurée x10.
- **🚀 AI Moments Progress Bar** : Ajout d'une barre de progression ASCII (`[█████████-------] 50%`) propre dans les logs de l'UI pour suivre l'extraction temporelle tous les 5% sans spammer la console.
- **🚀 Protection Crash Tkinter (AI Moments)** : Sécurisation de la mise à jour de la progression asynchrone pour éviter un crash `_tkinter.TclError` si l'utilisateur ferme la popup AI Moments en cours de route.

## [7.1.0] - Architecture & Performances (V7)
- **🚀 Architecture Refactorisée (MVC)** : Découpage complet du monolithe `preview_panel.py` vers un modèle MVC propre avec `main_panel.py` et des contrôleurs dédiés (`SourceController`, `AutoController`, `DmdController`). Cela améliore la maintenance sans impacter l'expérience utilisateur.
- **🚀 Threads ONNX Dynamiques** : Les threads YOLO s'adaptent désormais au contexte ! L'allocation passe instantanément à 2 threads pour les batchs (pour éviter la saturation du CPU) et à 8 threads pour l'Auto Action autonome ou les AI Moments, offrant un gain de temps massif.
- **🚀 Scoreboard Visuel AI Moments** : Amélioration des logs terminaux d'AI Moments avec des métriques détaillées, des moyennes de frames, de la stabilité, du jitter, le tout dans un format tabulaire clair.
- **🚀 Universal FFmpegPipeReader** : Remplacement de toutes les instances bloquantes de `cv2.VideoCapture` par le nouveau `FFmpegPipeReader` accéléré matériellement. Cela supprime tous les freezes sur l'ensemble de l'application (Batch, Auto Tracking, UI Previews).
- **🚀 Accélération Matérielle** : Détection et intégration automatique des encodeurs matériels (`h264_videotoolbox` pour macOS Apple Silicon, `h264_nvenc` pour NVIDIA, `h264_qsv` pour Intel) via `hardware_accel.py`, améliorant drastiquement les vitesses d'encodage H.264.
- **🚀 Correction Crash OpenCV (macOS)** : Résolution d'un crash critique `SIGABRT`/`SIGSEGV` lors de l'utilisation de `cv2.VideoCapture` avec de multiples threads (8 workers) en implémentant un Monkey Patch `SafeVideoCapture` avec un verrouillage global (`threading.Lock`).
- **🚀 Épuisement des Threads ONNX** : Limitation globale du nombre de threads utilisés par `onnxruntime` (`intra_op_num_threads=2`, `inter_op_num_threads=1`) pour éviter l'épuisement du CPU et les freezes système en mode batch "Convert All".
- **🚀 Previews UI Instantanées** : Élimination complète du gel de la boucle principale Tkinter lors du redimensionnement de l'interface graphique en passant de l'algorithme `Image.LANCZOS` à `Image.BILINEAR`.
- **🚀 Génération de Previews Chaînée** : Correction d'un bug où cliquer sur un fichier lançait l'analyse Auto-Action YOLO deux fois simultanément. La vue DMD attend désormais intelligemment que la vue Auto-Action ait terminé de générer son cache `action_pre.mp4` pour contourner totalement YOLO.
- **🚀 Previews Limitées dans le Temps** : Imposition d'un plafond strict de 10 secondes maximum pour la génération des previews Auto-Action et DMD. Sélectionner une longue vidéo ne fige plus l'application en traitant des milliers d'images inutilement.
- **🚀 Déblocage des Paramètres "Let me handle it"** : Les paramètres purement esthétiques ("Intro panoramic", "ROI padding", "Background Subtraction") ont été libérés du verrouillage automatique intelligent. L'option "Intro panoramic" est fixée à 0.0s par défaut.
- **🚀 Identification des Workers (Logs)** : Ajout d'étiquettes de préfixe de thread (`[W1]`, `[W2]`, etc.) via `WorkerFormatter` dans les logs UI pour suivre facilement les conversions concurrentes, et suppression du filtre de déduplication.
- **🚀 Correction KeyError (Scènes Dynamiques)** : Correction d'une erreur dans `AiMomentsScorer` où les transitions dynamiques de scène échouaient à injecter correctement le nom du profil de la scène, causant des exceptions de clés `None`.
- **🚀 Correction de la classification des gros plans Anime** : Les gros plans animés et dynamiques (comme dans `visage_anime_1.gif`) étaient incorrectement classés en `TOP_DOWN_ISOMETRIC`. Nous avons introduit un sol effectif (`effective_floor_in_lower`) pour éviter que les sujets géants ne déclenchent de fausses pénalités de sol, assoupli les critères d'aspect ratio pour les très grands sujets gros plans, et pénalisé inconditionnellement `TOP_DOWN_ISOMETRIC` lorsque le sujet occupe plus de 30% de l'image.
- **🚀 Résolution du crash UnboundLocalError de repli** : Correction d'une exception lors du scan de vidéos sans aucune détection, causée par l'utilisation de la variable `_auto_scene` avant sa définition.
- **🚀 Découplage des importations circulaires** : Importation paresseuse (lazy import) de `available_detectors` dans le fichier `src/engine/auto_action/__init__.py` pour permettre le lancement isolé de tests unitaires sur des modules précis sans erreurs de dépendances circulaires.
- **🚀 Correction de la Dérive Letterbox** : Intégration des limites de rognage de la letterbox directement dans les propriétés de la fenêtre de suivi du moteur de tracking, empêchant la caméra de dériver dans les bandes noires (résolvant la coupure des yeux sur des personnages comme Doc/Marty dans Retour vers le Futur).
- **🚀 Bouton de Mode de Contenu Toujours Actif** : Le menu déroulant du "Mode de contenu" reste désormais utilisable même lorsque le Smart Color Boost (mode IA auto-colorimétrie) ou "Laisse-moi gérer ça" (Let me handle it) est activé. Cela permet à l'utilisateur de spécifier le genre du contenu (par exemple, anime) pour adapter le recadrage automatique des visages, tout en bénéficiant de l'optimisation colorimétrique automatique.
- **🏗️ Typage Strict** : Remplacement des tuples primitifs par `NamedTuple` (`CamRect`, `BoundingBox`) pour éviter les erreurs d'indexation.
- **🏗️ Composition UI** : Suppression des Mixins (anti-pattern God Object) au profit d'une Composition stricte des panneaux graphiques.
- **⚡ Pipeline E/S Asynchrone** : Refonte de `preprocess_video_for_dmd` utilisant des `queue.Queue` Producteur/Consommateur, parallélisant OpenCV, YOLO, et FFmpeg dans des threads séparés.
- **🧠 FPS Configurable (IA)** : La résolution temporelle du scoring dans `ai_moments.py` n'est plus fixée à 2.0 FPS, grâce au nouveau paramètre configurable `analyze_fps`.

## Nouveautés de la v7.0.0
- **🧠 Moteur Scoring V2** : Une réécriture complète du système de score mathématique. AI Moments évalue désormais les signaux temporels purs (Contraste, Entropie, Densité des contours, Mouvement) séparément de la composition spatiale (Lisibilité, Encombrement), puis applique des poids stratégiques dynamiques (`Action`, `Balanced`, `Character`). Cela améliore massivement la fiabilité des moments extraits.
- **🔬 Lanceur A/B Testing** : Ajout d'une interface CLI dédiée `ab_runner.py` et d'un panneau UI A/B Testing pour comparer directement le Scoring V1 et le Scoring V2 sur des dossiers vidéo complets. Génère des rapports Markdown détaillés.
- **👁️ Cadrage Cinématique Règle des Tiers** : Affinement des mathématiques du tracker Auto Action pour les gros plans. Il ignore désormais les 25% supérieurs de la boîte de détection (cheveux/front) et cible spécifiquement les 35% suivants (visage). Nous avons également restauré la limite de sécurité verticale (`cy = min(cy, y + 0.25 * crop_h)`) dans le constructeur de caméra, empêchant le cadrage de descendre sous le regard et de commencer au niveau du nez, garantissant un cadrage optimal sur les matrices d'affichage ultra-courtes en 4:1.
- **🏗️ Architecture Pipeline du Tracker** : La méthode monolithique `TrackingEngine.process_frame()` a été entièrement refondue vers un modèle Pipeline (Chaîne de Responsabilité) parfaitement découplé. Elle exploite 12 étapes modulaires indépendantes (`DetectionStage`, `FaceClippingStage`, `LookAheadStage`, etc.) interconnectées par un contexte fortement typé (`FrameTrackingContext`).
- **📝 Balises de Log Dynamiques** : Le moteur émet maintenant des balises de log `[DYNAMIC]` en temps réel, permettant aux utilisateurs de surveiller les coupes de caméra et les transitions de profil de la Matrice de Score Continue directement dans le panneau de logs de l'interface.

## Nouveautés de la v6.3.0
- **📊 Matrice de Score Continue** : La détection de scène (Auto Action) ne repose plus sur un arbre en cascade rigide. Elle utilise désormais une matrice de score dynamique et continue pour identifier le profil de caméra optimal (ex: Platformer, Talking Closeup, Action). Le tableau des scores est désormais entièrement visible dans les logs de l'interface.
- **🛡️ Détecteur de Secours Auto (Person → Hybrid)** : Lors du suivi de contenus mixtes, si le détecteur principal `person` échoue sur un très gros-plan ou un sujet non-humain, le moteur peut désormais basculer instantanément sur le détecteur `hybrid` en plein milieu d'une scène ou lors du pré-scan, garantissant un suivi cinématique parfait sans jamais abandonner.
- **🎯 Correction Matrice `FIGHTING_2D`** : Correction d'un problème où la matrice de score favorisait trop lourdement le préréglage `fighting_2d` pour les scènes de films où un personnage de taille normale se déplace horizontalement, au lieu de choisir `action_moving` ou `full_body_tall`.
- **🏷️ Logs Sémantiques de Colorimétrie** : Smart Color Boost ajoute maintenant des tags sémantiques directement dans les logs de l'interface (ex: `[Dark + Low Contrast]`, `[Vivid]`) pour vous indiquer exactement comment l'IA perçoit votre vidéo.
- **🛡️ Suppression Stderr Thread-Safe** : Correction d'un bug de concurrence critique où de multiples conversions parallèles redirigeaient définitivement la sortie terminal de l'application vers `/dev/null`. La suppression du `stderr` C-level est désormais parfaitement protégée par un `threading.Lock`.
- **📝 Interception des Logs UI** : Les appels `logger.info()` du moteur (qui contournaient l'UI et s'imprimaient directement dans le terminal) ont été consolidés dans le payload final de conversion. Cela garantit que tous les raisonnements et matrices de scores d'Auto Action apparaissent parfaitement dans le panneau de logs de l'application.
- **✂️ Correction de l'Amputation du Corps** : Correction d'un bug critique dans `analysis.py` où le pré-recadreur tronquait artificiellement la boîte de détection aux 28% supérieurs pour signaler le mode face-priority. L'optimiseur intelligent a mal interprété cette fausse boîte comme les vraies limites du sujet et a définitivement recadré le corps entier avant même le début du suivi. Le pré-recadreur préserve désormais la boîte complète, laissant le zoom dynamique au moteur de suivi.
- **🔗 Correction d'Injection du Profil** : Correction de la cause racine du zoom excessif sur les cheveux. `analyzer.py` n'injectait jamais le `scene_profile` détecté dans l'instance `AutoActionConfig` passée au moteur de tracking. À cause de ce lien manquant, le tracker ne pouvait pas accéder aux offsets personnalisés et retombait sur ses valeurs par défaut (10% de hauteur corporelle). L'analyseur copie désormais explicitement `scene_profile` dans la configuration, reliant correctement l'analyse au suivi.
- **⚔️ Correction de la Décapitation en Combat** : Correction d'un bug où les scènes de combat anime (`combat_anime.gif`) étaient mal classées en `TALKING_CLOSEUP`. Le classificateur prenait la très large boîte englobante (couvrant les deux combattants) pour un grand visage unique. Cela forçait le mode de suivi `closeup`, qui coupait brutalement les 25% supérieurs de l'image (les prenant pour des cheveux). Ajout d'une pénalité dans `scene_types.py` pour que les très larges ratios d'aspect (`< 0.85`) ne déclenchent plus ce mode, permettant le repli vers `FIGHTING_2D` ou `PLATFORMER` qui encadrent tout le corps.

## Nouveautés de la v6.1.0
- **🎯 Correction détection visage en gros plan** : Le tracker auto-action identifie désormais correctement les gros plans (`roi_h > 40 % de la hauteur de frame`) et ignore les 25 % supérieurs de la bounding-box (cheveux) pour verrouiller la région des yeux — élimine la dérive de caméra sur contenu anime.
- **📸 Correction caméra face-priority** : Corrige un bug de calcul dans `face_priority_mode` (camera.py) où `cy` était placé ~300 px sous le visage (utilisation de la hauteur de crop au lieu de la hauteur de la ROI). La caméra reste maintenant verrouillée sur la région des yeux.
- **🔇 Suppression des messages C-level stderr** : Les messages OpenCV `[mp3float @ ...] Header missing` (qui contournent le logging Python et écrivent directement sur le file-descriptor 2) sont désormais réduits au silence via un gestionnaire de contexte `_quiet_c_stderr()` utilisant `os.dup2`.
- **📐 Corrections de mise en page UI** : La preview DMD n'écrase plus les previews Source/Auto (suppression du `weight=1` sur la mauvaise ligne). Le panneau de log ne cache plus les boutons Convert et Generate AI Moment.
- **🚌 Découplage EventBus** : Les événements `FILES_ADDED_TO_QUEUE`, `PREVIEW_SOURCE_CHANGED` et `PREVIEW_REFRESH_REQUESTED` découplent maintenant complètement AI Moments → Panneau gauche et Panneau central → Panneau preview.
- **🔤 Nettoyage du code** : Tous les commentaires du code source traduits du français vers l'anglais.
- **🧪 Couverture de tests étendue** : Nouveaux fichiers de tests — `test_tracker_closeup.py` (8 tests), `test_camera.py` (18 tests, réécriture complète), `test_event_bus_integration.py` (13 tests) — couvrant chaque bug corrigé dans cette version.

## Nouveautés de la v6.0.0
- **🤖 AI Iconic Moments** : Un tout nouvel onglet dédié pour analyser automatiquement des vidéos entières et extraire les meilleurs "moments" en utilisant des critères avancés (Action, Cuts épiques, Présence de personnages, Bouclage parfait, et Visibilité DMD). Il offre même un bouton magique pour envoyer instantanément le moment découvert vers le Convertisseur ! [Lisez le guide complet ici.](AI_MOMENTS_FR.md)
- **🎬 Studio AI Moments & Extraction CLI** : Mise à jour majeure du moteur AI Moments. Intégration d'une Timeline Studio interactive avec points IN/OUT et lecture en boucle. Parité totale avec la CLI grâce au flag `--ai-moments`.
- **🪄 Magie du Texte (Text Overlay)** : Ajout du support complet des superpositions de texte (Polices, Styles, Arrière-plan) avec des animations intégrées (`blink`, `scroll_left`, `scroll_up`) directement dans l'interface graphique.

## Nouveautés de la v5.1.0
- **🧩 Modularité Générique Étendue** : L'architecture modulaire de l'application (interfaces pour le Convertisseur, Tracker, Détecteur) s'étend désormais au moteur de recherche de GIFs. Une interface générique `ISearchEngine` orchestre DuckDuckGo, Tenor, et Giphy de façon transparente sans duplication de code, garantissant une réutilisabilité et extensibilité maximales pour l'UI et les scripts utilitaires.

## Nouveautés de la v5.0.0
- **🏗️ Refonte Architecturale** : Séparation des scripts monolithiques en un paquet `src/` modulaire (`auto_action`, `converter`, `ui`) pour faciliter le débogage et la maintenance.
- **🤖 Let me handle it** : Implémentation du système de score de visibilité pour un cadrage optimal.
- **👁️ DMD Quality Scoring & Gestion Intelligente** : L'interface sépare désormais les fichiers en attente des fichiers convertis. Chaque GIF généré reçoit un Score de Qualité (0-100%). Utilisez l'**Assistant de Nettoyage (Cleanup Assistant)** pour supprimer instantanément les mauvaises conversions !

## Nouveautés de la v4.0.0
- **🏗️ UI et Moteur Modulaires** : Refonte de l'interface graphique utilisant des Mixins à héritage multiple pour un code plus propre.
- **🎥 Suivi Fluide** : Correction des tremblements de caméra en lissant les sauts d'anticipation et en préservant le suivi X/Y lorsque le score de visibilité échoue.

## Nouveautés de la v3.1.0
- **🔍 Recherche de GIFs Étendue** : Augmentation de la limite de quantité de recherche de GIFs à 300.
- **🔄 Actualisation des Dossiers** : Ajout de la fonctionnalité de rafraîchissement des dossiers pour réanalyser et mettre à jour les fichiers dans l'UI sans redémarrer.

## Nouveautés de la v3.0.0
- **🌐 Recherche de GIFs Intégrée** : Introduction de la recherche pour télécharger des GIFs depuis DuckDuckGo, Tenor et Giphy directement depuis l'interface.
- **🚥 Simulation LED** : Ajout de la simulation de pixels LED pour la prévisualisation DMD, avec option pour voir exactement le rendu sur le matériel.

## Nouveautés de la v2.1.0
- **📐 Recadrage Avancé** : Ajout des fonctionnalités de recadrage automatique pour les limites supérieures et inférieures de la caméra d'action.
- **⚙️ Configuration Par-GIF** : Implémentation de la configuration indépendante par fichier dans la liste de traitement par lots.

## Nouveautés de la v2.0.0
- **🪄 Magie du Texte** : Ajout du support pour la superposition de texte directement lors de la conversion GIF.
- **🎨 Smart Color Boost** : Implémentation du Smart Color Boost pour l'analyse colorimétrique gérée par l'IA, améliorant considérablement les scènes sombres.
- **👤 Soustraction d'Arrière-plan** : Ajout du support pour supprimer les arrière-plans.

## Nouveautés de la v1.0.0
- **🚀 Lancement Initial** : Moteur de conversion de base, interface graphique, profils de colorimétrie HUB75, défilement ping-pong, et protections anti-transparence.
