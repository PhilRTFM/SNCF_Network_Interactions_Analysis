"""Prétraitement des jeux de données bruts (data/brut) -> fichiers d'analyse (data/genere).

Étapes (toutes par défaut, ou au choix : python preprocessing_datasets.py --etapes gares trafic) :
  gares      réseau gares -> gares (PK + jonctions des voies, vitesse max -> temps) -> nodes.csv, edges.csv, reseau_ferre.cyjs
  trafic     nombre de trains par liaison, un mardi type (GTFS SNCF)      -> colonne nb_trains_jour de edges.csv
  historique réseau de voies, lignes actuelles + fermées/neutralisées     -> historique_nodes.csv, historique_edges.csv
  gtfs       réseau desservi France (une gare par nœud, trains directs)   -> gtfs_fr_nodes.csv, gtfs_fr_edges.csv
  table      tables finales par ville (gares d'une commune regroupées)    -> villes.csv, liaisons.csv, regions.csv, departements.csv, reseau_villes.cyjs
             (n'utilise que les fichiers générés ci-dessus et le référentiel des communes Etalab)

Le notebook analyse_reseau.ipynb ne lit que data/genere.
"""
import argparse
import heapq
import json
import math
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

RACINE = Path(__file__).resolve().parent
BRUT = RACINE / "data" / "brut"
GENERE = RACINE / "data" / "genere"

VOIES = BRUT / "fichier-de-formes-des-voies-du-reseau-ferre-national.csv"
GARES = BRUT / "liste-des-gares.csv"
FREQUENTATION = BRUT / "frequentation-gares.csv"
STATUTS = BRUT / "lignes-par-statut.csv"
VITESSES = BRUT / "vitesse-maximale-nominale-sur-ligne.csv"
GTFS_FR = BRUT / "Export_OpenData_SNCF_GTFS_NewTripId.zip"  # Horaires SNCF (GTFS)

JOUR_TYPE = "20261201"  # mardi hors vacances, couvert par le GTFS SNCF
TYPES_FERRO = {"2"} | {str(t) for t in range(100, 118)}  # GTFS : train (simple et étendu)

VOYAGEURS_SEULEMENT = True  # False pour garder aussi les gares fret
RAYON_JONCTION_KM = 0.2  # distance max entre l'extrémité d'une ligne et la ligne qu'elle rejoint
RAYON_JONCTION_HISTORIQUE_KM = 0.5  # tracés de lignes-par-statut plus grossiers (ex. Sète : 360 m)
TOLERANCE_ELAGAGE = 1.15  # A-B est retirée si un chemin via d'autres gares fait moins de 115 % + 0,5 km

KX, KY = 111.32 * math.cos(math.radians(46.5)), 110.57  # km par degré (projection locale)


def lire_csv_sncf(chemin):
    return pd.read_csv(chemin, sep=";", dtype=str, encoding="utf-8-sig")


def pk_en_km(pk):
    """'123+456' -> 123.456 ; '000-031' -> -0.031 ; PK à lettre ('H+566') -> NaN."""
    if not isinstance(pk, str):
        return float("nan")
    if "+" in pk:
        km, m = pk.split("+")
        return int(km) + int(m) / 1000 if km.lstrip("-").isdigit() else float("nan")
    km, m = pk.split("-")
    return int(km) - int(m) / 1000


def vol_oiseau_km(lon1, lat1, lon2, lat2):
    return math.hypot((lon1 - lon2) * KX, (lat1 - lat2) * KY)


def points_des_traces(shapes, lignes, troncons, pk_debut, pk_fin, lon_debut, lat_debut):
    """Découpe chaque tracé (GeoJSON LineString/MultiLineString) en points (km projetés),
    avec pour chaque point sa clé 'ligne|troncon' et son PK interpolé."""
    pts, pt_cle, pt_pk = [], [], []
    for shape, ligne, tr, pk_d, pk_f, xd, yd in zip(shapes, lignes, troncons, pk_debut, pk_fin, lon_debut, lat_debut):
        geo = json.loads(shape)
        geo = geo.get("geometry", geo)
        parts = geo["coordinates"] if geo["type"] == "MultiLineString" else [geo["coordinates"]]
        xy = np.array([(lon * KX, lat * KY) for part in parts for lon, lat in part])
        debut = np.array([xd * KX, yd * KY])
        if np.linalg.norm(xy[0] - debut) > np.linalg.norm(xy[-1] - debut):
            xy = xy[::-1]  # on oriente la forme du PK début vers le PK fin
        cum = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))])
        frac = cum / cum[-1] if cum[-1] > 0 else np.zeros(len(cum))
        pts.append(xy)
        pt_cle += [f"{ligne}|{tr}"] * len(xy)
        pt_pk.append(pk_d + (pk_f - pk_d) * frac)
    return np.vstack(pts), np.array(pt_cle), np.concatenate(pt_pk)


def ajouter_jonctions(chaines, pts, pt_cle, pt_pk, rayon_km=RAYON_JONCTION_KM):
    """Pour chaque extrémité de ligne, cherche les autres lignes à moins de rayon_km et
    ajoute un nœud de jonction commun dans les chaînes concernées. Modifie `chaines`."""
    arbre = cKDTree(pts)
    n = 0
    positions = {}  # jonction -> (lon, lat)
    for cle in np.unique(pt_cle):
        idx = np.flatnonzero(pt_cle == cle)
        for i in (idx[np.argmin(pt_pk[idx])], idx[np.argmax(pt_pk[idx])]):  # 2 extrémités
            proches = {}
            for j in arbre.query_ball_point(pts[i], rayon_km):
                autre = pt_cle[j]
                if autre == cle:
                    continue
                d = np.linalg.norm(pts[j] - pts[i])
                if autre not in proches or d < proches[autre][0]:
                    proches[autre] = (d, pt_pk[j])
            if proches:
                jid = f"J{n}"
                n += 1
                positions[jid] = (pts[i][0] / KX, pts[i][1] / KY)
                chaines[cle].append((jid, pt_pk[i]))
                for autre, (_, pk) in proches.items():
                    chaines[autre].append((jid, pk))
    return positions


def graphe_des_chaines(chaines):
    """Chaque chaîne (ligne|tronçon) = suite de nœuds ordonnés par PK -> arêtes pondérées en km."""
    G = nx.Graph()
    for cle, elems in chaines.items():
        elems = sorted(set(elems), key=lambda e: e[1])
        for (a, pa), (b, pb) in zip(elems, elems[1:]):
            if a == b:
                continue
            w = abs(pb - pa)
            if not G.has_edge(a, b) or w < G[a][b]["w"]:
                G.add_edge(a, b, w=w, ligne=cle.split("|")[0], cle=cle)
    return G


def contracter(G, gardes):
    """Ne garde que les nœuds `gardes` : A-B existe si un chemin les relie sans passer par un autre nœud gardé."""
    def voisins(s):
        dist, lignes, tas, res = {s: 0.0}, {s: frozenset()}, [(0.0, s)], {}
        while tas:
            d, u = heapq.heappop(tas)
            if d > dist[u]:
                continue
            if u != s and u in gardes:
                res[u] = (d, lignes[u])
                continue
            for v, attr in G[u].items():
                nd = d + attr["w"]
                if nd < dist.get(v, math.inf):
                    dist[v], lignes[v] = nd, lignes[u] | {attr["ligne"]}
                    heapq.heappush(tas, (nd, v))
        return res

    H = nx.Graph()
    for s in gardes & set(G.nodes):
        for t, (d, l) in voisins(s).items():
            if not H.has_edge(s, t) or d < H[s][t]["w"]:
                H.add_edge(s, t, w=d, lignes=l)
    return H


def elaguer(H, poids="w", tolerance=TOLERANCE_ELAGAGE, marge=0.1):
    """Retire A-B si un chemin passant par d'autres nœuds est à peine plus long selon `poids`
    (sinon une gare proche d'une LGV se retrouve reliée à toutes les gares joignables par la LGV).
    Avec poids = temps de parcours, une LGV parallèle à une ligne classique (Mâcon-Loché -> Lyon)
    est conservée : le détour par la ligne classique est à peine plus long mais bien plus lent."""
    for a, b, d in sorted(H.edges(data=poids), key=lambda e: -e[2]):
        attr = H[a][b]
        H.remove_edge(a, b)
        try:
            alt = nx.dijkstra_path_length(H, a, b, weight=poids)
        except nx.NetworkXNoPath:
            alt = math.inf
        if alt > d * tolerance + marge:
            H.add_edge(a, b, **attr)
    return H


def vitesses_par_ligne():
    """Vitesse max nominale par code ligne : moyenne harmonique pondérée par la longueur
    (la vitesse constante qui donnerait le même temps total)."""
    v = lire_csv_sncf(VITESSES)
    v["long"] = (v["PKF"].map(pk_en_km) - v["PKD"].map(pk_en_km)).abs()
    v["V_MAX"] = pd.to_numeric(v["V_MAX"], errors="coerce")
    v = v.dropna(subset=["long", "V_MAX"])
    v = v[v["long"] > 0]
    return (v.groupby("CODE_LIGNE")["long"].sum()
            / (v["long"] / v["V_MAX"]).groupby(v["CODE_LIGNE"]).sum())


def vmax_liaison(lignes, vmax_ligne, defaut):
    # la ligne la plus rapide : les autres codes d'une liaison sont surtout de courts raccordements
    vs = [vmax_ligne[l] for l in lignes if l in vmax_ligne.index]
    return max(vs) if vs else defaut


def charger_gares(voyageurs_seulement=VOYAGEURS_SEULEMENT):
    gares = lire_csv_sncf(GARES)
    if voyageurs_seulement:
        gares = gares[gares["voyageurs"] == "O"].copy()
    gares["uic"] = gares["code_uic"].str.lstrip("0")
    gares["pk_km"] = gares["pk"].map(pk_en_km)
    for c in ["x_wgs84", "y_wgs84"]:
        gares[c] = gares[c].astype(float)
    return gares


def ecrire_cyjs(nodes, edges, chemin, nom, scale=100):
    def clean(d):
        return {k: (None if (not isinstance(v, (list, dict)) and pd.isna(v)) else v) for k, v in d.items()}

    cy = {
        "format_version": "1.0",
        "generated_by": "preprocessing_datasets.py",
        "data": {"name": nom},
        "elements": {
            "nodes": [
                {"data": clean({**r, "id": str(r["id"]), "cle": str(r["id"]), "name": r.get("nom", r["id"])}),
                 "position": {"x": r["lon"] * scale, "y": -r["lat"] * scale * 1.45}}  # 1,45 : proportions de la France
                for r in nodes.to_dict("records")
            ],
            "edges": [
                {"data": clean({**r, "source": str(r["source"]), "target": str(r["target"]),
                                "id": f"e{i}", "cle": f"{r['source']}~{r['target']}", "interaction": "rail"})}
                for i, r in enumerate(edges.to_dict("records"))
            ],
        },
    }
    # Cytoscape déduit le type d'une colonne de la première valeur lue : un premier élément sans valeur manquante
    # garde les colonnes numériques en nombres (sinon une colonne qui commence par null devient du texte).
    for elements in cy["elements"].values():
        complet = next((i for i, e in enumerate(elements) if None not in e["data"].values()), 0)
        elements.insert(0, elements.pop(complet))
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(cy, f, ensure_ascii=False)




def charger_voies_comme_points(chemin, col_pkd, col_pkf):
    df = lire_csv_sncf(chemin)
    df["pk_d"] = df[col_pkd].map(pk_en_km)
    df["pk_f"] = df[col_pkf].map(pk_en_km)
    df = df.dropna(subset=["pk_d", "pk_f", "Geo Shape"])
    return df, points_des_traces(
        df["Geo Shape"], df["CODE_LIGNE"], df["RG_TRONCON"], df["pk_d"], df["pk_f"],
        df["X_D_WGS84"].astype(float), df["Y_D_WGS84"].astype(float),
    )


# =====================================================================================
# Étape « gares » : réseau gares -> gares
# =====================================================================================
def etape_gares():
    gares = charger_gares()
    freq = lire_csv_sncf(FREQUENTATION)

    # Nœuds : une ligne par gare (une gare peut être sur plusieurs lignes)
    freq["uic"] = freq["code_uic_complet"].str.lstrip("0")
    cols_voy = [c for c in freq.columns if c.startswith("total_voyageurs")]
    freq[cols_voy] = freq[cols_voy].apply(pd.to_numeric, errors="coerce")
    freq = freq.drop_duplicates("uic")[["uic", "segmentation_drg"] + cols_voy]

    lignes_par_gare = gares.groupby("uic")["code_ligne"].apply(lambda s: ",".join(sorted(set(s))))
    nodes = (
        gares.drop_duplicates("uic")
        .set_index("uic")[["libelle", "commune", "departemen", "x_wgs84", "y_wgs84"]]
        .rename(columns={"libelle": "nom", "departemen": "departement", "x_wgs84": "lon", "y_wgs84": "lat"})
    )
    nodes["lignes"] = lignes_par_gare
    nodes = nodes.reset_index().rename(columns={"uic": "id"})
    nodes = nodes.merge(freq, left_on="id", right_on="uic", how="left").drop(columns="uic")

    # Jonctions entre lignes, à partir du fichier des voies : dans liste-des-gares, une gare de
    # bifurcation n'est rattachée qu'à une seule ligne, on retrouve donc où chaque ligne se
    # raccorde aux autres en regardant ses extrémités.
    _, (pts, pt_cle, pt_pk) = charger_voies_comme_points(VOIES, "PK_DEBUT_R", "PK_FIN_R")
    chaines = defaultdict(list)  # 'ligne|troncon' -> [(noeud, pk)]
    for g in gares.dropna(subset=["pk_km"]).itertuples():
        chaines[f"{g.code_ligne}|{g.rg_troncon}"].append((g.uic, g.pk_km))
    ajouter_jonctions(chaines, pts, pt_cle, pt_pk)

    # Graphe gares + jonctions, puis liaisons gare -> gare uniquement
    H = contracter(graphe_des_chaines(chaines), set(gares["uic"]))
    pos = nodes.set_index("id")[["lon", "lat"]]
    vmax_ligne = vitesses_par_ligne()
    defaut = float(vmax_ligne.median())
    for a, b, at in H.edges(data=True):
        at["vol"] = vol_oiseau_km(*pos.loc[a], *pos.loc[b])
        at["km"] = max(at["w"], at["vol"])  # le PK ne peut pas être plus court que le vol d'oiseau
        at["vmax"] = vmax_liaison(at["lignes"], vmax_ligne, defaut)
        at["t"] = at["km"] / at["vmax"] * 60
    H = elaguer(H, poids="t")

    edges = pd.DataFrame(
        [(a, b, ",".join(sorted(at["lignes"])), round(at["km"], 3), len(at["lignes"]),
          round(at["vol"], 3), round(at["vmax"], 1), round(at["t"], 2))
         for a, b, at in H.edges(data=True)],
        columns=["source", "target", "code_ligne", "distance_km", "nb_lignes",
                 "vol_oiseau_km", "vmax_kmh", "temps_min"],
    )

    nodes.to_csv(GENERE / "nodes.csv", index=False, encoding="utf-8")
    edges.to_csv(GENERE / "edges.csv", index=False, encoding="utf-8")

    R = nx.Graph()
    R.add_nodes_from(nodes["id"])
    R.add_edges_from(zip(edges.source, edges.target))
    comps = sorted((len(c) for c in nx.connected_components(R)), reverse=True)
    print(f"[gares] {len(nodes)} gares | {len(edges)} liaisons | {nx.number_of_isolates(R)} isolées | "
          f"{len(comps)} composantes (plus grande : {comps[0]}) | "
          f"{nodes[cols_voy[0]].isna().sum()} gares sans fréquentation")


# =====================================================================================
# GTFS : paires d'arrêts consécutifs desservis un jour donné
# =====================================================================================
def services_actifs(z, date):
    actifs = set()
    if "calendar.txt" in z.namelist():
        cal = pd.read_csv(z.open("calendar.txt"), dtype=str)
        jour = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][
            datetime.strptime(date, "%Y%m%d").weekday()]
        ok = (cal["start_date"] <= date) & (cal["end_date"] >= date) & (cal[jour] == "1")
        actifs = set(cal.loc[ok, "service_id"])
    if "calendar_dates.txt" in z.namelist():
        cd = pd.read_csv(z.open("calendar_dates.txt"), dtype=str)
        cd = cd[cd["date"] == date]
        actifs |= set(cd.loc[cd["exception_type"] == "1", "service_id"])
        actifs -= set(cd.loc[cd["exception_type"] == "2", "service_id"])
    return actifs


def paires_gtfs(chemin_zip, date, cle_station, filtre_routes=None):
    """Renvoie (stations, paires) :
    stations : id, nom, lon, lat ;  paires : source, target (non orientées), nb_trains (les 2 sens)."""
    z = zipfile.ZipFile(chemin_zip)
    routes = pd.read_csv(z.open("routes.txt"), dtype=str)
    routes = routes[routes["route_type"].isin(TYPES_FERRO)]
    if filtre_routes is not None:
        routes = routes[filtre_routes(routes)]
    trips = pd.read_csv(z.open("trips.txt"), dtype=str, usecols=["route_id", "service_id", "trip_id"])
    trips = trips[trips["route_id"].isin(set(routes["route_id"])) & trips["service_id"].isin(services_actifs(z, date))]
    ids = set(trips["trip_id"])

    stops = pd.read_csv(z.open("stops.txt"), dtype=str)
    stops["station"] = cle_station(stops)
    stops = stops.dropna(subset=["station"])

    morceaux = []
    for ch in pd.read_csv(z.open("stop_times.txt"), dtype=str, chunksize=2_000_000,
                          usecols=["trip_id", "stop_id", "stop_sequence"]):
        morceaux.append(ch[ch["trip_id"].isin(ids)])
    st = pd.concat(morceaux)
    st["stop_sequence"] = st["stop_sequence"].astype(int)
    st = st.merge(stops[["stop_id", "station"]], on="stop_id").sort_values(["trip_id", "stop_sequence"])
    st["suivante"] = st.groupby("trip_id")["station"].shift(-1)
    p = st.dropna(subset=["suivante"])
    p = p[p["station"] != p["suivante"]]
    a, b = np.minimum(p["station"], p["suivante"]), np.maximum(p["station"], p["suivante"])
    paires = pd.DataFrame({"source": a, "target": b}).value_counts().rename("nb_trains").reset_index()

    servies = set(paires["source"]) | set(paires["target"])
    sta = stops[stops["station"].isin(servies)]
    # coordonnées et nom : ceux de la zone d'arrêt si elle existe, sinon du premier quai
    sta = sta.assign(est_zone=sta["stop_id"] == sta["station"]).sort_values("est_zone", ascending=False)
    stations = (sta.drop_duplicates("station")[["station", "stop_name", "stop_lon", "stop_lat"]]
                .rename(columns={"station": "id", "stop_name": "nom", "stop_lon": "lon", "stop_lat": "lat"}))
    stations[["lon", "lat"]] = stations[["lon", "lat"]].astype(float)
    print(f"   {Path(chemin_zip).name} : {len(ids)} trains le {date}, {len(stations)} gares, {len(paires)} liaisons")
    return stations, paires


def cle_station_fr(stops):
    """Code UIC (8 chiffres en fin de stop_id), gares françaises (87...) seulement."""
    uic = stops["stop_id"].str.extract(r"(\d{8})$")[0]
    return uic.where(uic.str.startswith("87", na=False))


# =====================================================================================
# Étape « trafic » : nombre de trains par liaison du réseau gares -> gares
# =====================================================================================
def etape_trafic():
    _, paires = paires_gtfs(GTFS_FR, JOUR_TYPE, cle_station_fr)
    edges = pd.read_csv(GENERE / "edges.csv", dtype={"source": str, "target": str, "code_ligne": str})
    G = nx.Graph()
    poids = edges["temps_min"] if "temps_min" in edges else edges["distance_km"]
    G.add_weighted_edges_from(zip(edges.source, edges.target, poids))

    # un train qui va de A à B sans s'arrêter charge toutes les liaisons du chemin le plus rapide A -> B
    # (un TGV prend la LGV même si la ligne classique est un peu plus courte)
    charge, non_projetees = Counter(), 0
    for a, b, n in paires.itertuples(index=False):
        try:
            chemin = nx.dijkstra_path(G, a, b)
        except (nx.NodeNotFound, nx.NetworkXNoPath):
            non_projetees += n
            continue
        for u, v in zip(chemin, chemin[1:]):
            charge[frozenset((u, v))] += n
    edges["nb_trains_jour"] = [charge.get(frozenset((a, b)), 0) for a, b in zip(edges.source, edges.target)]
    edges.to_csv(GENERE / "edges.csv", index=False, encoding="utf-8")
    total = paires["nb_trains"].sum()
    print(f"[trafic] {100 * (1 - non_projetees / total):.1f} % des passages projetés | "
          f"{(edges.nb_trains_jour == 0).sum()} liaisons sans train le {JOUR_TYPE}")


# =====================================================================================
# Étape « historique » : réseau de voies, lignes exploitées + fermées / neutralisées / déclassées
# =====================================================================================
def categorie_statut(statut):
    s = str(statut)
    if s.startswith("Exploitée") or s.startswith("S9A3"):
        return "exploitee"
    if s.startswith("Neutralisée"):
        return "neutralisee"
    if s.startswith("Transférée"):
        return "voie_de_service"
    if s.startswith("Déclassée") or s.startswith("Retranchée"):
        return "declassee"
    return "fermee"


def etape_historique():
    """Réseau de voies construit sur la géométrie des tracés de lignes-par-statut (sans les PK, trop
    incohérents entre tracés) : distances mesurées le long des polylignes, extrémités raccordées au
    tracé voisin le plus proche, gares accrochées au tracé exploité le plus proche."""
    lignes = lire_csv_sncf(STATUTS).dropna(subset=["Geo Shape"]).drop_duplicates(subset=["Geo Shape"])
    lignes["categorie"] = lignes["STATUT"].map(categorie_statut)

    # 1. sommets de tous les tracés (km projetés), avec leur tracé et leur rang dans le tracé
    traces = []  # (xy, code_ligne, statut, categorie)
    for shape, code, st, cat in zip(lignes["Geo Shape"], lignes["CODE_LIGNE"], lignes["STATUT"], lignes["categorie"]):
        geo = json.loads(shape)
        parts = geo["coordinates"] if geo["type"] == "MultiLineString" else [geo["coordinates"]]
        for part in parts:
            if len(part) >= 2:
                traces.append((np.array([(lon * KX, lat * KY) for lon, lat in part]), code, st, cat))
    sommets = np.vstack([t[0] for t in traces])
    trace_de = np.concatenate([np.full(len(t[0]), k) for k, t in enumerate(traces)])
    rang_de = np.concatenate([np.arange(len(t[0])) for t in traces])
    debut = np.concatenate([[0], np.cumsum([len(t[0]) for t in traces])])[:-1]  # indice global du 1er sommet
    arbre = cKDTree(sommets)

    utiles = defaultdict(set)  # tracé -> rangs des sommets qui deviennent des nœuds
    for k, t in enumerate(traces):
        utiles[k] |= {0, len(t[0]) - 1}
    connecteurs = []  # (sommet global a, sommet global b, km, tracé d'origine)

    # 2. jonctions : chaque extrémité de tracé est reliée au sommet le plus proche de chaque autre tracé
    for k, t in enumerate(traces):
        for r in (0, len(t[0]) - 1):
            g = debut[k] + r
            proches = {}
            for j in arbre.query_ball_point(sommets[g], RAYON_JONCTION_HISTORIQUE_KM):
                kk = trace_de[j]
                if kk == k:
                    continue
                d = float(np.linalg.norm(sommets[j] - sommets[g]))
                if kk not in proches or d < proches[kk][0]:
                    proches[kk] = (d, j)
            for kk, (d, j) in proches.items():
                utiles[kk].add(rang_de[j])
                connecteurs.append((g, j, d, k))

    # 3. gares voyageurs : accrochées au sommet le plus proche d'un tracé exploité
    gares = charger_gares()
    expl = np.flatnonzero(np.array([traces[k][3] == "exploitee" for k in trace_de]))
    arbre_expl = cKDTree(sommets[expl])
    d, i = arbre_expl.query(np.c_[gares["x_wgs84"] * KX, gares["y_wgs84"] * KY])
    accroche = {}
    for uic, dist, ii in zip(gares["uic"], d, i):
        if dist <= 2.0 and uic not in accroche:
            j = expl[ii]
            accroche[uic] = (j, dist)
            utiles[trace_de[j]].add(rang_de[j])

    # 4. graphe : nœuds = sommets utiles ; arêtes = portions de tracé entre deux sommets utiles consécutifs
    def nid(g):
        return f"v{g}"

    G = nx.Graph()
    for k, (xy, code, st, cat) in enumerate(traces):
        seg = np.r_[0, np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
        rangs = sorted(utiles[k])
        for r1, r2 in zip(rangs, rangs[1:]):
            G.add_edge(nid(debut[k] + r1), nid(debut[k] + r2), w=seg[r2] - seg[r1], ligne=code, statut=st, categorie=cat)
    for a, b, dist, k in connecteurs:
        if not G.has_edge(nid(a), nid(b)):
            _, code, st, cat = traces[k]
            G.add_edge(nid(a), nid(b), w=dist, ligne=code, statut=st, categorie=cat)
    for uic, (j, dist) in accroche.items():
        G.add_edge(uic, nid(j), w=dist, ligne="acces_gare", statut="Exploitée", categorie="exploitee")

    # 5. export (département d'une portion = celui de la gare, fret compris, la plus proche de son milieu)
    def position(n):
        if n in accroche:
            g = gares.loc[gares["uic"] == n].iloc[0]
            return g["x_wgs84"], g["y_wgs84"]
        x, y = sommets[int(n[1:])]
        return x / KX, y / KY

    toutes = charger_gares(voyageurs_seulement=False)
    arbre_g = cKDTree(np.c_[toutes["x_wgs84"] * KX, toutes["y_wgs84"] * KY])
    noms = dict(zip(gares["uic"], gares["libelle"]))
    pos = {n: position(n) for n in G.nodes}
    nodes = pd.DataFrame([(n, "gare" if n in noms else "voie", noms.get(n), *pos[n]) for n in G.nodes],
                         columns=["id", "type", "nom", "lon", "lat"])
    lignes_e = []
    for a, b, at in G.edges(data=True):
        _, i = arbre_g.query([(pos[a][0] + pos[b][0]) / 2 * KX, (pos[a][1] + pos[b][1]) / 2 * KY])
        lignes_e.append((a, b, round(at["w"], 3), at["ligne"], at["statut"], at["categorie"], toutes["departemen"].iloc[i]))
    edges = pd.DataFrame(lignes_e, columns=["source", "target", "km", "code_ligne", "statut", "categorie", "departement"])
    nodes.to_csv(GENERE / "historique_nodes.csv", index=False, encoding="utf-8")
    edges.to_csv(GENERE / "historique_edges.csv", index=False, encoding="utf-8")
    print(f"[historique] {len(nodes)} nœuds, {len(edges)} portions, {len(accroche)} gares accrochées | km : " +
          ", ".join(f"{k} {v:.0f}" for k, v in edges.groupby("categorie")["km"].sum().items()))



# =====================================================================================
# Étape « gtfs » : réseau desservi France (une gare par nœud, une arête par paire d'arrêts consécutifs)
# =====================================================================================
def etape_gtfs():
    stations, paires = paires_gtfs(GTFS_FR, JOUR_TYPE, cle_station_fr)
    pos = stations.set_index("id")[["lon", "lat"]]
    paires["vol_oiseau_km"] = [round(vol_oiseau_km(*pos.loc[a], *pos.loc[b]), 3)
                               for a, b in zip(paires.source, paires.target)]
    stations.to_csv(GENERE / "gtfs_fr_nodes.csv", index=False, encoding="utf-8")
    paires.to_csv(GENERE / "gtfs_fr_edges.csv", index=False, encoding="utf-8")
    print(f"[gtfs] {len(stations)} gares, {len(paires)} liaisons directes")


def etape_cyjs():
    nodes = pd.read_csv(GENERE / "nodes.csv", dtype={"id": str})
    edges = pd.read_csv(GENERE / "edges.csv", dtype={"source": str, "target": str, "code_ligne": str})
    ecrire_cyjs(nodes, edges, GENERE / "reseau_ferre.cyjs", "Reseau ferre national (gares)")


# =====================================================================================
# Étape « table » : tables finales par ville, lues par le notebook
# =====================================================================================
# Codes RFN des lignes à grande vitesse (numéros de ligne relevés sur Wikipédia, articles de chaque LGV,
# et recoupés avec les longueurs mesurées dans historique_edges.csv).
LGV = {
    "752000": "Sud-Est, Rhône-Alpes, Méditerranée (Combs-la-Ville - Saint-Louis)",
    "752100": "Interconnexion Est (Villeneuve-Saint-Georges - Moisenay)",
    "431000": "Atlantique (Paris-Montparnasse - Monts)",
    "429000": "Atlantique, branche Ouest (Courtalain - Connerré)",
    "408000": "Bretagne-Pays de la Loire (Connerré - Rennes)",
    "566000": "Sud Europe Atlantique (Tours - Bordeaux)",
    "226000": "Nord (Gonesse - Lille-Frontière)",
    "216000": "Nord, branche Calais (Fretin - Fréthun)",
    "005000": "Est européenne (Vaires - Vendenheim)",
    "014000": "Rhin-Rhône, branche Est",
    "834000": "Contournement Nîmes - Montpellier",
    "837000": "Perpignan - Figueras",
}
TOLERANCE_TRACE = 0.3  # écart max admis entre longueur du tracé et longueur par points kilométriques
SEUIL_LGV = 0.5  # une liaison est « LGV » si plus de la moitié de son tracé est sur LGV
GRANDE_VITESSE_KMH = 250  # une ligne à grande vitesse est conçue pour au moins 250 km/h
ECART_VITESSE_KM = 2.0  # distance max entre une portion de voie et le tronçon de vitesse qu'on lui associe
REGION_SANS_GTFS = "11"  # Île-de-France : Transilien et RER absents du GTFS SNCF, desserte inconnue


def sans_accents(texte):
    """'Saint-Étienne' -> 'SAINT ETIENNE' : clé de rapprochement entre fichiers SNCF et INSEE."""
    import unicodedata
    texte = unicodedata.normalize("NFKD", str(texte)).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", " ", texte).strip()


def communes_insee():
    """Référentiel Etalab (codes INSEE) : communes actuelles, et table ancienne commune -> commune actuelle."""
    communes = pd.DataFrame(json.load(open(BRUT / "communes.json", encoding="utf-8")))
    deps = pd.DataFrame(json.load(open(BRUT / "departements.json", encoding="utf-8")))
    regions = pd.DataFrame(json.load(open(BRUT / "regions.json", encoding="utf-8")))
    communes["cle"] = communes["nom"].map(sans_accents)
    actuelles = communes[communes["type"] == "commune-actuelle"]
    anciennes = communes[communes["type"].isin(["commune-deleguee", "commune-associee"])]
    anciennes = anciennes.merge(actuelles[["code", "nom"]], left_on="chefLieu", right_on="code", suffixes=("", "_actuelle"))
    return actuelles, anciennes, deps, regions


def rattacher_insee(gares):
    """Ajoute code_insee, departement (code), region (code) à chaque gare, par le nom de commune et le département.
    Les communes fusionnées (commune déléguée ou associée) sont rattachées à la commune nouvelle."""
    actuelles, anciennes, deps, _ = communes_insee()
    gares = gares.copy()
    code_dep = dict(zip(deps["nom"].map(sans_accents), deps["code"]))
    gares["dep"] = gares["departement"].map(lambda nom: code_dep.get(sans_accents(nom)))
    gares["cle"] = gares["commune"].map(sans_accents)
    via_actuelle = gares.merge(actuelles[["cle", "departement", "code"]], left_on=["cle", "dep"],
                               right_on=["cle", "departement"], how="left", suffixes=("", "_x"))["code"]
    via_ancienne = gares.merge(anciennes.drop_duplicates(["cle", "departement"])[["cle", "departement", "chefLieu"]],
                               left_on=["cle", "dep"], right_on=["cle", "departement"], how="left",
                               suffixes=("", "_x"))["chefLieu"]
    gares["code_insee"] = via_actuelle.fillna(via_ancienne).to_numpy()
    infos = actuelles.set_index("code")
    gares["region"] = gares["dep"].map(dict(zip(deps["code"], deps["region"])))  # par le département : toujours connu
    gares["population_commune"] = gares["code_insee"].map(infos["population"])
    gares["commune_insee"] = gares["code_insee"].map(infos["nom"])
    return gares.drop(columns=["cle"])


def vitesse_des_voies(voies):
    """Vitesse maximale nominale (km/h) de chaque portion de voie : celle du tronçon de
    vitesse-maximale-nominale-sur-ligne, de même code ligne, dont un point du tracé est le plus proche
    du milieu de la portion (NaN au-delà de ECART_VITESSE_KM, ou pour les accès aux gares)."""
    noeuds = pd.read_csv(GENERE / "historique_nodes.csv", dtype={"id": str}).set_index("id")
    v = lire_csv_sncf(VITESSES).dropna(subset=["Geo Shape"])
    v["V_MAX"] = pd.to_numeric(v["V_MAX"], errors="coerce")
    points, vitesses = defaultdict(list), defaultdict(list)
    for shape, code, vmax in zip(v["Geo Shape"], v["CODE_LIGNE"], v["V_MAX"]):
        if pd.isna(vmax):
            continue
        geo = json.loads(shape)
        for part in geo["coordinates"] if geo["type"] == "MultiLineString" else [geo["coordinates"]]:
            for lon, lat in part:
                points[code].append((lon * KX, lat * KY))
                vitesses[code].append(vmax)
    milieux = (noeuds.loc[voies["source"], ["lon", "lat"]].to_numpy()
               + noeuds.loc[voies["target"], ["lon", "lat"]].to_numpy()) / 2 * [KX, KY]
    resultat = np.full(len(voies), np.nan)
    for code, idx in pd.Series(np.arange(len(voies))).groupby(voies["code_ligne"].to_numpy()).groups.items():
        if code in points:
            distance, j = cKDTree(np.array(points[code])).query(milieux[idx])
            resultat[idx] = np.where(distance <= ECART_VITESSE_KM, np.array(vitesses[code])[j], np.nan)
    return resultat


def etape_table():
    """villes.csv + liaisons.csv : une ligne par ville (toutes ses gares regroupées) et par liaison ville -> ville."""
    gares = pd.read_csv(GENERE / "nodes.csv", dtype={"id": str})
    liaisons = pd.read_csv(GENERE / "edges.csv", dtype={"source": str, "target": str, "code_ligne": str})
    voies = pd.read_csv(GENERE / "historique_edges.csv", dtype={"source": str, "target": str, "code_ligne": str})

    # 1. Longueur le long du tracé et part sur LGV, pour chaque liaison gare -> gare
    voies = voies[voies["categorie"] == "exploitee"].reset_index(drop=True)
    voies["vmax"] = vitesse_des_voies(voies)
    T = nx.Graph()
    for a, b, km, code, vmax in zip(voies.source, voies.target, voies.km, voies.code_ligne, voies.vmax):
        connue = not np.isnan(vmax)
        T.add_edge(a, b, km=km, lgv_km=km if code in LGV else 0.0,
                   km_vitesse=km if connue else 0.0, heures=km / vmax if connue and vmax > 0 else 0.0,
                   gv_km=km if connue and vmax >= GRANDE_VITESSE_KMH else 0.0)
    cumuls = {c: [] for c in ["km", "lgv_km", "km_vitesse", "heures", "gv_km"]}
    for a, b in zip(liaisons.source, liaisons.target):
        try:
            chemin = nx.bidirectional_dijkstra(T, a, b, weight="km")[1]
            for c in cumuls:
                cumuls[c].append(sum(T[u][v][c] for u, v in zip(chemin, chemin[1:])))
        except (nx.NodeNotFound, nx.NetworkXNoPath):
            for c in cumuls:
                cumuls[c].append(float("nan"))
    liaisons["distance_trace_km"], liaisons["lgv_km"] = cumuls["km"], cumuls["lgv_km"]
    # vitesse maximale moyenne le long du tracé (moyenne harmonique : la vitesse constante qui donne le même temps)
    heures = pd.Series(cumuls["heures"], index=liaisons.index)
    liaisons["vitesse_kmh"] = (pd.Series(cumuls["km_vitesse"], index=liaisons.index) / heures.where(heures > 0)).round(1)
    liaisons["gv_km"] = cumuls["gv_km"]
    # Contrôle de cohérence : le tracé doit donner à peu près la même longueur que les points kilométriques.
    # Un écart de plus de 30 % signale un trou dans les tracés de lignes-par-statut (le chemin fait un grand détour).
    rapport = liaisons["distance_trace_km"] / liaisons["distance_km"]
    incoherent = (rapport > 1 + TOLERANCE_TRACE) | (rapport < 1 - TOLERANCE_TRACE)
    liaisons.loc[incoherent, ["distance_trace_km", "lgv_km", "gv_km", "vitesse_kmh"]] = float("nan")
    print(f"[table] tracé incohérent avec les PK (écart > {TOLERANCE_TRACE:.0%}) : {incoherent.sum()} liaisons, tracé mis à vide")

    # 2. Une ville = une commune INSEE ; ses coordonnées sont celles de sa gare la plus fréquentée
    gares = rattacher_insee(gares)
    gares["ville"] = gares["code_insee"].fillna(gares["commune"] + "|" + gares["departement"])
    gares = gares.sort_values("total_voyageurs_2025", ascending=False, kind="stable")  # tri stable : résultat reproductible
    villes = gares.groupby("ville", sort=False).agg(
        nom=("commune_insee", "first"), commune_sncf=("commune", "first"), departement=("dep", "first"),
        region=("region", "first"), lon=("lon", "first"), lat=("lat", "first"), nb_gares=("id", "size"),
        voyageurs_2025=("total_voyageurs_2025", "sum"), population=("population_commune", "first"))
    villes["nom"] = villes["nom"].fillna(villes["commune_sncf"].str.title())
    ville_de = dict(zip(gares["id"], gares["ville"]))

    # 3. Liaisons ville -> ville : on retire les liaisons internes à une ville, on fusionne les doublons
    liaisons["source"], liaisons["target"] = liaisons["source"].map(ville_de), liaisons["target"].map(ville_de)
    liaisons = liaisons[liaisons["source"] != liaisons["target"]]
    a, b = liaisons[["source", "target"]].min(axis=1), liaisons[["source", "target"]].max(axis=1)
    liaisons = liaisons.assign(source=a, target=b).sort_values("distance_km", kind="stable")
    trains_paire = liaisons.groupby(["source", "target"])["nb_trains_jour"].sum()  # liaisons parallèles : trains additionnés
    liaisons = liaisons.drop_duplicates(["source", "target"])  # on garde la plus courte (tri par distance_km)
    liaisons = liaisons[["source", "target", "distance_km", "distance_trace_km", "vol_oiseau_km", "lgv_km", "gv_km",
                         "vitesse_kmh", "code_ligne"]]
    liaisons["nb_trains_jour"] = trains_paire.loc[list(zip(liaisons.source, liaisons.target))].to_numpy()
    liaisons["part_lgv"] = (liaisons["lgv_km"] / liaisons["distance_trace_km"]).round(3)
    liaisons["lgv"] = liaisons["part_lgv"] > SEUIL_LGV
    liaisons["part_grande_vitesse"] = (liaisons["gv_km"] / liaisons["distance_trace_km"]).round(3)  # part du tracé à 250 km/h ou plus
    liaisons["detour"] = (liaisons["distance_trace_km"] / liaisons["vol_oiseau_km"]).round(3)
    liaisons["longueur_km"] = liaisons["distance_trace_km"].fillna(liaisons["distance_km"])  # poids du graphe
    liaisons["type_ligne"] = liaisons["lgv"].map({True: "LGV", False: "classique"})  # texte : pratique dans Cytoscape
    liaisons = liaisons[["source", "target", "code_ligne", "type_ligne", "lgv", "part_lgv", "vitesse_kmh",
                         "part_grande_vitesse", "nb_trains_jour", "longueur_km", "distance_km", "distance_trace_km", "vol_oiseau_km", "detour"]]

    # 4. Attributs de desserte des villes
    trains = pd.concat([liaisons[["source", "nb_trains_jour"]].rename(columns={"source": "ville"}),
                        liaisons[["target", "nb_trains_jour"]].rename(columns={"target": "ville"})])
    villes["nb_trains_jour"] = trains.groupby("ville")["nb_trains_jour"].sum().reindex(villes.index).fillna(0)
    villes["desservie"] = (villes["nb_trains_jour"] > 0).astype("boolean")
    villes.loc[villes["region"] == REGION_SANS_GTFS, "desservie"] = pd.NA  # pas de Transilien/RER dans le GTFS
    villes["statut_desserte"] = villes["desservie"].map({True: "desservie", False: "non desservie"}).fillna("inconnue (IDF)")
    R = nx.Graph()
    R.add_nodes_from(villes.index)
    R.add_edges_from(zip(liaisons.source, liaisons.target))
    principale = max(nx.connected_components(R), key=len)
    villes["reseau_principal"] = villes.index.isin(principale)
    villes = villes.drop(columns="commune_sncf").reset_index().rename(columns={"ville": "id"})

    # 5. Contrôles : la table doit être propre avant toute analyse
    controles = {
        "villes sans code INSEE": villes["id"].str.contains(r"\|").sum(),
        "villes sans coordonnées": villes[["lon", "lat"]].isna().any(axis=1).sum(),
        "identifiants de ville en double": villes["id"].duplicated().sum(),
        "liaisons en double": liaisons.duplicated(["source", "target"]).sum(),
        "boucles (ville reliée à elle-même)": (liaisons["source"] == liaisons["target"]).sum(),
        "liaisons vers une ville inconnue": (~liaisons["source"].isin(villes["id"])
                                             | ~liaisons["target"].isin(villes["id"])).sum(),
        "liaisons sans tracé (distance_trace_km vide)": liaisons["distance_trace_km"].isna().sum(),
        "liaisons de longueur nulle": (liaisons["distance_km"] <= 0).sum(),
        "villes hors du réseau principal": (~villes["reseau_principal"]).sum(),
    }
    print("[table] contrôles :")
    for nom, n in controles.items():
        print(f"   {nom:<45} {n}")
    print(f"[table] {len(villes)} villes ({len(gares)} gares) | {len(liaisons)} liaisons | "
          f"{liaisons.lgv.sum()} liaisons LGV ({liaisons.loc[liaisons.lgv, 'distance_trace_km'].sum():.0f} km)")

    # 6. Synthèse par région et par département : part des communes qui ont une gare, villes desservies ou non
    actuelles, _, deps, regions = communes_insee()
    actuelles = actuelles[(actuelles["zone"] == "metro") & ~actuelles["departement"].isin(["2A", "2B"])]  # la Corse n'est pas sur le RFN
    for niveau, ref, fichier in [("region", regions, "regions.csv"), ("departement", deps, "departements.csv")]:
        synthese = pd.DataFrame({
            "nom": ref.set_index("code")["nom"],
            "communes": actuelles.groupby(niveau).size(),
            "population": actuelles.groupby(niveau)["population"].sum(),
            "communes_avec_gare": villes.groupby(niveau).size(),
            "villes_desservies": villes[villes["desservie"] == True].groupby(niveau).size(),
            "villes_non_desservies": villes[villes["desservie"] == False].groupby(niveau).size(),
            "population_avec_gare": villes.groupby(niveau)["population"].sum(),
        }).dropna(subset=["communes"]).fillna(0)
        synthese["part_communes_avec_gare"] = (100 * synthese["communes_avec_gare"] / synthese["communes"]).round(2)
        synthese["part_population_avec_gare"] = (100 * synthese["population_avec_gare"] / synthese["population"]).round(1)
        synthese.loc[REGION_SANS_GTFS if niveau == "region" else ["75", "77", "78", "91", "92", "93", "94", "95"],
                     ["villes_desservies", "villes_non_desservies"]] = float("nan")  # desserte inconnue en IDF
        synthese.rename_axis("code").reset_index().to_csv(GENERE / fichier, index=False, encoding="utf-8")

    villes.to_csv(GENERE / "villes.csv", index=False, encoding="utf-8")
    liaisons.to_csv(GENERE / "liaisons.csv", index=False, encoding="utf-8")
    ecrire_cyjs(villes, liaisons, GENERE / "reseau_villes.cyjs", "Reseau ferre (villes)")


ETAPES = {"gares": etape_gares, "trafic": etape_trafic,
          "historique": etape_historique, "gtfs": etape_gtfs, "table": etape_table}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--etapes", nargs="+", choices=list(ETAPES), default=list(ETAPES))
    args = ap.parse_args()
    GENERE.mkdir(parents=True, exist_ok=True)
    for nom in ETAPES:  # toujours dans l'ordre (trafic complète edges.csv)
        if nom in args.etapes:
            ETAPES[nom]()
    if {"gares", "trafic"} & set(args.etapes):
        etape_cyjs()


if __name__ == "__main__":
    main()
