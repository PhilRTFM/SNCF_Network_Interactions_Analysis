# Fichiers à télécharger dans `data/brut/`

Ces fichiers ne sont pas dans le dépôt : ils sont trop lourds et `.gitignore` les exclut. Ils ne servent qu'à refaire le prétraitement ; pour exécuter le notebook, les tables de `data/genere/` suffisent.

Chaque fichier garde son nom d'origine, car `preprocessing_datasets.py` les lit sous ces noms. On ne les modifie pas et on ne décompresse pas les `.zip`, que le script lit directement. Sur les pages SNCF, le CSV se télécharge depuis l'onglet « Export » (format CSV).

Fichiers téléchargés le 24/11/2026. Le script analyse les trains du mardi 01/12/2026 (constante `JOUR_TYPE`) : avec des horaires téléchargés plus tard, choisir un mardi couvert par le GTFS.

## 1. SNCF Réseau : l'infrastructure

| Fichier | Page de téléchargement | Taille | Étape du script |
|---|---|---|---|
| `liste-des-gares.csv` | https://ressources.data.sncf.com/explore/dataset/liste-des-gares/ | 2 Mo | `gares`, `historique` |
| `fichier-de-formes-des-voies-du-reseau-ferre-national.csv` | https://ressources.data.sncf.com/explore/dataset/fichier-de-formes-des-voies-du-reseau-ferre-national/ | 47 Mo | `gares` |
| `vitesse-maximale-nominale-sur-ligne.csv` | https://ressources.data.sncf.com/explore/dataset/vitesse-maximale-nominale-sur-ligne/ | 9 Mo | `gares` |
| `lignes-par-statut.csv` | https://ressources.data.sncf.com/explore/dataset/lignes-par-statut/ | 10 Mo | `historique` |

## 2. SNCF Voyageurs : fréquentation et horaires

| Fichier | Page de téléchargement | Taille | Étape du script |
|---|---|---|---|
| `frequentation-gares.csv` | https://ressources.data.sncf.com/explore/dataset/frequentation-gares/ | 0,2 Mo | `gares` |
| `Export_OpenData_SNCF_GTFS_NewTripId.zip` | lien direct : https://eu.ftp.opendatasoft.com/sncf/plandata/Export_OpenData_SNCF_GTFS_NewTripId.zip (page : https://ressources.data.sncf.com/explore/dataset/horaires-sncf/) | 5,5 Mo | `trafic`, `gtfs` |

## Déjà dans le dépôt : référentiel Etalab

Rien à télécharger. Source : https://github.com/etalab/decoupage-administratif

| Fichier | Lien | Étape du script |
|---|---|---|
| `communes.json` | https://unpkg.com/@etalab/decoupage-administratif/data/communes.json | `table` |
| `departements.json` | https://unpkg.com/@etalab/decoupage-administratif/data/departements.json | `table` |
| `regions.json` | https://unpkg.com/@etalab/decoupage-administratif/data/regions.json | `table` |

## À ne pas télécharger

`horaires-sncf.csv`, proposé sur la page du GTFS SNCF, est la description du jeu de données et non les horaires : le script ne l'utilise pas.

## Contenu attendu du dossier

```
data/brut/
├── A_TELECHARGER.md
├── communes.json                                              (dépôt)
├── departements.json                                          (dépôt)
├── regions.json                                               (dépôt)
├── liste-des-gares.csv
├── fichier-de-formes-des-voies-du-reseau-ferre-national.csv
├── vitesse-maximale-nominale-sur-ligne.csv
├── lignes-par-statut.csv
├── frequentation-gares.csv
└── Export_OpenData_SNCF_GTFS_NewTripId.zip
```