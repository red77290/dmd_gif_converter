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
3. Cliquez sur "Generate Best Moments".
4. Le système analysera la vidéo (cela peut prendre quelques minutes pour les longues vidéos).
5. Une liste des moments les mieux classés apparaîtra. Cliquez sur un moment pour le prévisualiser instantanément et le convertir !

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
