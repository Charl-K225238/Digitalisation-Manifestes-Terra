"""Mémoire de la Note volumes mensuels : lignes du fichier situation et
volumes des manifestes, par escale.

Stocké dans la table générique manifestes_app_kv (déjà en place : aucune
migration Supabase). Clés :
  « nv_sit:<NAVIRE>|<VOYAGE> »  -> dernière ligne lue du fichier situation
  « nv_man:<NAVIRE>|<VOYAGE> »  -> volumes calculés depuis les manifestes
La ligne d'un navire TERMINÉ n'est jamais écrasée par une ligne « En cours »
ou « Prévu » plus ancienne dans un autre fichier : le réalisé prime.
Base indisponible : repli en mémoire de session (rien n'est perdu pendant
la session, l'utilisateur est prévenu par la page).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

_SIT, _MAN = "nv_sit:", "nv_man:"
_RANK = {"Prévu": 0, "En cours": 1, "Terminé": 2}


def _json_default(o):
    if isinstance(o, (datetime, pd.Timestamp)):
        return pd.Timestamp(o).isoformat()
    if pd.isna(o):
        return None
    return str(o)


def _clean(d: dict) -> dict:
    return json.loads(json.dumps(d, default=_json_default))


def _mem() -> dict:
    return st.session_state.setdefault("_nv_mem", {})


def _db_read(prefix: str) -> dict | None:
    try:
        import tracking
        conn = tracking._connect()
        with conn.cursor() as cur:
            cur.execute("SELECT key, value FROM manifestes_app_kv WHERE key LIKE %s", (prefix + "%",))
            rows = cur.fetchall()
        conn.close()
        return {k[len(prefix):]: (v if isinstance(v, dict) else json.loads(v)) for k, v in rows}
    except Exception:
        return None


def _db_write(items: dict) -> bool:
    try:
        import psycopg2.extras
        import tracking
        conn = tracking._connect()
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO manifestes_app_kv (key, value) VALUES %s
                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                [(k, json.dumps(v)) for k, v in items.items()])
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def _load(prefix: str) -> tuple[dict, bool]:
    db = _db_read(prefix)
    mem = {k[len(prefix):]: v for k, v in _mem().items() if k.startswith(prefix)}
    if db is None:
        return mem, False
    db.update(mem)                     # écritures de la session pas encore en base
    return db, True


def load_situations() -> tuple[dict, bool]:
    """{escale: ligne} et True si la base répond."""
    return _load(_SIT)


def load_manifestes() -> tuple[dict, bool]:
    return _load(_MAN)


def save_situation(navires: pd.DataFrame, fichier: str) -> tuple[int, bool]:
    """Mémorise chaque ligne du fichier (règle : le réalisé prime). Retourne
    (nombre de lignes enregistrées, True si écrit en base)."""
    if navires is None or navires.empty:
        return 0, True
    known, _ = load_situations()
    now = datetime.now(timezone.utc).isoformat()
    items = {}
    for r in navires.to_dict("records"):
        old = known.get(r["escale"])
        if old and _RANK.get(old.get("statut"), 0) > _RANK.get(r.get("statut"), 0):
            continue
        items[_SIT + r["escale"]] = _clean({**r, "_fichier": fichier, "_horodatage": now})
    _mem().update(items)
    ok = _db_write(items) if items else True
    if ok:
        for k in items:
            _mem().pop(k, None)
    return len(items), ok


_LAST = "nv_last:situation"


def save_last(situation: dict, fichier: str) -> bool:
    """Garde le dernier fichier situation lu (navires prévus, onglets CUMUL) :
    la page reste utilisable sans redéposer le fichier."""
    item = {_LAST: _clean({
        "fichier": fichier, "_horodatage": datetime.now(timezone.utc).isoformat(),
        "navires": situation["navires"].to_dict("records") if not situation["navires"].empty else [],
        "cumul": {str(m): df.to_dict("records") for m, df in situation["cumul"].items()},
    })}
    _mem().update(item)
    ok = _db_write(item)
    if ok:
        _mem().pop(_LAST, None)
    return ok


def load_last() -> dict | None:
    """Dernier fichier situation : {"navires", "cumul", "fichier", "horodatage"} ou None."""
    raw = _mem().get(_LAST)
    if raw is None:
        db = _db_read(_LAST)
        raw = (db or {}).get("")
    if not raw:
        return None

    def _df(rows):
        df = pd.DataFrame(rows)
        for c in ("debut", "fin", "sortie", "accostage"):
            if c in df:
                df[c] = pd.to_datetime(df[c], errors="coerce")
        return df

    return {"navires": _df(raw.get("navires", [])),
            "cumul": {int(m): _df(r) for m, r in raw.get("cumul", {}).items()},
            "fichier": raw.get("fichier", ""), "horodatage": raw.get("_horodatage", "")}


def save_manifeste(escale: str, volumes: dict, fichiers: list[str], conteneurs: bool, fmt: str,
                   navire_brut: str) -> bool:
    item = {_MAN + escale: _clean({"volumes": volumes, "fichiers": fichiers, "conteneurs": conteneurs,
                                   "format": fmt, "navire_brut": navire_brut, "origine": "Dépôt",
                                   "_horodatage": datetime.now(timezone.utc).isoformat()})}
    _mem().update(item)
    ok = _db_write(item)
    if ok:
        _mem().pop(_MAN + escale, None)
    return ok


# ── Manifestes des Archives (source par défaut) ──────────────────────────────
def archives_par_escale(escales: list[str]) -> dict:
    """{escale: [(fichier, chemin archivé), …]} : manifestes sources archivés
    (Pré-Masque Grimaldi, MOL / NYK, navire à grue) dont le navire / voyage
    correspond à une escale demandée. Base indisponible : {}."""
    import situation_parser as sp
    try:
        import tracking
        log = tracking.read_log()
    except Exception:
        return {}
    if log is None or log.empty or "pdf_path" not in log:
        return {}
    log = log[log["pdf_path"].notna() & (log["pdf_path"].astype(str).str.strip() != "")]
    voulues = {e: e.split("|", 1) for e in escales}
    out = {}
    for r in log.sort_values("horodatage").itertuples(index=False):
        nav, voy = sp.ship_key(r.navire), sp.voyage_key(r.voyage)
        for e, (en, ev) in voulues.items():
            if nav == en and (not ev or not voy or voy in ev or ev in voy):
                lst = out.setdefault(e, [])
                if r.pdf_path not in [p for _, p in lst]:
                    lst.append((str(r.fichier or ""), str(r.pdf_path)))
    return out


def charger_archives(escales: list[str], lire, progress=None, force: bool = False) -> dict:
    """Lit (une seule fois) les manifestes archivés des escales et mémorise
    leurs volumes (clé nv_man, origine « Archives »). Un manifeste déposé à
    la main sur la page n'est jamais écrasé. `lire(nom, données)` = lecture
    d'un manifeste (note_volumes.lire_manifeste). Retourne {escale: message}
    pour les fichiers illisibles."""
    import tracking
    from note_volumes import add_volumes
    deja, _ = load_manifestes()
    a_lire = archives_par_escale(escales)
    erreurs, n_tot = {}, sum(len(v) for v in a_lire.values()) or 1
    fait = 0
    for esc, fichiers in a_lire.items():
        chemins = sorted(p for _, p in fichiers)
        old = deja.get(esc) or {}
        if old.get("origine") == "Dépôt" or (not force and old.get("archives") == chemins):
            fait += len(fichiers)
            continue
        vols, noms, fmt, conteneurs, nav = None, [], "", False, ""
        for nom, chemin in fichiers:
            if progress:
                progress(fait / n_tot, f"Archives : {nom or chemin}")
            fait += 1
            data = tracking.get_archive_file(chemin)
            if not data:
                erreurs[esc] = f"{nom} : fichier introuvable dans les archives"
                continue
            ext = chemin.rsplit(".", 1)[-1] if "." in chemin else "pdf"
            try:
                r = lire(f"{nom.rsplit('.', 1)[0] if nom else 'manifeste'}.{ext}", data)
            except Exception as exc:
                erreurs[esc] = f"{nom} : {exc}"
                continue
            vols = add_volumes(vols, r["volumes"])
            noms.append(nom)
            fmt, conteneurs, nav = r["format"], r["conteneurs"], r["navire_brut"]
        if vols is not None:
            item = {_MAN + esc: _clean({"volumes": vols, "fichiers": noms, "conteneurs": conteneurs,
                                         "format": fmt, "navire_brut": nav, "origine": "Archives",
                                         "archives": chemins,
                                         "_horodatage": datetime.now(timezone.utc).isoformat()})}
            _mem().update(item)
            if _db_write(item):
                _mem().pop(_MAN + esc, None)
    return erreurs
