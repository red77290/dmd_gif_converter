# DMD GIF Converter — Historique des versions (Changelog)

## Nouveautés de la v6.2.0
- **📊 Matrice de Score Continue** : La détection de scène (Auto Action) ne repose plus sur un arbre en cascade rigide. Elle utilise désormais une matrice de score dynamique et continue pour identifier le profil de caméra optimal (ex: Platformer, Talking Closeup, Action). Le tableau des scores est désormais entièrement visible dans les logs de l'interface.
- **🛡️ Détecteur de Secours Auto (Person → Hybrid)** : Lors du suivi de contenus mixtes, si le détecteur principal `person` échoue sur un très gros-plan ou un sujet non-humain, le moteur peut désormais basculer instantanément sur le détecteur `hybrid` en plein milieu d'une scène ou lors du pré-scan, garantissant un suivi cinématique parfait sans jamais abandonner.
- **🎯 Correction Matrice `FIGHTING_2D`** : Correction d'un problème où la matrice de score favorisait trop lourdement le préréglage `fighting_2d` pour les scènes de films où un personnage de taille normale se déplace horizontalement, au lieu de choisir `action_moving` ou `full_body_tall`.
- **🏷️ Logs Sémantiques de Colorimétrie** : Smart Color Boost ajoute maintenant des tags sémantiques directement dans les logs de l'interface (ex: `[Dark + Low Contrast]`, `[Vivid]`) pour vous indiquer exactement comment l'IA perçoit votre vidéo.
- **🛡️ Suppression Stderr Thread-Safe** : Correction d'un bug de concurrence critique où de multiples conversions parallèles redirigeaient définitivement la sortie terminal de l'application vers `/dev/null`. La suppression du `stderr` C-level est désormais parfaitement protégée par un `threading.Lock`.
- **📝 Interception des Logs UI** : Les appels `logger.info()` du moteur (qui contournaient l'UI et s'imprimaient directement dans le terminal) ont été consolidés dans le payload final de conversion. Cela garantit que tous les raisonnements et matrices de scores d'Auto Action apparaissent parfaitement dans le panneau de logs de l'application.

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
