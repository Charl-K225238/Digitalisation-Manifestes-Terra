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
IND_CONTROLE = "controle"                       # journal : contrôle accepté sans correction
MOTIF_ACCEPTE = "Contrôle accepté : "
CORR_ESC_COLS = ["annee", "mois", "navire", "indicateur", "valeur_calculee", "valeur_retenue",
                 "motif", "precision_motif", "agent", "horodatage"]


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
@st.cache_data(ttl=300, show_spinner=False, max_entries=8)
def _cached_sql(query: str) -> pd.DataFrame:
    """Lecture Supabase mise en cache (Lot 2 fluidité) : Stats Flash et
    Activité relisaient les trois tables à chaque clic. Le cache est vidé
    après chaque écriture (voir _invalidate), donc jamais de chiffre périmé
    après un enregistrement ; la durée de 5 min couvre les écritures faites
    hors de l'app."""
    conn = tracking._connect()
    try:
        return pd.read_sql_query(query, conn)
    finally:
        conn.close()


def _read_sql(query: str) -> pd.DataFrame:
    return _cached_sql(query).copy()


def _invalidate() -> None:
    _cached_sql.clear()


def load_values() -> pd.DataFrame:
    if db_ok():
        df = _read_sql(f"SELECT {', '.join(COLS)} FROM manifestes_stats_mensuelles")
    else:
        df = _mem("_stats_values", COLS).copy()
    if df.empty:
        return pd.DataFrame(columns=COLS + ["valeur"])
    df["valeur"] = df["valeur_saisie"].where(df["valeur_saisie"].notna(), df["valeur_calculee"])
    return df


def load_escales() -> pd.DataFrame:
    if db_ok():
        return _read_sql(f"SELECT {', '.join(ESC_COLS)} FROM manifestes_stats_escales")
    return _mem("_stats_escales", ESC_COLS).copy()


def load_log() -> pd.DataFrame:
    if db_ok():
        return _read_sql(
            f"SELECT {', '.join(LOG_COLS)} FROM manifestes_stats_corrections ORDER BY horodatage DESC")
    return _mem("_stats_log", LOG_COLS).copy()


def load_corr_escales() -> pd.DataFrame:
    """Corrections par escale (une ligne par mois / navire / indicateur)."""
    if db_ok():
        try:
            return _read_sql(f"SELECT {', '.join(CORR_ESC_COLS)} FROM manifestes_stats_corr_escales")
        except Exception:   # table pas encore créée (MISE À JOUR v10) : aucune correction
            return pd.DataFrame(columns=CORR_ESC_COLS)
    return _mem("_stats_corr_esc", CORR_ESC_COLS).copy()


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
        _invalidate()
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
        _invalidate()
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
        _invalidate()
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
        _invalidate()
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


def list_sources() -> list[dict]:
    """Fichiers sources Stats Flash archivés (classeurs volumes, extraits PAA), du plus récent au plus ancien.

    Chaque élément : {path, nom, mois ("AAAA-MM"), ts (datetime UTC | None), genre}.
    Liste vide si le stockage est indisponible (jamais d'exception pour l'affichage)."""
    if not db_ok():
        return []
    import re
    import requests
    base = tracking._secret("SUPABASE_URL").rstrip("/")
    url = f"{base}/storage/v1/object/list/{tracking._STORAGE_BUCKET}"
    headers = tracking._storage_headers("application/json")

    def _ls(prefix: str) -> list[dict]:
        r = requests.post(url, headers=headers, timeout=30,
                          json={"prefix": prefix, "limit": 1000, "offset": 0,
                                "sortBy": {"column": "name", "order": "desc"}})
        return r.json() if r.status_code == 200 else []

    out = []
    try:
        for dossier in _ls("stats/"):
            mois = dossier.get("name", "")
            if not re.fullmatch(r"\d{4}-\d{2}", mois):
                continue
            for f in _ls(f"stats/{mois}/"):
                nom = f.get("name", "")
                m = re.match(r"(\d{14})_(.+)", nom)
                if not m:
                    continue
                ts = datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                propre = m.group(2)
                genre = "Extrait PAA" if "STATISTIQUES" in propre.upper() else "Classeur volumes"
                out.append({"path": f"stats/{mois}/{nom}", "nom": propre, "mois": mois, "ts": ts, "genre": genre})
    except Exception:
        return []
    return sorted(out, key=lambda x: x["ts"], reverse=True)


def save_corr_escale(annee: int, mois: int, navire: str, indicateur: str, valeur_calculee: float | None,
                     valeur_retenue: float | None, motif: str, precision: str, agent: str,
                     ancienne: float | None) -> None:
    """Corrige la contribution d'UNE escale à un indicateur (valeur_retenue=None
    annule la correction). Journalisée dans manifestes_stats_corrections avec
    le nom du navire dans le motif, comme les corrections de total."""
    now = _now()
    motif_log = f"Escale {navire} : {motif}" + (f" ({precision})" if precision else "")
    if db_ok():
        conn = tracking._connect()
        with conn.cursor() as cur:
            if valeur_retenue is None:
                cur.execute("DELETE FROM manifestes_stats_corr_escales WHERE annee = %s AND mois = %s "
                            "AND navire = %s AND indicateur = %s", (annee, mois, navire, indicateur))
            else:
                cur.execute(
                    f"""INSERT INTO manifestes_stats_corr_escales ({', '.join(CORR_ESC_COLS)})
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (annee, mois, navire, indicateur) DO UPDATE SET
                            valeur_calculee = EXCLUDED.valeur_calculee, valeur_retenue = EXCLUDED.valeur_retenue,
                            motif = EXCLUDED.motif, precision_motif = EXCLUDED.precision_motif,
                            agent = EXCLUDED.agent, horodatage = EXCLUDED.horodatage""",
                    (annee, mois, navire, indicateur, valeur_calculee, valeur_retenue, motif,
                     precision or None, agent, now))
            cur.execute(
                f"INSERT INTO manifestes_stats_corrections ({', '.join(LOG_COLS)}) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (now, annee, mois, indicateur, "realise", valeur_calculee, ancienne, valeur_retenue, motif_log, agent))
        conn.commit()
        _invalidate()
        conn.close()
        return
    df = _mem("_stats_corr_esc", CORR_ESC_COLS)
    df = df[~((df["annee"] == annee) & (df["mois"] == mois) & (df["navire"] == navire) & (df["indicateur"] == indicateur))]
    if valeur_retenue is not None:
        df = pd.concat([df, pd.DataFrame([[annee, mois, navire, indicateur, valeur_calculee, valeur_retenue,
                                           motif, precision or None, agent, now]], columns=CORR_ESC_COLS)],
                       ignore_index=True)
    st.session_state["_stats_corr_esc"] = df
    log = _mem("_stats_log", LOG_COLS)
    log.loc[len(log)] = [now, annee, mois, indicateur, "realise", valeur_calculee, ancienne, valeur_retenue, motif_log, agent]
    st.session_state["_stats_log"] = log


def log_acceptation(annee: int, mois: int, controle: str, agent: str) -> None:
    """Trace qu'un écart de contrôle est accepté tel quel (aucune valeur modifiée)."""
    now = _now()
    motif = MOTIF_ACCEPTE + controle
    if db_ok():
        conn = tracking._connect()
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO manifestes_stats_corrections ({', '.join(LOG_COLS)}) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (now, annee, mois, IND_CONTROLE, "realise", None, None, None, motif, agent))
        conn.commit()
        _invalidate()
        conn.close()
        return
    log = _mem("_stats_log", LOG_COLS)
    log.loc[len(log)] = [now, annee, mois, IND_CONTROLE, "realise", None, None, None, motif, agent]
    st.session_state["_stats_log"] = log
