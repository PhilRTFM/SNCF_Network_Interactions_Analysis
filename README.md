# Le réseau ferré français vu comme un graphe

Projet du cours *Metabolic networks / Graph analysis* (C. Frainay, F. Jourdan, INRAE Toxalim) : les méthodes d'analyse de graphes du cours appliquées au réseau ferré national (RFN), avec une comparaison avec l'Allemagne.

Le notebook `analyse_reseau.ipynb` est rédigé comme un rapport : pour chaque question, une figure suivie d'une légende qui en donne la lecture.

## Contenu du dépôt

```
SNCF_Network_Interactions_Analysis/
├── README.md                    ce fichier
├── requirements.txt             bibliothèques Python
├── preprocessing_datasets.py    prétraitement : data/brut -> data/genere
├── analyse_reseau.ipynb         rapport (déjà exécuté) : questions Q1 à Q11 et bonus
├── data/
│   ├── README.md                description de chaque fichier, sources et colonnes
│   ├── brut/                    fichiers téléchargés, sous leur nom d'origine
│   │   └── A_TELECHARGER.md     liste et liens des fichiers SNCF et GTFS à déposer ici
│   └── genere/                  tables produites par le script et lues par le notebook
└── figures/                     figures du notebook (PNG), une par question
```

## Reproduire l'analyse

1. Installer les bibliothèques : `pip install -r requirements.txt`
2. Exécuter `analyse_reseau.ipynb` (environ 4 minutes). Il ne lit que `data/genere/`, déjà fourni.

Pour refaire aussi le prétraitement :

3. Déposer dans `data/brut/` les fichiers listés dans [`data/brut/A_TELECHARGER.md`](data/brut/A_TELECHARGER.md), sous leur nom d'origine. Les trois fichiers Etalab (`communes.json`, `departements.json`, `regions.json`) y sont déjà.
4. Lancer, depuis ce dossier, `python preprocessing_datasets.py`. Toutes les tables de `data/genere/` sont recréées et un rapport de contrôle s'affiche. Une seule étape : `--etapes table`.

## Du CSV au fichier Cytoscape

Le prétraitement construit le graphe en trois temps :
1. **gares → liaisons** : deux gares voyageurs voisines sur une même ligne (ordonnées par point kilométrique, `liste-des-gares.csv`) sont reliées ; les lignes sont raccordées entre elles aux bifurcations, repérées sur les tracés (`fichier-de-formes-des-voies-…csv`) ;
2. **trafic** : chaque train du GTFS SNCF d'un mardi type est projeté sur l'itinéraire le plus rapide (vitesses de `vitesse-maximale-nominale-sur-ligne.csv`), ce qui donne le nombre de trains par jour de chaque liaison ;
3. **villes** : toutes les gares d'une même commune INSEE (référentiel Etalab) forment un seul nœud ; chaque liaison est mesurée le long du tracé (`lignes-par-statut.csv`), avec sa part sur LGV.

Il en sort deux tables, `villes.csv` (nœuds) et `liaisons.csv` (arêtes), puis le fichier Cytoscape `data/genere/reseau_villes.cyjs` (format JSON de Cytoscape.js), écrit par la fonction `ecrire_cyjs` du script :

| Dans Cytoscape | Construit à partir de | Attributs (colonnes des tables Cytoscape) |
|---|---|---|
| un nœud par ville (2 597) | une ligne de `villes.csv` | toutes les colonnes : code INSEE, nom, département, région, coordonnées, nombre de gares, voyageurs 2025, population, trains par jour, statut de desserte ; plus `cle` (= `id`) et `name` (nom de la ville) |
| une arête par liaison (3 182) | une ligne de `liaisons.csv` | toutes les colonnes : code de ligne, type (LGV ou classique), part sur LGV, trains par jour, longueur (poids du graphe), distances, détour ; plus `cle` (= `source~target`) et `interaction` (= `rail`) |
| position des nœuds | `lon`, `lat` | x = lon × 100, y = −lat × 145 : le réseau s'ouvre comme une carte de France |

Les valeurs manquantes deviennent `null`. Le fichier s'ouvre directement dans Cytoscape (*File → Import → Network from File*). `data/genere/reseau_ferre.cyjs` est construit de la même façon à partir de `nodes.csv` et `edges.csv` (une gare par nœud, identifiée par son code UIC).

## Cytoscape et compte rendu PDF

Chaque figure de réseau peut être refaite dans Cytoscape, piloté par le notebook avec [py4cytoscape](https://pypi.org/project/py4cytoscape/) :

1. ouvrir Cytoscape (version 3.10 ou plus récente) ;
2. dans la cellule « Cytoscape » du notebook, passer `CYTOSCAPE = True` ;
3. exécuter tout le notebook : pour chaque question, les résultats sont ajoutés comme colonnes grâce à la clé `cle`, un style est créé, et la vue est exportée dans `figures/` (`*_cytoscape.png`) puis affichée sous la légende.

Avec `CYTOSCAPE = False` (par défaut), py4cytoscape n'est pas importé et les cellules Cytoscape ne font rien.

Export en PDF : *File → Save and Export Notebook As → PDF*, ou, pour un rapport sans le code, `jupyter nbconvert --to pdf --no-input analyse_reseau.ipynb` (LaTeX requis).

## Questions traitées

| Question | Notion du cours | Figure |
|---|---|---|
| Q1. Où sont les lignes à grande vitesse ? | attributs des arêtes | `Q1_LGV.png` |
| Q2. Où circulent les trains ? | graphe pondéré | `Q2_trains.png` |
| Q3. Quelles villes sont proches de tout le réseau ? | closeness, farness | `Q3_closeness.png` |
| Q4. Où sont le centre et la périphérie ? Quel est le trajet le plus long ? | excentricité, rayon, diamètre | `Q4_excentricite.png` |
| Q5. Quels sont les points névralgiques ? | betweenness des nœuds et des arêtes | `Q5_betweenness.png` |
| Q6. Que se passe-t-il si on retire les villes les plus importantes (dont les 10 de plus forte betweenness) ? | robustesse, points d'articulation, composantes connexes | `Q6_robustesse.png` |
| Q7. Les trajets de la promotion vers Rouen | plus court chemin pondéré, sous-graphe, vue schématique | `Q7_trajets_rouen.png` |
| Q8. Les régions sont-elles inégalement desservies ? | attributs des nœuds, graphe quotient | `Q8_regions.png` |
| Q9. Quelles villes ne sont pas connectées ? | composantes connexes | `Q9_non_desservies.png` |
| Q10. Quelles gares sont les plus et les moins connectées ? | degré, distribution des degrés | `Q10_degre.png` |
| Q11. Quel trajet passe obligatoirement par le plus de gares ? | plus court chemin et diamètre non pondérés | `Q11_plus_de_gares.png` |
| Bonus. La France est-elle plus centralisée que l'Allemagne ? | métriques globales, modularité | `Bonus_France_Allemagne.png` |
