# Données

Le dossier `brut/` contient les fichiers téléchargés, sous leur nom d'origine, à ne jamais modifier (liste et liens : `brut/A_TELECHARGER.md`). Seuls les trois fichiers Etalab sont dans le dépôt ; les autres sont exclus par `.gitignore`. Le dossier `genere/` contient les fichiers produits par `preprocessing_datasets.py`. Le notebook `analyse_reseau.ipynb` ne lit que ce dossier.

Les CSV SNCF utilisent le séparateur `;` et l'encodage UTF-8 avec BOM : les lire avec `encoding="utf-8-sig"`. Les zip ne sont pas décompressés, le script les lit directement.

## Fichiers bruts (`brut/`)

| Fichier | Source | Contenu | Utilisé pour |
|---|---|---|---|
| `liste-des-gares.csv` | [SNCF Réseau, Liste des gares](https://ressources.data.sncf.com/explore/dataset/liste-des-gares/) | gares : code UIC, nom, commune, département, voyageurs (O/N), code ligne et point kilométrique, coordonnées | nœuds du graphe |
| `fichier-de-formes-des-voies-du-reseau-ferre-national.csv` | [SNCF Réseau, Formes des voies du RFN](https://ressources.data.sncf.com/explore/dataset/fichier-de-formes-des-voies-du-reseau-ferre-national/) | environ 10 000 tronçons de voie : code ligne, points kilométriques, tracé GeoJSON | trouver où les lignes se raccordent |
| `vitesse-maximale-nominale-sur-ligne.csv` | [SNCF Réseau, Vitesse maximale nominale](https://ressources.data.sncf.com/explore/dataset/vitesse-maximale-nominale-sur-ligne/) | vitesse maximale par portion de ligne | colonne `temps_min` de `edges.csv` ; colonnes `vitesse_kmh` et `part_grande_vitesse` de `liaisons.csv` |
| `lignes-par-statut.csv` | [SNCF Réseau, Lignes par statut](https://ressources.data.sncf.com/explore/dataset/lignes-par-statut/) | tracé de chaque ligne et son statut (exploitée, fermée, neutralisée, déclassée…) | longueur le long du tracé, part sur LGV |
| `frequentation-gares.csv` | [SNCF, Fréquentation en gares](https://ressources.data.sncf.com/explore/dataset/frequentation-gares/) | voyageurs par gare en 2025 | attribut des villes |
| `Export_OpenData_SNCF_GTFS_NewTripId.zip` | [SNCF, Horaires (GTFS)](https://ressources.data.sncf.com/explore/dataset/horaires-sncf/) | horaires théoriques TER, TGV INOUI, OUIGO, Intercités (sans Transilien ni RER) | trains par jour sur chaque liaison, un mardi type (01/12/2026) |
| `communes.json`, `departements.json`, `regions.json` | [Etalab, découpage administratif](https://github.com/etalab/decoupage-administratif) | communes (code INSEE, population, département, région) | regrouper les gares par commune, normaliser par région |

Codes des lignes à grande vitesse : numéros RFN relevés dans les articles Wikipédia de chaque LGV (constante `LGV` du script), vérifiés par la longueur mesurée dans les données.

## Prétraitement

Tout recréer : `python preprocessing_datasets.py`. Une seule étape : `--etapes gares trafic historique gtfs table`.

| Étape | Ce qu'elle fait | Sorties |
|---|---|---|
| `gares` | relie les gares voisines sur une même ligne, puis raccorde les lignes entre elles aux bifurcations | `nodes.csv`, `edges.csv`, `reseau_ferre.cyjs` |
| `trafic` | compte les trains d'un mardi type sur chaque liaison | colonne `nb_trains_jour` de `edges.csv` |
| `historique` | réseau des voies le long de leur tracé, lignes exploitées et fermées | `historique_nodes.csv`, `historique_edges.csv` |
| `gtfs` | réseau desservi France : une gare par nœud, une arête par paire d'arrêts consécutifs d'un train | `gtfs_fr_*.csv` |
| `table` | tables finales : gares d'une même commune regroupées en une ville, longueur le long du tracé, part sur LGV, rattachement INSEE, contrôles | `villes.csv`, `liaisons.csv`, `regions.csv`, `departements.csv`, `reseau_villes.cyjs` |

## Tables finales (`genere/`), lues par le notebook

| Fichier | Contenu |
|---|---|
| `villes.csv` | une ligne par ville : `id` (code INSEE ; `COMMUNE|DÉPARTEMENT` pour les 14 villes que le script n'a pas pu rattacher), `nom`, `departement`, `region`, `lon`, `lat`, `nb_gares`, `voyageurs_2025`, `population`, `nb_trains_jour`, `desservie`, `statut_desserte` (desservie, non desservie, inconnue en Île-de-France), `reseau_principal` |
| `liaisons.csv` | une ligne par liaison ville → ville : `code_ligne`, `type_ligne` (LGV ou classique), `lgv`, `part_lgv`, `vitesse_kmh` (vitesse maximale permise, moyenne harmonique le long du tracé), `part_grande_vitesse` (part du tracé à 250 km/h ou plus), `nb_trains_jour` (deux sens), `longueur_km` (poids du graphe : tracé, sinon points kilométriques), `distance_km` (points kilométriques), `distance_trace_km` (tracé), `vol_oiseau_km`, `detour` |
| `regions.csv`, `departements.csv` | communes, communes avec gare, population, villes desservies ou non, parts en % (Corse exclue : hors RFN) |
| `reseau_villes.cyjs` | le réseau des villes pour Cytoscape : un nœud par ligne de `villes.csv`, une arête par ligne de `liaisons.csv`, toutes les colonnes en attributs, plus la clé `cle` (voir le README principal) |

Fichiers intermédiaires : `nodes.csv`, `edges.csv` (réseau gare → gare), `historique_*.csv` (réseau des voies), `gtfs_fr_*.csv` (réseau desservi, lu en Q10), `reseau_ferre.cyjs` (réseau des gares pour Cytoscape).
