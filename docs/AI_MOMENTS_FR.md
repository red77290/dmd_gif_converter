# AI Moments & Suivi Intelligent

DMD GIF Converter inclut une fonctionnalité avancée **AI Moments** conçue pour analyser automatiquement les longues vidéos et extraire les meilleurs moments pour vos écrans physiques DMD.

## Comment ça marche

Le moteur AI Moments effectue une analyse en plusieurs passes sur votre vidéo :

1. **Détection de scènes** : Identifie les coupures et changements de plan pour éviter les sauts de caméra.
2. **Détection de sujets** : Utilise l'IA (basé sur YOLO ou ONNX) pour trouver les visages, les personnes et les objets.
3. **Analyse de mouvement** : Évalue la quantité d'action dans la scène.
4. **Prédiction de la qualité DMD** : Simule la mise à l'échelle 128x32 et évalue le contraste, la lisibilité et l'encombrement.
5. **Classement** : Classe les scènes en fonction de l'action, de la visibilité et de la durée.

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
./dmd_gif_converter.py mes_videos/ --ai-moments --ai-moments-count 5 --ai-moments-strategy Action
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
