# Démarrage Rapide : Let's Start

Bienvenue dans le DMD GIF Converter. Cet outil permet de convertir très facilement des dossiers de vidéos en GIFs de 128x32 pixels optimisés pour les dalles LED.

## 🖥️ 1. Utilisation de l'Interface Graphique (GUI)

Pour lancer l'interface graphique :
- **Windows** : Double-cliquez sur `launch_ui.bat`
- **Mac/Linux** : Lancez `./launch_ui.sh`

### Le workflow "Zéro Config" ultime :
1. Regardez en haut à droite de l'application (dans le panneau `⚙️ Paramètres`).
2. Cochez la case **`🚀 Let Me Handle It ✓`**.
   *(Cela active instantanément les 5 moteurs IA : Auto-Action, Recadrage Intelligent, Auto-Colorimétrie, Soustraction de fond et Score DMD).*
3. Assurez-vous que **`Workers`** est réglé sur un chiffre élevé (ex: `8` si vous avez un PC récent) pour convertir les fichiers beaucoup plus vite.
4. Réglez le curseur **`Assistant de Nettoyage (Cleanup)`** sur `50%` (ou votre seuil de tolérance). Le système supprimera automatiquement les mauvais résultats !
5. Cliquez sur **`Batch Convert Folder`** sur le panneau de gauche, choisissez un dossier de vidéos, et allez prendre un café.

### Extraire les Meilleurs Moments :
Vous avez une longue vidéo ? Passez à l'onglet **`AI Moments`** !
Cliquez sur **`Generate Best Moments`** pour laisser l'IA trouver, évaluer et classer automatiquement les meilleures scènes de votre vidéo. Vous pouvez ensuite prévisualiser et convertir ces extraits directement. [Lisez le guide complet AI Moments ici](docs/AI_MOMENTS_FR.md).

---

## 💻 2. Utilisation en Ligne de Commande (CLI)

Si vous préférez la ligne de commande ou voulez automatiser le processus dans un script, la même magie "zéro config" est disponible via le CLI.

Pour traiter un dossier nommé `gifs_MonDossier` avec 8 processus en parallèle, le cadrage/couleurs gérés par l'IA, et la mise à la corbeille automatique des fichiers avec un score inférieur à 50% :

```bash
python3 -m src.engine.conversion.cli gifs_MonDossier --let-me-handle-it --workers 8 --reject-threshold 50
```

Et voilà ! Le script va convertir vos vidéos et supprimer automatiquement les fichiers `.gif` qui n'atteignent pas le seuil de visibilité de 50%.

---

---

## 🔍 3. Téléchargement et Conversion en une étape

Grâce à l'architecture modulaire, la recherche de GIFs (via DuckDuckGo, Tenor ou Giphy) est directement intégrée dans l'outil ! Plus besoin de télécharger vos médias à la main. Vous pouvez tout faire en une seule commande :

```bash
python3 -m src.engine.conversion.cli --search-keyword "arcade" --search-engine DuckDuckGo --search-limit 5 --let-me-handle-it
```

Cette commande va télécharger 5 GIFs correspondant à "arcade", puis les convertir automatiquement dans la foulée en utilisant tous les paramètres IA !

---

## 📝 4. Suivi et Logs (UI & CLI)

L'interface graphique intègre désormais un **panneau de logs dynamique** (cliquez sur "📝 Show / Hide Logs").
Vous y trouverez un menu déroulant pour régler le niveau de verbosité à la volée :
- **INFO** : (Par défaut) Affiche les scores de qualité, les résumés de conversion et les avertissements.
- **DEBUG** : Affiche absolument tout le traitement interne, y compris les retours complexes de FFMPEG (très utile pour analyser un problème spécifique).

Si vous utilisez le CLI, vous pouvez obtenir le même niveau de détail complet avec l'argument `--log-level DEBUG` (ou simplement `--verbose`).

---

## 🤖 5. Découvrir les AI Iconic Moments

Vous avez une vidéo de gameplay ou un film de 10 minutes et vous souhaitez extraire les meilleurs segments de 3 secondes pour votre panneau LED sans avoir à tout regarder ?

1. Allez dans le nouvel onglet **`AI Moments`** en haut de l'interface.
2. Sélectionnez votre vidéo et choisissez le nombre de moments à extraire (ex: le Top 5).
3. Activez vos critères de détection préférés (Action, Epic, Character, Loopable, DMD).
4. Cliquez sur **`Generate AI Moments`**. Le moteur IA va traiter la vidéo à une vitesse fulgurante et vous présenter une grille des meilleurs moments, classés par score.
5. Cliquez sur **`Details`** d'un moment, puis sur **`Open In Converter`**. Cela vous ramènera instantanément à l'onglet de conversion avec les timestamps exacts et le cadrage Auto Action parfaitement pré-configurés pour vous !
