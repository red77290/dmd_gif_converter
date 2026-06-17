# AI Moments & Suivi Intelligent

![AI Moments Studio Timeline](../media/AI_MOMENT_PREVIEW.png)

DMD GIF Converter inclut une fonctionnalité avancée **AI Moments** conçue pour analyser automatiquement les longues vidéos et extraire les meilleurs moments pour vos écrans physiques DMD.

## Comment ça marche (Moteur Scoring V2)

Le moteur AI Moments effectue une analyse en plusieurs passes sur votre vidéo en utilisant le **Moteur Scoring V2**, qui sépare l'évaluation en domaines Temporels et Spatiaux :

1. **Détection de scènes** : Identifie les coupures et changements de plan via corrélation d'histogrammes pour éviter les sauts de caméra.
2. **Signaux Temporels** : Calcule des signaux purement mathématiques pour chaque image :
   - *Contraste* : Différence entre les zones claires et sombres.
   - *Entropie* : Complexité visuelle de l'image.
   - *Densité des contours* : Netteté et détails (gradient de Sobel).
   - *Mouvement* : Intensité du flux optique (Optical Flow).
3. **Évaluateur Spatial** : Évalue la lisibilité DMD, l'encombrement et la composition (utilise YOLO pour la détection du sujet).
4. **Pondération Stratégique** : Applique dynamiquement des poids en fonction de la stratégie choisie (`Action`, `Balanced`, `Character`, `Emotion`, `Epic`, `Custom`).
5. **Dédoublonnage par Signature Visuelle** : Calcule une empreinte visuelle pour chaque séquence candidate.
6. **Suppression des Non-Maxima (NMS)** : Classe les séquences et extrait les meilleurs moments sans chevauchement. Utilise les Signatures Visuelles pour rejeter agressivement les scènes visuellement similaires (garantissant ainsi la diversité de vos moments extraits).

## Stratégies IA Disponibles

Le moteur propose plusieurs stratégies intégrées pour correspondre à l'ambiance de votre vidéo :
- **Action** : Maximise le flux optique (mouvement). Idéal pour les combats, le sport et les séquences rapides.
- **Character** : Se concentre sur le sujet et les visages. Utilise le suivi YOLO avec un puissant "Biais de Centrage" pour verrouiller le personnage principal.
- **Emotion** : Privilégie les gros plans statiques et parfaitement centrés avec un minimum de mouvement. Parfait pour les dialogues intenses et les réactions faciales expressives.
- **Epic** : Équilibre un contraste élevé et des mouvements dynamiques pour créer des moments cinématiques dignes de bandes-annonces.
- **Balanced** : Un mélange équilibré de mouvement, de contraste et de visibilité du sujet.
- **Custom** : Déverrouille des curseurs avancés, vous permettant d'ajuster manuellement les poids exacts pour le Mouvement, le Contraste, la Densité des Contours, le Centrage du Sujet et l'Entropie.

## Optimisation des Performances

Le moteur AI Moments peut être très gourmand en CPU. Vous pouvez contrôler la vitesse d'analyse en ajustant le paramètre **Analyze FPS** :
- **FPS Bas** (ex: `2.0`) : Le moteur ignorera plus d'images. L'analyse sera significativement plus rapide, mais vous perdrez en précision sur les micro-mouvements.
- **FPS Haut** (ex: `10.0`) : Le moteur analyse plus d'images par seconde. Le résultat sera d'une précision chirurgicale, mais l'analyse sera beaucoup plus longue.
- **Par défaut** : `5.0` (analyse 1 image sur 5 sur une vidéo à 25 fps).

## Utilisation dans l'interface

1. Ouvrez une vidéo dans l'interface.
2. Allez dans l'onglet **AI Moments**.
3. Utilisez la **Studio Timeline** pour prévisualiser votre vidéo.
4. Cliquez sur **Generate AI Moments** pour extraire automatiquement les meilleures scènes, ou utilisez les boutons **[ Set IN ]** et **[ Set OUT ]** pour extraire manuellement un moment précis.
5. Les moments extraits manuellement ou par l'IA sont automatiquement ajoutés à votre liste de conversion !

### Studio Timeline & Lecture (Playback)
Vous pouvez utiliser le bouton **▶ Play Selection** pour lire en boucle infinie la sélection entre vos points IN et OUT. Cela vous permet de cadrer parfaitement vos coupes personnalisées avant de les extraire.

## Utilisation via CLI

Vous pouvez également automatiser l'extraction AI Moments depuis la ligne de commande :

```bash
# Analyse toutes les vidéos du dossier, extrait les 5 meilleurs moments par vidéo et les convertit en GIF DMD
./dmd_gif_converter.py mes_videos/ --ai-moments --ai-moments-count 5 --ai-w-action 100
```

## Magie du Texte (Animations)

Pour accompagner vos AI Moments, vous pouvez ajouter des superpositions de texte avec des animations intégrées !
- Allez dans les paramètres **Text Overlay** (le bouton "T").
- Choisissez votre texte, couleur et police.
- Choisissez une **Magic Animation** :
  - `none` : Texte statique.
  - `blink` : Clignotement d'arcade classique.
  - `scroll_left` : Le texte défile doucement de droite à gauche.
  - `scroll_up` : Le texte défile de bas en haut.

L'animation du texte est appliquée directement sur le rendu final du DMD, ce qui signifie que vous pouvez l'ajuster instantanément sans avoir à relancer le lourd processus de suivi par IA.
