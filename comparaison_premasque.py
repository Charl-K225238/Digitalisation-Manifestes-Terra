"""
comparaison_premasque.py — Compare le pré-masque produit par l'app au pré-masque
saisi par un agent (même navire), châssis par châssis. Lecture seule : rien n'est
écrit en base (PR B1) ; les règles proposées seront appliquées en PR B2.

Classement de chaque écart :
  - « ignoré »            : formulation seule (mêmes mots dans un autre ordre, MODELE) ;
  - « erreur agent probable » : B/L absent du manifeste, caractère parasite dans le
                            châssis, valeur contraire à ce que le manifeste écrit ;
  - « règle proposée »    : écart régulier (même valeur app -> même valeur agent sur
                            ≥ 2 lignes et ≥ 90 % des cas) ou valeur absente côté app ;
  - « à revoir »          : le reste.
Pas de dépendance Streamlit : testable seul.
"""
import io
import re
from collections import Counter, defaultdict

import pandas as pd

import premasque_ipaki as pi

SEUIL_COHERENCE = 0.90
MIN_LIGNES = 2

# Colonnes comparées : (colonne, type, niveau de règle si l'écart est régulier)
COLONNES = [
    ("BL", "texte", None),
    ("NATURE BL", "texte", 1), ("POL IPAKI", "texte", 1), ("POD IPAKI", "texte", 1),
    # Valeurs lues au manifeste (ville, état, client) : jamais de règle générale, un écart
    # y est soit une erreur de lecture (à corriger dans le parser), soit une erreur agent.
    ("FINAL DESTINATION TETRAX", "texte", 3), ("FINAL DESTINATION IPAKI", "texte", 1),
    ("TYPE D'ACTION", "texte", 1), ("ETAT", "texte", 3), ("BLItem YardItemCode", "texte", 1),
    ("MARQUE ", "texte", 2), ("MODELE", "mots", 3), ("ANNEE DE FABRICATION ", "nombre", 3),
    ("POIDS IPAKI (TON)", "poids", 3), ("VOLUME", "volume", 3), ("CLIENT ", "texte", 3),
    ("OBSERVATION", "texte", None),
]
COLS_REGLES = ["Niveau", "Colonne", "Châssis", "Si l'app donne", "Mettre", "Lignes", "Cohérence"]
IGNORE, ERREUR_AGENT, REGLE, A_REVOIR = "ignoré", "erreur agent probable", "règle proposée", "à revoir"


def _ch(v) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(v or "").upper())


def _txt(v) -> str:
    s = "" if v is None or (isinstance(v, float) and v != v) else str(v)
    return re.sub(r"\s+", " ", s).strip().upper()


def _num(v):
    try:
        f = float(str(v).replace(",", "."))
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _egal(kind, a, b) -> bool:
    if kind in ("poids", "volume", "nombre"):
        x, y = _num(a), _num(b)
        if x is None or y is None:
            return (x is None or x == 0) and (y is None or y == 0)
        tol = {"poids": 0.002, "volume": 0.01, "nombre": 0}[kind]
        return abs(x - y) <= tol
    return _txt(a) == _txt(b)


# ── Lecture du pré-masque agent ────────────────────────────────────────────────
def lire_premasque_agent(data: bytes, nom: str = "") -> pd.DataFrame:
    """DataFrame aux colonnes du masque (libellés exacts), lignes avec châssis.
    Lit .xls (même légèrement corrompu : moteur calamine) et .xlsx."""
    try:
        raw = pd.read_excel(io.BytesIO(data), sheet_name=0, header=None, dtype=object, engine="calamine")
    except Exception:
        raw = pd.read_excel(io.BytesIO(data), sheet_name=0, header=None, dtype=object)
    # ligne d'en-tête = première ligne contenant CHÂSSIS
    entete = next((i for i in range(min(len(raw), 20))
                   if any(_txt(v) in ("CHÂSSIS", "CHASSIS") for v in raw.iloc[i].tolist())), None)
    if entete is None:
        raise ValueError("Colonne CHÂSSIS introuvable : ce fichier n'est pas un pré-masque véhicules.")
    noms = ["" if v is None or (isinstance(v, float) and v != v) else str(v) for v in raw.iloc[entete].tolist()]
    df = raw.iloc[entete + 1:].copy()
    df.columns = noms
    # rattacher les libellés de l'agent aux libellés exacts (espaces près)
    exact = {re.sub(r"\s+", " ", c).strip().upper(): c for c in pi.COLUMNS if c}
    df = df.rename(columns={c: exact.get(re.sub(r"\s+", " ", c).strip().upper(), c) for c in df.columns})
    col_ch = "CHÂSSIS" if "CHÂSSIS" in df.columns else next(c for c in df.columns if _txt(c) == "CHASSIS")
    df = df[df[col_ch].map(lambda v: bool(_ch(v)))].copy()
    # lignes d'exemple du gabarit (listes de valeurs) : châssis sans B/L
    if "BL" in df.columns:
        df = df[df["BL"].map(lambda v: bool(_txt(v)))]
    # ligne d'exemple restée d'une autre escale (gabarit agent) : autre n° Tetrax ou autre escale
    autres = pd.Series(False, index=df.index)
    for c in ("MODE DE TRANSPORT", "ESCALE IPAKI"):
        if c in df.columns:
            vals = df[c].map(_txt)
            maj = vals[vals != ""].mode()
            if len(maj):
                autres |= (vals != "") & (vals != maj.iloc[0])
    df.attrs["lignes_autre_escale"] = int(autres.sum())
    df = df[~autres].copy()
    df["_cle"] = df[col_ch].map(_ch)
    df["_chassis_brut"] = df[col_ch].astype(str)
    out = df.reset_index(drop=True)
    out.attrs["lignes_autre_escale"] = df.attrs.get("lignes_autre_escale", 0)
    return out


# ── Comparaison ────────────────────────────────────────────────────────────────
def comparer(app_rows, agent_df: pd.DataFrame) -> dict:
    app = pd.DataFrame(app_rows)
    app["_cle"] = app["CHÂSSIS"].map(_ch)
    bl_app = set(app["BL"].map(_txt))
    cles_app, cles_ag = set(app["_cle"]), set(agent_df["_cle"])
    communs = cles_app & cles_ag
    a = app.drop_duplicates("_cle").set_index("_cle")
    g = agent_df.drop_duplicates("_cle").set_index("_cle")

    ecarts, erreurs = [], []
    # erreurs agent sur le châssis lui-même
    for cle in sorted(communs):
        brut = str(g.at[cle, "_chassis_brut"]).strip()
        if _txt(brut) != cle:
            erreurs.append({"Châssis": cle, "Colonne": "CHÂSSIS", "Agent": brut,
                            "Motif": "Caractère parasite dans le châssis saisi"})
    n_cellules = n_ok = 0
    for col, kind, niveau in COLONNES:
        if col not in g.columns or col not in a.columns:
            continue
        for cle in sorted(communs):
            va, vg = a.at[cle, col], g.at[cle, col]
            n_cellules += 1
            if _egal("texte" if kind == "mots" else kind, va, vg):
                n_ok += 1
                continue
            classe, motif = A_REVOIR, ""
            if kind == "mots" and sorted(_txt(va).split()) == sorted(_txt(vg).split()):
                classe, motif = IGNORE, "Mêmes mots, autre ordre"
                n_ok += 1
            elif col == "BL" and _txt(vg) not in bl_app:
                classe, motif = ERREUR_AGENT, "B/L de l'agent absent du manifeste"
            elif col == "OBSERVATION" and not _txt(vg) and _txt(va):
                classe, motif = A_REVOIR, "Code calculé par l'app, absent chez l'agent"
            ecarts.append({"Châssis": cle, "B/L": a.at[cle, "BL"], "Colonne": col, "App": va,
                           "Agent": vg, "Classement": classe, "Motif": motif, "_niveau": niveau,
                           "_kind": kind})
    df_e = pd.DataFrame(ecarts, columns=["Châssis", "B/L", "Colonne", "App", "Agent", "Classement",
                                         "Motif", "_niveau", "_kind"])
    regles = _proposer_regles(df_e)
    erreurs += [{"Châssis": r["Châssis"], "Colonne": r["Colonne"], "Agent": r["Agent"], "Motif": r["Motif"]}
                for _, r in df_e[df_e["Classement"] == ERREUR_AGENT].iterrows()]

    absents_agent = app[app["_cle"].isin(cles_app - cles_ag)][["BL", "CHÂSSIS", "MARQUE ", "MODELE"]]
    absents_app = agent_df[agent_df["_cle"].isin(cles_ag - cles_app)]
    absents_app = absents_app[[c for c in ("BL", "CHÂSSIS", "MARQUE ", "MODELE") if c in absents_app.columns]]
    return {
        "retrouves": len(communs), "absents_agent": absents_agent.reset_index(drop=True),
        "absents_app": absents_app.reset_index(drop=True),
        "concordance": round(100 * n_ok / n_cellules, 1) if n_cellules else 100.0,
        "ecarts": df_e, "regles": regles, "erreurs_agent": pd.DataFrame(erreurs),
        "par_colonne": (df_e[df_e["Classement"] != IGNORE].groupby("Colonne").size()
                        .sort_values(ascending=False).rename("Écarts").reset_index()
                        if len(df_e) else pd.DataFrame(columns=["Colonne", "Écarts"])),
    }


def _proposer_regles(df_e: pd.DataFrame) -> pd.DataFrame:
    """Écart régulier (même valeur app -> même valeur agent) : règle niveau 1/2 ;
    valeur vide côté app : surcharge niveau 3 par châssis. Met à jour le classement."""
    regles = []
    if df_e.empty:
        return pd.DataFrame(columns=COLS_REGLES)
    cand = df_e[df_e["Classement"] == A_REVOIR]
    for col, sous in cand.groupby("Colonne"):
        niveau = sous["_niveau"].iloc[0]
        if not niveau:
            continue
        par_app = defaultdict(Counter)
        for _, r in sous.iterrows():
            par_app[_txt(r["App"])][_txt(r["Agent"])] += 1
        for v_app, agents in par_app.items():
            v_ag, n = agents.most_common(1)[0]
            # cohérence mesurée sur TOUTES les lignes où l'app donne cette valeur
            total = int((df_e["Colonne"].eq(col) & df_e["App"].map(_txt).eq(v_app)).sum())
            idx = sous.index[sous["App"].map(_txt).eq(v_app) & sous["Agent"].map(_txt).eq(v_ag)]
            if v_app and niveau in (1, 2) and n >= MIN_LIGNES and n / max(total, 1) >= SEUIL_COHERENCE:
                regles.append({"Niveau": int(niveau), "Colonne": col, "Châssis": "", "Si l'app donne": v_app,
                               "Mettre": v_ag, "Lignes": n, "Cohérence": f"{round(100 * n / max(total, 1))} %"})
                df_e.loc[idx, "Classement"] = REGLE
            elif not v_app and v_ag:
                for k in idx:
                    regles.append({"Niveau": 3, "Colonne": col, "Châssis": df_e.at[k, "Châssis"],
                                   "Si l'app donne": "", "Mettre": v_ag, "Lignes": 1, "Cohérence": "ponctuel"})
                df_e.loc[idx, "Classement"] = REGLE
    return pd.DataFrame(regles, columns=COLS_REGLES)


# ── Rapport Excel ──────────────────────────────────────────────────────────────
def rapport_xlsx(res: dict, navire: str = "", voyage: str = "") -> bytes:
    buf = io.BytesIO()
    resume = pd.DataFrame([
        ("Navire / voyage", f"{navire} / {voyage}".strip(" /")),
        ("Retrouvés des deux côtés", res["retrouves"]),
        ("Absents chez l'agent", len(res["absents_agent"])),
        ("Absents dans l'app", len(res["absents_app"])),
        ("Concordance (%)", res["concordance"]),
        ("Règles proposées", len(res["regles"])),
        ("Erreurs agent probables", len(res["erreurs_agent"])),
    ], columns=["Indicateur", "Valeur"])
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        resume.to_excel(xw, sheet_name="Résumé", index=False)
        res["par_colonne"].to_excel(xw, sheet_name="Écarts par colonne", index=False)
        res["ecarts"].drop(columns=["_niveau", "_kind"]).to_excel(xw, sheet_name="Écarts détaillés", index=False)
        res["regles"].to_excel(xw, sheet_name="Règles proposées", index=False)
        res["erreurs_agent"].to_excel(xw, sheet_name="Erreurs agent probables", index=False)
        res["absents_agent"].to_excel(xw, sheet_name="Absents chez l'agent", index=False)
        res["absents_app"].to_excel(xw, sheet_name="Absents dans l'app", index=False)
    return buf.getvalue()


# ── Garde-fou avant d'enregistrer des règles (PR B2) ─────────────────────────────
def verifier_regles(app_rows, agent_df: pd.DataFrame, regles: list) -> tuple:
    """Applique les règles candidates à une copie des lignes de l'app et recompare.
    Une règle est BLOQUÉE si elle rend faux un champ qui était juste (concordance
    perdue sur une ligne déjà conforme à l'agent). Renvoie (acceptées, bloquées)."""
    avant = comparer(app_rows, agent_df)
    faux_avant = set(zip(avant["ecarts"]["Châssis"], avant["ecarts"]["Colonne"]))
    acceptees, bloquees = [], []
    for rg in regles:
        lignes = pi.appliquer_regles([dict(r) for r in app_rows], [rg])[0]
        apres = comparer(lignes, agent_df)
        faux_apres = set(zip(apres["ecarts"]["Châssis"], apres["ecarts"]["Colonne"]))
        casses = faux_apres - faux_avant
        (bloquees if casses else acceptees).append(
            dict(rg, _casses=sorted(casses)[:5]) if casses else rg)
    return acceptees, bloquees
