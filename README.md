# Le réseau ferré français vu comme un graphe

Projet du cours *Metabolic networks / Graph analysis* (C. Frainay, F. Jourdan, INRAE Toxalim) : les méthodes d'analyse de graphes du cours appliquées au réseau ferré national (RFN), avec une comparaison avec l'Allemagne.

## Contenu de l'archive

```
projet_reseau_ferre/
├── README.md                    ce fichier
├── requirements.txt             bibliothèques Python
├── preprocessing_datasets.py    prétraitement : data/brut -> data/genere
├── analyse_reseau.ipynb         analyse (déjà exécutée) : questions Q1 à Q9 et bonus
├── data/
│   ├── README.md                description de chaque fichier, sources et colonnes
│   ├── brut/                    fichiers téléchargés, sous leur nom d'origine
│   │   └── A_TELECHARGER.md     liste et liens des fichiers SNCF et GTFS à déposer ici
│   └── genere/                  tables produites par le script et lues par le notebook
├── figures/                     figures du notebook (PNG)
└── cours/                       supports de cours (PDF)
```

## Reproduire l'analyse

1. Installer les bibliothèques : `pip install -r requirements.txt`
2. Déposer dans `data/brut/` les fichiers listés dans `data/brut/A_TELECHARGER.md`, sous leur nom d'origine. Les trois fichiers Etalab (`communes.json`, `departements.json`, `regions.json`) y sont déjà.
3. Lancer le prétraitement depuis ce dossier : `python preprocessing_datasets.py`. Toutes les tables de `data/genere/` sont alors recréées, et un rapport de contrôle s'affiche.
4. Ouvrir `analyse_reseau.ipynb` et exécuter toutes les cellules (environ 4 minutes).

Les tables de `data/genere/` sont déjà fournies : on peut exécuter le notebook directement, sans refaire les étapes 2 et 3.

## Cytoscape et compte rendu PDF

Tout le notebook se refait dans Cytoscape, à partir du réseau construit par le prétraitement (`data/genere/reseau_villes.cyjs`). Le notebook pilote Cytoscape avec [py4cytoscape](https://pypi.org/project/py4cytoscape/).

1. Ouvrir Cytoscape (version 3.10 ou plus récente).
2. Dans la cellule « Cytoscape » du notebook, passer `CYTOSCAPE = True`.
3. Exécuter tout le notebook. Pour chaque question, les résultats sont ajoutés comme colonnes aux tables de Cytoscape, un style est créé, et la vue est exportée dans `figures/` puis **affichée dans le notebook**.
4. Exporter le notebook en PDF : *File → Save and Export Notebook As → PDF* (ou *Download as → PDF*).

Le fichier `data/genere/reseau_villes.cyjs` s'ouvre aussi directement dans Cytoscape (*File → Import → Network from File*). Chaque ville et chaque liaison y porte une clé `cle`, qui sert à y ajouter des colonnes.

## Questions traitées

| Question | Notion du cours |
|---|---|
| Q1. Où sont les lignes à grande vitesse ? | attributs des arêtes |
| Q2. Où circulent les trains ? | graphe pondéré |
| Q3. Quelles villes sont proches de tout le réseau ? | closeness, farness |
| Q4. Où sont le centre et la périphérie ? Quel est le trajet le plus long ? | excentricité, rayon, diamètre |
| Q5. Quels sont les points névralgiques ? | betweenness des nœuds et des arêtes |
| Q6. Que se passe-t-il si on retire les villes les plus importantes (dont les 10 de plus forte betweenness) ? | robustesse, points d'articulation, composantes connexes |
| Q7. Les trajets de la promotion vers Rouen | plus court chemin pondéré, sous-graphe, vue schématique |
| Q8. Les régions sont-elles inégalement desservies ? | attributs des nœuds, graphe quotient |
| Q9. Quelles villes ne sont pas connectées ? | composantes connexes |
| Q10. Quelles gares sont les plus et les moins connectées ? | degré, distribution des degrés |
| Q11. Quel trajet passe obligatoirement par le plus de gares ? | plus court chemin et diamètre non pondérés |
| Bonus. La France est-elle plus centralisée que l'Allemagne ? | métriques globales, modularité |
