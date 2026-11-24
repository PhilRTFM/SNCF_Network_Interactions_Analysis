# Fichiers à déposer dans ce dossier

Garder le nom d'origine de chaque fichier téléchargé : le script `preprocessing_datasets.py` les lit sous ces noms. Ne jamais modifier ces fichiers.

Sur les pages SNCF, le CSV se télécharge depuis l'onglet « Export ».

| Fichier | Lien |
|---|---|
| `liste-des-gares.csv` | https://ressources.data.sncf.com/explore/dataset/liste-des-gares/ |
| `fichier-de-formes-des-voies-du-reseau-ferre-national.csv` | https://ressources.data.sncf.com/explore/dataset/fichier-de-formes-des-voies-du-reseau-ferre-national/ |
| `vitesse-maximale-nominale-sur-ligne.csv` | https://ressources.data.sncf.com/explore/dataset/vitesse-maximale-nominale-sur-ligne/ |
| `lignes-par-statut.csv` | https://ressources.data.sncf.com/explore/dataset/lignes-par-statut/ |
| `frequentation-gares.csv` | https://ressources.data.sncf.com/explore/dataset/frequentation-gares/ |
| `Export_OpenData_SNCF_GTFS_NewTripId.zip` | https://eu.ftp.opendatasoft.com/sncf/plandata/Export_OpenData_SNCF_GTFS_NewTripId.zip (page : https://ressources.data.sncf.com/explore/dataset/horaires-sncf/) |
| `latest.zip` | https://gtfs.de/en/feeds/de_full/ (bonus Allemagne) |

Déjà présents dans ce dossier (référentiel Etalab, https://github.com/etalab/decoupage-administratif) :

| Fichier | Lien |
|---|---|
| `communes.json` | https://unpkg.com/@etalab/decoupage-administratif/data/communes.json |
| `departements.json` | https://unpkg.com/@etalab/decoupage-administratif/data/departements.json |
| `regions.json` | https://unpkg.com/@etalab/decoupage-administratif/data/regions.json |

`horaires-sncf.csv`, téléchargé depuis la page du GTFS SNCF, n'est pas utilisé : c'est la description du jeu de données, pas les horaires.

Les fichiers ont été téléchargés le 24/11/2026.
