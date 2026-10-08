"""État des données Stats Flash : ce qui est disponible, ce qui reste à compléter.

Fonctions pures (pandas) : à partir des valeurs mensuelles et du détail par
escale, construit une grille « donnée × mois » et la liste des données
manquantes, avec leur effet sur le rapport et l'endroit où les fournir.
Aucune donnée n'est devinée : une case n'est « disponible » que si une valeur
issue de la bonne source est en base.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

import stats_flash_builder as sfb
import stats_flash_parser as sfp

OK, TODO, OPT = "ok", "todo", "opt"
RACINE = "PLANIFICATION & REPORTING - TRACK & REPORTING › DOSSIERS REPORTING › REPORTING"

# Données suivies : libellé, sous-titre, dossier SharePoint, nom du fichier, apport
DONNEES = {
    "classeur": ("Classeur volumes (ELVIS)", "Escales, TEU, RORO, Hinterland",
                 f"{RACINE} › STATS FLASH VOLUMES TCS BOLS MAFIS ET VEHICULES OPN › <AAAA> › <MOIS> "
                 "(ou PAA - KOUAI EDEN SUPER U › Dossiers PAA <Mois> <AAAA>)",
                 "VOLUMES D'ACTIVITES <MOIS>_<AAAA>_ELVIS.xls",
                 "Apporte : escales, TEU, RORO, neufs / usagés, Hinterland"),
    "paa": ("Extrait PAA", "Tranches de volume, Lo/Lo",
            f"{RACINE} › STATISTIQUES TERRA <AAAA> (certains mois, le dossier de l'année précédente sert encore : STATISTIQUES BQP TERRA <AAAA-1>)",
            "STATISTIQUES TERRA <MOIS> <AAAA>.xls",
            "Apporte : tranches < 15, 15-50, > 50 m³ et trafic Lo/Lo"),
    "n1": ("Historique N-1", "Comparaison N-1 (Référentiel)",
           f"{RACINE} › rapport Stats Flash de l'année précédente (chemin exact à confirmer)",
           "Rapport Stats Flash <AAAA-1> (.xlsx)",
           "Apporte : mêmes mois de l'année précédente pour les écarts N-1"),
    "budget": ("Budget", "Atteinte du budget (Référentiel)",
               "Saisi une fois dans l'onglet Référentiel (pas de fichier à déposer)", "—",
               "Apporte : barres budget et taux d'atteinte"),
    "hinterland": ("Hinterland par tranche", "Depuis les manifestes traités",
                   "Aucun fichier : calculé automatiquement à chaque manifeste traité dans le Pré-Masque", "—",
                   "Apporte : répartition Hinterland par tranche de volume"),
}
BUDGET_CLES = [("escales", "Escales"), ("teu", "TEU"), ("roro", "RORO"), ("neufs", "Véhicules neufs"),
               ("usages", "Véhicules usagés"), ("hinterland", "Hinterland")]


def _date(x) -> str:
    try:
        return pd.Timestamp(x).strftime("%d/%m")
    except Exception:
        return "—"


def etat(vals: pd.DataFrame, esc: pd.DataFrame, annee: int | None = None,
         aujourd_hui: dt.date | None = None) -> dict:
    """Retourne {annee, mois: [1..n], lignes: {cle: [cellule par mois]}, manquants: [...], resume}.
    Cellule = {statut, titre, l1, l2, l3}."""
    aujourd_hui = aujourd_hui or dt.date.today()
    real = vals[(vals["nature"] == "realise") & (vals["mois"] > 0)] if vals is not None and not vals.empty else None
    if annee is None:
        annee = int(real["annee"].max()) if real is not None and not real.empty else aujourd_hui.year
    charges = sorted(set(real.loc[real["annee"] == annee, "mois"].astype(int))) if real is not None else []
    dernier = max(charges + ([aujourd_hui.month - 1] if annee == aujourd_hui.year else [12 if annee < aujourd_hui.year else 0]))
    mois = list(range(1, max(dernier, 1) + 1))
    noms = sfp.MOIS_FR

    def rows(a, m):
        if real is None:
            return pd.DataFrame()
        return real[(real["annee"] == a) & (real["mois"] == m)].set_index("indicateur")

    def esc_mois(m):
        if esc is None or esc.empty:
            return esc
        return esc[(esc["annee"] == annee) & (esc["mois"] == m)]

    lignes = {k: [] for k in DONNEES}
    manque = {k: [] for k in DONNEES}
    for m in mois:
        r, e = rows(annee, m), esc_mois(m)
        lab = f"{noms[m - 1]} {annee}"
        # Classeur des volumes
        src_v = r[r["source"] == sfb.SRC_VOLUMES] if not r.empty else r
        if not src_v.empty:
            x = src_v.iloc[0]
            nesc = len(e) if e is not None and not e.empty else None
            lignes["classeur"].append(dict(statut=OK, titre=f"Disponible · {lab}",
                                           l1=f"Fichier : {str(x.get('fichier') or '—').split(' + ')[0]}",
                                           l2=f"Chargé le {_date(x.get('horodatage'))} par {x.get('agent') or '—'}"
                                              + (f" · {nesc} escales" if nesc else ""), l3=""))
        else:
            ref = r[r["source"] == sfb.SRC_RAPPORT] if not r.empty else r
            lignes["classeur"].append(dict(
                statut=OK if not ref.empty else TODO, titre=("Disponible" if not ref.empty else "À compléter") + f" · {lab}",
                l1="Valeurs reprises du rapport existant (pas de détail par escale)" if not ref.empty else "Aucun classeur pour ce mois.",
                l2="" if not ref.empty else "Effet : escales, TEU et RORO absents du rapport.",
                l3="" if not ref.empty else "À déposer dans Charger un mois"))
            if ref.empty:
                manque["classeur"].append(m)
        # Extrait PAA
        t = r.loc[r.index.isin(["t_lt15", "t_15_50", "t_gt50"])] if not r.empty else r
        paa = t[t["source"] == sfb.SRC_PAA] if not t.empty else t
        if not paa.empty:
            x = paa.iloc[0]
            f = str(x.get("fichier") or "—")
            f = f.split(" + ")[-1] if " + " in f else f
            lignes["paa"].append(dict(statut=OK, titre=f"Disponible · {lab}", l1=f"Fichier : {f}",
                                      l2=f"Chargé le {_date(x.get('horodatage'))} par {x.get('agent') or '—'}", l3=""))
        elif not t.empty and t["valeur"].notna().any():
            lignes["paa"].append(dict(statut=OK, titre=f"Disponible · {lab}",
                                      l1=f"Tranches reprises de : {t.iloc[0].get('source') or '—'}", l2="", l3=""))
        else:
            lignes["paa"].append(dict(statut=TODO, titre=f"À compléter · {lab}", l1="Aucun extrait PAA pour ce mois.",
                                      l2="Effet : tranches et Lo/Lo masqués, contrôle classeur / PAA impossible.",
                                      l3="À déposer dans Charger un mois"))
            manque["paa"].append(m)
        # Historique N-1 (même mois)
        r1 = rows(annee - 1, m)
        if not r1.empty and r1["valeur"].notna().any():
            lignes["n1"].append(dict(statut=OK, titre=f"Disponible · {noms[m - 1]} {annee - 1}",
                                     l1=f"Source : {r1.iloc[0].get('source') or '—'}",
                                     l2=f"Enregistré le {_date(r1.iloc[0].get('horodatage'))}", l3=""))
        else:
            lignes["n1"].append(dict(statut=TODO, titre=f"À compléter · {noms[m - 1]} {annee - 1}",
                                     l1=f"Pas de valeur {annee - 1} pour ce mois.", l2="Effet : écarts N-1 masqués.",
                                     l3="Onglet Référentiel"))
            manque["n1"].append(m)
        # Hinterland par tranche (facultatif : dépend des manifestes traités)
        h = r.loc[r.index.isin(["h_lt15", "h_15_50", "h_gt50"])] if not r.empty else r
        if not h.empty and h["valeur"].notna().any():
            lignes["hinterland"].append(dict(statut=OK, titre=f"Disponible · {lab}",
                                             l1=f"Source : {h.iloc[0].get('source') or '—'}", l2="", l3=""))
        else:
            lignes["hinterland"].append(dict(statut=OPT, titre=f"Facultatif · {lab}",
                                             l1="Manifestes du mois non traités dans l'app : répartition non disponible.",
                                             l2="", l3=""))

    # Budget de l'année (une valeur annuelle par indicateur)
    b = vals[(vals["nature"] == "budget") & (vals["annee"] == annee) & (vals["mois"] == 0)] \
        if vals is not None and not vals.empty else pd.DataFrame(columns=["indicateur", "valeur"])
    bset = {k for k, v in b[["indicateur", "valeur"]].itertuples(index=False) if pd.notna(v)}
    sans_budget = [lib for k, lib in BUDGET_CLES
                   if (k == "hinterland" and not {"h_lt15", "h_15_50", "h_gt50"} <= bset) or (k != "hinterland" and k not in bset)]
    st_b = OK if len(sans_budget) < len(BUDGET_CLES) else TODO
    for m in mois:
        lignes["budget"].append(dict(
            statut=st_b, titre=("Disponible" if st_b == OK else "À compléter") + f" · {noms[m - 1]} {annee}",
            l1=f"Budget annuel {annee} saisi, réparti par mois" if st_b == OK else "Budget absent.",
            l2=("Sans budget : " + ", ".join(sans_budget)) if sans_budget and st_b == OK else
               ("Effet : barres budget masquées." if st_b == TODO else ""),
            l3="Onglet Référentiel" if st_b == TODO else ""))

    def liste(ms):
        """Mois en plages lisibles : « janvier à août, octobre »."""
        plages, deb = [], ms[0]
        for a, b in zip(ms, ms[1:] + [None]):
            if b != a + 1:
                plages.append(noms[deb - 1] if deb == a else
                              f"{noms[deb - 1]} et {noms[a - 1]}" if a == deb + 1 else f"{noms[deb - 1]} à {noms[a - 1]}")
                deb = b
        return ", ".join(plages)

    manquants = []
    if manque["classeur"]:
        manquants.append(dict(quoi=f"Classeur volumes · {liste(manque['classeur'])} {annee}",
                              effet="Escales, TEU, RORO et Hinterland absents pour ces mois.", ou="Déposer dans Charger un mois"))
    if manque["paa"]:
        manquants.append(dict(quoi=f"Extrait PAA · {liste(manque['paa'])} {annee}",
                              effet="Tranches de volume et Lo/Lo masquées ; contrôle classeur / PAA impossible.",
                              ou="Déposer dans Charger un mois"))
    if manque["n1"]:
        manquants.append(dict(quoi=f"Historique {annee - 1} · {liste(manque['n1'])}",
                              effet="Écarts vs N-1 masqués pour ces mois.", ou="Onglet Référentiel"))
    if sans_budget:
        manquants.append(dict(quoi=f"Budget {annee} · " + ", ".join(sans_budget),
                              effet="Pas de barre budget ni de taux d'atteinte pour ces indicateurs.", ou="Onglet Référentiel"))

    cells = [c for v in lignes.values() for c in v]
    n_ok = sum(c["statut"] == OK for c in cells)
    n_todo = sum(c["statut"] == TODO for c in cells)
    n_opt = sum(c["statut"] == OPT for c in cells)
    return dict(annee=annee, mois=mois, lignes=lignes, manquants=manquants,
                resume=f"{n_ok} disponibles · {n_todo} à compléter" + (f" · {n_opt} facultatives" if n_opt else ""))


def rappel_court(e: dict) -> str:
    """Une phrase listant les données à compléter (vide si tout est là)."""
    return "; ".join(m["quoi"] for m in e["manquants"])
