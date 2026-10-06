"""Export Excel « prêt Power BI » : une feuille par table, chaque feuille
contenant un tableau Excel nommé (Power BI › Obtenir des données › Excel
propose directement ces tableaux). Tables plates, une ligne d'en-tête,
colonnes typées (dates en vraies dates, nombres en nombres).

Tables :
- Indicateurs   : liste des 14 indicateurs (ordre, groupe, libellé)
- Stats_mensuelles : une ligne par année / mois / indicateur / nature
- Escales       : une ligne par navire et par mois (détail des fichiers chargés)
- Corrections   : journal des corrections manuelles
- Traitements   : manifestes traités dans l'app (usage, temps de traitement)
- Calendrier    : une ligne par mois, pour relier les tables entre elles
"""
from __future__ import annotations

import io
from datetime import date

import pandas as pd

from stats_flash_builder import INDICATEURS, MOIS_COURT

TRAITEMENT_COLS = ["id", "horodatage", "agent", "service", "navire", "voyage", "type_cargo",
                   "nb_bl", "nb_vehicules", "nb_conteneurs", "nb_colis", "nb_transit",
                   "duree_traitement_sec", "verifie"]


def _dim_indicateur() -> pd.DataFrame:
    return pd.DataFrame([{"indicateur": k, "ordre": i + 1, "groupe": g, "libelle": l}
                         for i, (k, g, l) in enumerate(INDICATEURS)])


def _date_mois(a, m):
    try:
        return date(int(a), int(m), 1) if 1 <= int(m) <= 12 else None
    except Exception:
        return None


def prepare_tables(vals: pd.DataFrame, esc: pd.DataFrame, log: pd.DataFrame,
                   traitements: pd.DataFrame | None) -> dict[str, pd.DataFrame]:
    out = {"Indicateurs": _dim_indicateur()}

    v = vals.copy()
    if not v.empty:
        v["date_mois"] = [_date_mois(a, m) for a, m in zip(v["annee"], v["mois"])]
        v["est_corrigee"] = v["valeur_saisie"].notna()
        v["source"] = v["source"].where(~v["est_corrigee"], "Saisie manuelle")
        v = v[["annee", "mois", "date_mois", "indicateur", "nature", "valeur", "valeur_calculee",
               "valeur_saisie", "est_corrigee", "source", "fichier", "motif", "agent", "horodatage"]]
    out["Stats_mensuelles"] = v

    e = esc.copy()
    if not e.empty:
        e["date_mois"] = [_date_mois(a, m) for a, m in zip(e["annee"], e["mois"])]
        for c in ["roro", "roro_paa", "paa_gt50", "sup50_classeur"]:
            e[c] = pd.to_numeric(e[c], errors="coerce")
        e["ecart_roro_classeur_paa"] = e["roro"] - e["roro_paa"]
        e["ecart_sup50_paa_classeur"] = e["paa_gt50"] - e["sup50_classeur"]
        e = e.rename(columns={"transit": "hinterland"})
        e = e[["annee", "mois", "date_mois", "navire", "type_navire", "armateur", "debut", "fin",
               "duree_escale_h", "teu", "roro", "neufs", "usages", "hinterland", "paa_lt15",
               "paa_15_50", "paa_gt50", "roro_paa", "ecart_roro_classeur_paa", "sup50_classeur",
               "ecart_sup50_paa_classeur", "fichier_volumes", "fichier_paa"]]
    out["Escales"] = e

    out["Corrections"] = log.copy()

    t = traitements.copy() if traitements is not None else pd.DataFrame(columns=TRAITEMENT_COLS)
    if not t.empty:
        t = t[[c for c in TRAITEMENT_COLS if c in t.columns]].copy()
        t["horodatage"] = pd.to_datetime(t["horodatage"], utc=True).dt.tz_convert("Africa/Abidjan").dt.tz_localize(None)
        t["date_traitement"] = t["horodatage"].dt.date
        t["date_mois"] = t["horodatage"].dt.to_period("M").dt.to_timestamp().dt.date
    out["Traitements"] = t

    annees = sorted({int(a) for a in v["annee"]} if not v.empty else {date.today().year})
    a0, a1 = min(annees + [date.today().year]), max(annees + [date.today().year])
    out["Calendrier"] = pd.DataFrame([
        {"date_mois": date(a, m, 1), "annee": a, "mois_num": m, "mois": f"{MOIS_COURT[m - 1]} {a}",
         "trimestre": f"T{(m - 1) // 3 + 1}"}
        for a in range(a0, a1 + 1) for m in range(1, 13)])
    return out


def _clean_value(v):
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    if v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        if pd.isna(v):
            return None
        return (v.tz_convert("Africa/Abidjan").tz_localize(None) if v.tzinfo else v).to_pydatetime()
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def build_powerbi_workbook(tables: dict[str, pd.DataFrame]) -> bytes:
    import xlsxwriter

    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "remove_timezone": True})
    fdate = wb.add_format({"num_format": "dd/mm/yyyy"})
    fdt = wb.add_format({"num_format": "dd/mm/yyyy hh:mm"})
    for name, df in tables.items():
        ws = wb.add_worksheet(name)
        cols = list(df.columns)
        if df.empty:
            ws.write_row(0, 0, cols)
            continue
        data = []
        for row in df.itertuples(index=False):
            data.append([_clean_value(x) for x in row])
        ws.add_table(0, 0, len(data), len(cols) - 1, {
            "name": f"t_{name}", "style": "Table Style Light 9",
            "columns": [{"header": c} for c in cols], "data": data})
        for j, c in enumerate(cols):
            sample = next((r[j] for r in data if r[j] is not None), None)
            if isinstance(sample, date) and not hasattr(sample, "hour"):
                ws.set_column(j, j, 12, fdate)
            elif hasattr(sample, "hour"):
                ws.set_column(j, j, 17, fdt)
            else:
                ws.set_column(j, j, max(10, min(30, len(c) + 2)))
        ws.freeze_panes(1, 0)
    wb.close()
    return buf.getvalue()
