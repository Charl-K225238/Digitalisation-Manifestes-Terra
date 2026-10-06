"""Persistance des statistiques mensuelles (page Stats Flash & Reporting).

Format « long » (une ligne par année / mois / indicateur), directement
exploitable dans Power BI. Si la base Supabase n'est pas joignable (poste
local sans secrets, panne), tout reste en mémoire de session et la page le
signale : rien n'est perdu pendant la session, rien n'est conservé après.

Règles :
- valeur retenue = valeur saisie si elle existe, sinon valeur calculée ;
- un recalcul depuis les fichiers remplace la valeur calculée mais ne touche
  jamais une valeur saisie à la main ;
- l'amorçage depuis le rapport existant n'écrase jamais une valeur calculée
  depuis un fichier source ;
- chaque correction est journalisée (ancienne, nouvelle, auteur, motif).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

import tracking

COLS = ["annee", "mois", "indicateur", "nature", "valeur_calculee", "valeur_saisie",
        "source", "fichier", "motif", "agent", "horodatage"]
ESC_COLS = ["annee", "mois", "navire", "type_navire", "armateur", "debut", "fin", "duree_escale_h",
            "teu", "roro", "neufs", "usages", "transit", "paa_lt15", "paa_15_50", "paa_gt50",
            "roro_paa", "sup50_classeur", "fichier_volumes", "fichier_paa", "agent", "horodatage"]
LOG_COLS = ["horodatage", "annee", "mois", "indicateur", "nature", "valeur_calculee",
            "ancienne_valeur", "nouvelle_valeur", "motif", "agent"]
SRC_RAPPORT = "Rapport existant"


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Choix du stockage
# ---------------------------------------------------------------------------
def db_ok() -> bool:
    if "_stats_db_ok" not in st.session_state:
        try:
            conn = tracking._connect()
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM manifestes_stats_mensuelles LIMIT 1")
            conn.close()
            st.session_state["_stats_db_ok"] = True
        except Exception:
            st.session_state["_stats_db_ok"] = False
    return st.session_state["_stats_db_ok"]


def _mem(key, cols):
    if key not in st.session_state:
        st.session_state[key] = pd.DataFrame(columns=cols)
    return st.session_state[key]


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------
def load_values() -> pd.DataFrame:
    if db_ok():
        conn = tracking._connect()
        df = pd.read_sql_query(f"SELECT {', '.join(COLS)} FROM manifestes_stats_mensuelles", conn)
        conn.close()
    else:
        df = _mem("_stats_values", COLS).copy()
    if df.empty:
        return pd.DataFrame(columns=COLS + ["valeur"])
    df["valeur"] = df["valeur_saisie"].where(df["valeur_saisie"].notna(), df["valeur_calculee"])
    return df


def load_escales() -> pd.DataFrame:
    if db_ok():
        conn = tracking._connect()
        df = pd.read_sql_query(f"SELECT {', '.join(ESC_COLS)} FROM manifestes_stats_escales", conn)
        conn.close()
        return df
    return _mem("_stats_escales", ESC_COLS).copy()


def load_log() -> pd.DataFrame:
    if db_ok():
        conn = tracking._connect()
        df = pd.read_sql_query(
            f"SELECT {', '.join(LOG_COLS)} FROM manifestes_stats_corrections ORDER BY horodatage DESC", conn)
        conn.close()
        return df
    return _mem("_stats_log", LOG_COLS).copy()


# ---------------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------------
def save_calcules(annee: int, mois: int, valeurs: dict, sources: dict, fichier: str, agent: str) -> None:
    """valeurs = {indicateur: float|None}. Ne touche pas aux valeurs saisies."""
    now = _now()
    rows = [(annee, mois, k, "realise", v, sources.get(k, ""), fichier, agent, now)
            for k, v in valeurs.items() if v is not None]
    if db_ok():
        conn = tracking._connect()
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO manifestes_stats_mensuelles
                       (annee, mois, indicateur, nature, valeur_calculee, source, fichier, agent, horodatage)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (annee, mois, indicateur, nature) DO UPDATE SET
                       valeur_calculee = EXCLUDED.valeur_calculee, source = EXCLUDED.source,
                       fichier = EXCLUDED.fichier, agent = EXCLUDED.agent, horodatage = EXCLUDED.horodatage""",
                rows)
        conn.commit()
        conn.close()
        return
    df = _mem("_stats_values", COLS)
    for a, m, k, n, v, s, f, ag, t in rows:
        mask = (df["annee"] == a) & (df["mois"] == m) & (df["indicateur"] == k) & (df["nature"] == n)
        if mask.any():
            df.loc[mask, ["valeur_calculee", "source", "fichier", "agent", "horodatage"]] = [v, s, f, ag, t]
        else:
            df.loc[len(df)] = [a, m, k, n, v, None, s, f, None, ag, t]
    st.session_state["_stats_values"] = df


def seed_reference(rows: list[tuple], fichier: str, agent: str) -> int:
    """rows = [(annee, mois, indicateur, nature, valeur)] lus dans le rapport
    existant. N'écrase que des valeurs elles-mêmes issues du rapport existant."""
    now = _now()
    data = [(a, m, k, n, v, SRC_RAPPORT, fichier, agent, now) for a, m, k, n, v in rows]
    if db_ok():
        conn = tracking._connect()
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO manifestes_stats_mensuelles
                       (annee, mois, indicateur, nature, valeur_calculee, source, fichier, agent, horodatage)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (annee, mois, indicateur, nature) DO UPDATE SET
                       valeur_calculee = EXCLUDED.valeur_calculee, fichier = EXCLUDED.fichier,
                       agent = EXCLUDED.agent, horodatage = EXCLUDED.horodatage
                   WHERE manifestes_stats_mensuelles.source = %s""",
                [d + (SRC_RAPPORT,) for d in data])
        conn.commit()
        conn.close()
        return len(data)
    df = _mem("_stats_values", COLS)
    for a, m, k, n, v, s, f, ag, t in data:
        mask = (df["annee"] == a) & (df["mois"] == m) & (df["indicateur"] == k) & (df["nature"] == n)
        if mask.any():
            if (df.loc[mask, "source"] == SRC_RAPPORT).all():
                df.loc[mask, ["valeur_calculee", "fichier", "agent", "horodatage"]] = [v, f, ag, t]
        else:
            df.loc[len(df)] = [a, m, k, n, v, None, s, f, None, ag, t]
    st.session_state["_stats_values"] = df
    return len(data)


def save_saisie(annee: int, mois: int, indicateur: str, nature: str, valeur: float | None,
                motif: str, agent: str, valeur_calculee: float | None, ancienne: float | None) -> None:
    """Corrige (ou annule la correction si valeur=None) et journalise."""
    now = _now()
    if db_ok():
        conn = tracking._connect()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO manifestes_stats_mensuelles
                       (annee, mois, indicateur, nature, valeur_saisie, source, motif, agent, horodatage)
                   VALUES (%s, %s, %s, %s, %s, 'Saisie manuelle', %s, %s, %s)
                   ON CONFLICT (annee, mois, indicateur, nature) DO UPDATE SET
                       valeur_saisie = EXCLUDED.valeur_saisie, motif = EXCLUDED.motif,
                       agent = EXCLUDED.agent, horodatage = EXCLUDED.horodatage""",
                (annee, mois, indicateur, nature, valeur, motif or None, agent, now))
            cur.execute(
                f"INSERT INTO manifestes_stats_corrections ({', '.join(LOG_COLS)}) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (now, annee, mois, indicateur, nature, valeur_calculee, ancienne, valeur, motif or None, agent))
        conn.commit()
        conn.close()
        return
    df = _mem("_stats_values", COLS)
    mask = (df["annee"] == annee) & (df["mois"] == mois) & (df["indicateur"] == indicateur) & (df["nature"] == nature)
    if mask.any():
        df.loc[mask, ["valeur_saisie", "motif", "agent", "horodatage"]] = [valeur, motif or None, agent, now]
    else:
        df.loc[len(df)] = [annee, mois, indicateur, nature, None, valeur, "Saisie manuelle", None, motif or None, agent, now]
    st.session_state["_stats_values"] = df
    log = _mem("_stats_log", LOG_COLS)
    log.loc[len(log)] = [now, annee, mois, indicateur, nature, valeur_calculee, ancienne, valeur, motif or None, agent]
    st.session_state["_stats_log"] = log


def save_escales(annee: int, mois: int, detail: pd.DataFrame, fichier_volumes: str,
                 fichier_paa: str, agent: str) -> None:
    now = _now()
    d = detail.rename(columns={"paa_<15": "paa_lt15", "paa_15-50": "paa_15_50", "paa_>50": "paa_gt50"}).copy()
    d["annee"], d["mois"] = annee, mois
    d["fichier_volumes"], d["fichier_paa"], d["agent"], d["horodatage"] = fichier_volumes, fichier_paa or None, agent, now
    d = d[ESC_COLS].astype(object).where(d[ESC_COLS].notna(), None)
    if db_ok():
        conn = tracking._connect()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM manifestes_stats_escales WHERE annee = %s AND mois = %s", (annee, mois))
            cur.executemany(
                f"INSERT INTO manifestes_stats_escales ({', '.join(ESC_COLS)}) VALUES ({', '.join(['%s'] * len(ESC_COLS))})",
                [tuple(None if (v is not None and not isinstance(v, str) and pd.isna(v)) else
                       (v.to_pydatetime() if hasattr(v, "to_pydatetime") else v) for v in row)
                 for row in d.itertuples(index=False)])
        conn.commit()
        conn.close()
        return
    df = _mem("_stats_escales", ESC_COLS)
    df = df[~((df["annee"] == annee) & (df["mois"] == mois))]
    st.session_state["_stats_escales"] = pd.concat([df, d], ignore_index=True)


def archive_source(annee: int, mois: int, filename: str, data: bytes) -> str | None:
    """Conserve le fichier source chargé (preuve), si le stockage est disponible."""
    if not db_ok():
        return None
    import re
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)
    try:
        return tracking._storage_upload(
            f"stats/{annee}-{mois:02d}/{_now():%Y%m%d%H%M%S}_{safe}", data)
    except Exception:
        return None
