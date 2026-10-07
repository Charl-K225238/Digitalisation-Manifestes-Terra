"""Hinterland par tranche de volume (< 15, 15-50, > 50 m³).

Calculé au traitement d'un manifeste (Pays_Transit + volume unitaire de chaque
ligne véhicule), conservé par navire/voyage, puis rapproché des escales de
Stats Flash. Rien n'est deviné : un véhicule sans volume est compté à part.
"""
from __future__ import annotations

import pandas as pd

import stats_flash_parser as sfp

FENETRE_JOURS = 45   # écart max entre la date de référence du manifeste (ETA ou archivage) et le début d'escale
COLS = ["navire", "voyage", "nb_lt15", "nb_15_50", "nb_gt50", "nb_sans_volume", "agent", "horodatage"]
SEUILS = (15, 50)


def compute(df_f: pd.DataFrame) -> dict | None:
    """Véhicules Import en transit par tranche, depuis le tableau des B/L d'un manifeste.
    None si aucun véhicule en transit."""
    need = {"_cat_code", "Pays_Transit", "Nb_Unites", "Volume_CBM"}
    if df_f is None or df_f.empty or not need <= set(df_f.columns):
        return None
    d = df_f[(df_f["_cat_code"] == "V") & (df_f["Pays_Transit"].fillna("").astype(str).str.strip() != "")]
    if "Nature_BL" in d.columns:
        d = d[d["Nature_BL"].fillna("Import").isin(["Import", ""])]
    if d.empty:
        return None
    out = {"nb_lt15": 0, "nb_15_50": 0, "nb_gt50": 0, "nb_sans_volume": 0}
    for nb, vol in zip(pd.to_numeric(d["Nb_Unites"], errors="coerce").fillna(0),
                       pd.to_numeric(d["Volume_CBM"], errors="coerce").fillna(0)):
        nb = int(nb)
        if nb <= 0:
            continue
        if vol <= 0:
            out["nb_sans_volume"] += nb
            continue
        u = vol / nb
        out["nb_lt15" if u < SEUILS[0] else "nb_15_50" if u <= SEUILS[1] else "nb_gt50"] += nb
    return out if sum(out.values()) else None


def save(navire: str, voyage: str, counts: dict, agent: str) -> None:
    """Enregistre (ou remplace) les tranches d'un navire/voyage. Non bloquant côté appelant."""
    from datetime import datetime, timezone
    import tracking
    conn = tracking._connect()
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO manifestes_hinterland_tranches
                   (navire, voyage, nb_lt15, nb_15_50, nb_gt50, nb_sans_volume, agent, horodatage)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (navire, voyage) DO UPDATE SET
                   nb_lt15 = EXCLUDED.nb_lt15, nb_15_50 = EXCLUDED.nb_15_50, nb_gt50 = EXCLUDED.nb_gt50,
                   nb_sans_volume = EXCLUDED.nb_sans_volume, agent = EXCLUDED.agent,
                   horodatage = EXCLUDED.horodatage""",
            (navire, voyage, counts["nb_lt15"], counts["nb_15_50"], counts["nb_gt50"],
             counts["nb_sans_volume"], agent, datetime.now(timezone.utc)))
    conn.commit()
    conn.close()


def load() -> pd.DataFrame:
    """Table vide si la base ou la table est indisponible (le Hinterland reste alors à saisir)."""
    try:
        import tracking
        conn = tracking._connect()
        df = pd.read_sql_query(f"SELECT {', '.join(COLS)} FROM manifestes_hinterland_tranches", conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame(columns=COLS)


def _voy(v) -> str:
    return str(v or "").strip().upper()


def reference(hint: pd.DataFrame, suivi: pd.DataFrame | None) -> pd.DataFrame:
    """Ajoute kkey et ref (ETA saisie si elle existe, sinon date d'archivage)."""
    if hint is None or hint.empty:
        return pd.DataFrame(columns=COLS + ["kkey", "ref"])
    h = hint.copy()
    h["kkey"] = h["navire"].map(sfp.ship_key)
    h["ref"] = pd.to_datetime(h["horodatage"], errors="coerce", utc=True).dt.tz_localize(None)
    if suivi is not None and not suivi.empty:
        s = suivi.copy()
        s["kkey"] = s["navire"].map(sfp.ship_key)
        eta = {(k, _voy(v)): pd.Timestamp(x) for k, v, x in zip(s["kkey"], s["voyage"], s["date_escale"])}
        h["ref"] = [eta.get((k, _voy(v)), r) for k, v, r in zip(h["kkey"], h["voyage"], h["ref"])]
    return h


def match_month(det: pd.DataFrame, hint_ref: pd.DataFrame) -> tuple[dict | None, pd.DataFrame, str]:
    """(totaux par tranche | None, détail par navire, note).

    Un mois n'est pré-rempli que si CHAQUE navire en transit du classeur a un
    manifeste archivé dont le total égale sa colonne DT VEH TRANSIT : sinon la
    saisie reste à l'agent (pas de total partiel présenté comme complet)."""
    rows, problemes = [], []
    cible = det[pd.to_numeric(det["transit"], errors="coerce").fillna(0) > 0]
    for _, e in cible.iterrows():
        nav, transit = e["navire"], int(round(float(e["transit"])))
        c = hint_ref[hint_ref["kkey"] == sfp.ship_key(nav)] if not hint_ref.empty else hint_ref
        debut = pd.to_datetime(e.get("debut"), errors="coerce")
        if len(c) and pd.notna(debut):
            c = c.assign(ecart=(c["ref"] - debut).abs().dt.days)
            c = c[c["ecart"] <= FENETRE_JOURS].sort_values("ecart")
        if c is None or len(c) == 0:
            problemes.append(f"{nav} : manifeste archivé introuvable")
            continue
        r = c.iloc[0]
        tot = int(r["nb_lt15"] + r["nb_15_50"] + r["nb_gt50"])
        if tot != transit:
            problemes.append(f"{nav} : manifeste {tot} véhicule(s) en transit, classeur {transit}")
            continue
        rows.append({"navire": nav, "nb_lt15": int(r["nb_lt15"]), "nb_15_50": int(r["nb_15_50"]),
                     "nb_gt50": int(r["nb_gt50"])})
    detail = pd.DataFrame(rows, columns=["navire", "nb_lt15", "nb_15_50", "nb_gt50"])
    if cible.empty:
        return None, detail, "Aucun véhicule en transit dans le classeur."
    if problemes:
        return None, detail, "Hinterland à saisir — " + " ; ".join(problemes) + "."
    return ({"lt15": int(detail["nb_lt15"].sum()), "15_50": int(detail["nb_15_50"].sum()),
             "gt50": int(detail["nb_gt50"].sum())}, detail, "")
