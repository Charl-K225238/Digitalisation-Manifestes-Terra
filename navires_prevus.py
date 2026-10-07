"""Navires prévus — manifestes archivés pas encore réalisés (Stats Flash).

Fonction pure (pandas) : rapproche le journal des traitements (manifestes
archivés), les ETA déjà saisies (manifestes_suivi_escale) et les escales
réalisées de Stats Flash. Un navire sans ETA reste dans les totaux.
"""
import pandas as pd

import stats_flash_parser as sfp

FENETRE_JOURS = 10   # un navire est « réalisé » si une escale réelle débute à partir de (ETA ou date d'archivage) - 10 j
COLS = ["navire", "voyage", "eta", "vehicules", "hinterland", "statut", "archive"]


def _voy(v) -> str:
    return str(v or "").strip().upper()


def build_prevus(log: pd.DataFrame, suivi: pd.DataFrame, escales: pd.DataFrame) -> pd.DataFrame:
    if log is None or log.empty:
        return pd.DataFrame(columns=COLS)
    d = log[log["navire"].notna()].copy()
    d["kkey"] = d["navire"].map(sfp.ship_key)
    d["kvoy"] = d["voyage"].map(_voy)
    d = d[d["kkey"] != ""].sort_values("horodatage").drop_duplicates(["kkey", "kvoy"], keep="last")

    eta = {}
    if suivi is not None and not suivi.empty:
        s = suivi.copy()
        s["kkey"] = s["navire"].map(sfp.ship_key)
        s["kvoy"] = s["voyage"].map(_voy)
        s = s.sort_values("horodatage").drop_duplicates(["kkey", "kvoy"], keep="last")
        eta = {(k, v): pd.Timestamp(x) for k, v, x in zip(s["kkey"], s["kvoy"], s["date_escale"])}

    debuts = {}
    if escales is not None and not escales.empty:
        e = escales.assign(kkey=escales["navire"].map(sfp.ship_key),
                           debut=pd.to_datetime(escales["debut"], errors="coerce"))
        debuts = e.dropna(subset=["debut"]).groupby("kkey")["debut"].max().to_dict()

    rows = []
    for r in d.itertuples(index=False):
        archive = pd.Timestamp(r.horodatage).tz_localize(None) if pd.Timestamp(r.horodatage).tzinfo else pd.Timestamp(r.horodatage)
        e_ = eta.get((r.kkey, r.kvoy))
        ref = e_ if e_ is not None else archive
        dernier = debuts.get(r.kkey)
        realise = dernier is not None and dernier >= ref - pd.Timedelta(days=FENETRE_JOURS)
        statut = "Réalisé" if realise else ("Prévu" if e_ is not None else "Prévu (sans ETA)")
        rows.append({"navire": r.kkey, "voyage": r.kvoy, "eta": e_.date() if e_ is not None else None,
                     "vehicules": int(r.nb_vehicules or 0), "hinterland": int(r.nb_transit or 0),
                     "statut": statut, "archive": archive.date()})
    out = pd.DataFrame(rows, columns=COLS)
    return out.sort_values(["statut", "eta", "navire"], na_position="last").reset_index(drop=True)
