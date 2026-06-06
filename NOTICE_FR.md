# DMD GIF Converter - Manuel Utilisateur

Bienvenue dans le DMD GIF Converter ! Cet outil convertit automatiquement vos vidéos, GIF et images en séquences ultra-optimisées pour les écrans matrices LED basse résolution (comme les DMD de flipper ou les panneaux LED).

## Notre Philosophie

Lors de la conversion de vidéos vers de très basses résolutions (par ex. 128x32 ou 256x64), le plus important est la **lisibilité**. Un algorithme de tracking 4K parfait ne sert à rien si le sujet est trop petit pour être reconnu sur un écran pixelisé. Notre moteur est conçu pour se concentrer sur l'action, stabiliser le cadrage, et garantir un rendu exceptionnel sur votre matrice LED.

## Fonctionnalités Principales

1. **Smart Auto Crop** 🤖 : Analyse la vidéo pour déterminer s'il faut suivre le visage d'un personnage, s'ancrer au sol (pour les jeux de plateforme), ou ignorer le ciel.
2. **Mode Platformer** 🎮 : Spécialement calibré pour les jeux 2D à défilement horizontal (Mario, Sonic, Metroid). Il verrouille le sol en bas de l'écran et anticipe la direction du personnage de manière fluide.
3. **Tracking d'Action** 🏃 : Utilise une IA légère (YOLO) combinée à la détection de mouvement pour suivre le sujet sans faille.
4. **Score de Visibilité et Lisibilité DMD** 👁️ : Le moteur teste plusieurs options de recadrage en interne et choisit celle qui offre le meilleur contraste, la meilleure séparation des formes et la taille idéale pour votre résolution LED exacte.
5. **Auto Tuning & Debug** 🛠️ : Si un recadrage semble incorrect, vous pouvez activer le dataset de debug pour voir exactement ce que le moteur analyse.

## Démarrage Rapide (Ligne de commande)

Pour convertir simplement une vidéo avec les meilleurs paramètres automatiques :

```bash
python main.py input.mp4 --smart-crop --platformer
```

### Options Importantes
- `--smart-crop` : Laisse le moteur décider de la meilleure façon de cadrer la vidéo.
- `--platformer` : À utiliser pour les jeux 2D afin de maintenir le niveau du sol.
- `--look-ahead 0.25` : Permet à la caméra d'anticiper le mouvement du personnage en regardant légèrement devant lui.
- `--detect hybrid` : Combine le tracking IA (personnes) avec le tracking de mouvement pour un résultat optimal.
- `--intro-duration 1.5` : Affiche la scène entière pendant 1,5 seconde avant de zoomer sur l'action.

## Dépannage

- **La caméra tremble trop !** 
  Augmentez la fluidité : `--smoothness 0.95`
- **Ça n'arrête pas de zoomer sur des mouvements parasites en arrière-plan.**
  Utilisez une limite de confiance plus élevée : `--roi-conf 0.4`
- **Je joue à un jeu de combat et ça ne suit qu'un seul joueur !**
  Assurez-vous que la fusion multiple est activée (elle l'est par défaut en mode smart).

Pour une configuration plus avancée, vous pouvez modifier directement le script ou passer des arguments supplémentaires au pipeline décrits dans la documentation développeur.
