"""Flash hebdomadaire (lundi -> dimanche) — Stats Flash.

Fonctions pures (pandas) : mêmes indicateurs que le reporting mensuel, calculés
sur une période de 7 jours à partir du détail par escale déjà enregistré.
Rien n'est deviné : un indicateur sans source reste vide (« — »).
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

import hinterland_tranches as htr
import stats_flash_builder as sfb
import stats_flash_parser as sfp

JOURS_BUDGET = 30   # budget d'une période = budget mensuel × jours / 30 (règle du flash actuel)
LIBELLE_GROUPE = {"Côte d'Ivoire": "CÔTE D'IVOIRE"}


def lundi(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def bornes(monday: dt.date) -> tuple[dt.date, dt.date]:
    return monday, monday + dt.timedelta(days=6)


def n_semaine(monday: dt.date) -> int:
    return monday.isocalendar()[1]


def escales_periode(esc: pd.DataFrame, start: dt.date, end: dt.date) -> pd.DataFrame:
    """Escales dont le début tombe entre start et end inclus."""
    if esc is None or esc.empty:
        return pd.DataFrame(columns=getattr(esc, "columns", []))
    d = esc.copy()
    d["debut"] = pd.to_datetime(d["debut"], errors="coerce")
    m = (d["debut"] >= pd.Timestamp(start)) & (d["debut"] < pd.Timestamp(end) + pd.Timedelta(days=1))
    return d[m].sort_values("debut").reset_index(drop=True)


def _somme(s: pd.Series):
    v = pd.to_numeric(s, errors="coerce").sum(min_count=1)
    return None if pd.isna(v) else float(v)


def indicateurs(esc_p: pd.DataFrame, hint_ref: pd.DataFrame | None) -> tuple[dict, list[str]]:
    """({indicateur: valeur|None}, notes). Même clés que sfb.IND_KEYS."""
    out = {k: None for k in sfb.IND_KEYS}
    notes: list[str] = []
    if esc_p is None or esc_p.empty:
        return out, ["Aucune escale enregistrée sur la période (chargez le classeur du mois)."]
    out["escales"] = float(len(esc_p))
    for k in ("teu", "roro", "neufs", "usages"):
        out[k] = _somme(esc_p[k])
    avec_paa = esc_p[pd.to_numeric(esc_p["roro_paa"], errors="coerce").notna()]
    if len(avec_paa) < len(esc_p):
        notes.append(f"Tranches PAA : {len(avec_paa)} escale(s) sur {len(esc_p)} couverte(s) par un extrait PAA.")
    for t, suf in (("paa_lt15", "lt15"), ("paa_15_50", "15_50"), ("paa_gt50", "gt50")):
        out[f"t_{suf}"] = _somme(avec_paa[t]) if len(avec_paa) else None
        lolo = avec_paa[avec_paa["type_navire"] == "Lo/Lo"]
        out[f"l_{suf}"] = _somme(lolo[t]) if len(lolo) else (0.0 if len(avec_paa) else None)
    if hint_ref is not None:
        det = esc_p.rename(columns={"transit": "transit"})[["navire", "transit", "debut"]]
        tot, _, note = htr.match_month(det, hint_ref)
        if tot is not None:
            for suf in ("lt15", "15_50", "gt50"):
                out[f"h_{suf}"] = float(tot[suf])
        elif note:
            notes.append(note)
    return out, notes


def budget_periode(bud: dict, start: dt.date, end: dt.date) -> dict:
    jours = (end - start).days + 1
    return {k: v * jours / JOURS_BUDGET for k, v in bud.items() if v is not None and pd.notna(v)}


def tableau(cur: dict, n1: dict, bud: dict) -> pd.DataFrame:
    """Une ligne par indicateur : période N, même période N-1, budget, écarts."""
    rows = []
    for k, groupe, lib in sfb.INDICATEURS:
        c, p, b = cur.get(k), n1.get(k), bud.get(k)
        rows.append({"Groupe": groupe, "Indicateur": lib, "ind": k, "Période": c, "N-1": p, "Budget": b,
                     "% vs N-1": sfb._pct(c, p), "% vs budget": sfb._pct(c, b)})
    return pd.DataFrame(rows)


def _cle(nom) -> str:
    return sfp.ship_key(str(nom))


def navires_semaine(esc_p: pd.DataFrame, prevus: pd.DataFrame | None,
                    start: dt.date, end: dt.date) -> pd.DataFrame:
    """Navires de la semaine : escales enregistrées + navires prévus dont l'ETA tombe dans la semaine."""
    rows = []
    vus = set()
    if esc_p is not None and not esc_p.empty:
        for r in esc_p.itertuples(index=False):
            vus.add(_cle(r.navire))
            rows.append({"Navire": r.navire, "Type": r.type_navire or "", "TEU": r.teu, "Véhicules": r.roro,
                         "Statut": "Réalisé"})
    if prevus is not None and not prevus.empty:
        for r in prevus.itertuples(index=False):
            if r.statut == "Réalisé" or r.eta is None or pd.isna(r.eta) or r.navire in vus:
                continue
            if start <= r.eta <= end:
                rows.append({"Navire": f"{r.navire} {r.voyage}".strip(), "Type": "", "TEU": None,
                             "Véhicules": r.vehicules, "Statut": "Prévu"})
    return pd.DataFrame(rows, columns=["Navire", "Type", "TEU", "Véhicules", "Statut"])


def navires_suivants(prevus: pd.DataFrame | None, start: dt.date, end: dt.date) -> tuple[pd.DataFrame, int]:
    """(navires prévus avec ETA la semaine suivante, nombre de prévus sans ETA)."""
    cols = ["Navire", "ETA", "Véhicules"]
    if prevus is None or prevus.empty:
        return pd.DataFrame(columns=cols), 0
    a = prevus[prevus["statut"] != "Réalisé"]
    sans = int(a["eta"].isna().sum())
    s0, s1 = start + dt.timedelta(days=7), end + dt.timedelta(days=7)
    suiv = a[a["eta"].notna() & (a["eta"] >= s0) & (a["eta"] <= s1)]
    out = pd.DataFrame({"Navire": (suiv["navire"] + " " + suiv["voyage"]).str.strip(),
                        "ETA": suiv["eta"], "Véhicules": suiv["vehicules"]})
    return out.reset_index(drop=True), sans


def build_xlsx(titre: str, start: dt.date, end: dt.date, nav: pd.DataFrame, suiv: pd.DataFrame,
               tab: pd.DataFrame, notes: list[str]) -> bytes:
    """Classeur Excel du flash : navires de la semaine, semaine suivante, tableau de période."""
    import io
    import xlsxwriter
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "nan_inf_to_errors": True})
    ws = wb.add_worksheet("FLASH HEBDO")
    gras = wb.add_format({"bold": True})
    tit = wb.add_format({"bold": True, "font_size": 14})
    head = wb.add_format({"bold": True, "bg_color": "#C00000", "font_color": "white", "border": 1, "align": "center"})
    cel = wb.add_format({"border": 1})
    num = wb.add_format({"border": 1, "num_format": "#,##0"})
    dec = wb.add_format({"border": 1, "num_format": "#,##0.0"})
    pct = wb.add_format({"border": 1, "num_format": "0%"})
    ws.set_column(0, 0, 34)
    ws.set_column(1, 7, 16)
    ws.write(0, 0, titre, tit)
    ws.write(1, 0, f"Du {start:%d/%m/%Y} au {end:%d/%m/%Y}")
    r = 3

    def put(r, c, v, fmt):
        if v is None or (not isinstance(v, str) and pd.isna(v)):
            ws.write(r, c, "—", fmt)
        else:
            ws.write(r, c, v, fmt)

    if not nav.empty:
        ws.write(r, 0, "NAVIRES DE LA SEMAINE", gras); r += 1
        for c, h in enumerate(nav.columns):
            ws.write(r, c, h, head)
        r += 1
        for row in nav.itertuples(index=False):
            for c, v in enumerate(row):
                put(r, c, v, num if c in (2, 3) else cel)
            r += 1
        ws.write(r, 0, "TOTAL", gras)
        put(r, 2, pd.to_numeric(nav["TEU"], errors="coerce").sum(min_count=1), num)
        put(r, 3, pd.to_numeric(nav["Véhicules"], errors="coerce").sum(min_count=1), num)
        r += 2
    if not suiv.empty:
        ws.write(r, 0, "NAVIRES PRÉVUS LA SEMAINE SUIVANTE", gras); r += 1
        for c, h in enumerate(suiv.columns):
            ws.write(r, c, h, head)
        r += 1
        for row in suiv.itertuples(index=False):
            put(r, 0, row[0], cel)
            put(r, 1, row[1].strftime("%d/%m/%Y") if pd.notna(row[1]) else None, cel)
            put(r, 2, row[2], num)
            r += 1
        r += 1
    t = tab.dropna(subset=["Période", "N-1", "Budget"], how="all")
    if not t.empty:
        ws.write(r, 0, "INDICATEURS DE LA PÉRIODE", gras); r += 1
        for c, h in enumerate(["", "Période", "Même période N-1", "Budget", "% vs N-1", "% vs budget"]):
            ws.write(r, c, h, head)
        r += 1
        groupe = None
        for row in t.itertuples(index=False):
            if row.Groupe != groupe:
                groupe = row.Groupe
                ws.write(r, 0, LIBELLE_GROUPE.get(groupe, groupe.upper()), gras); r += 1
            ws.write(r, 0, row.Indicateur, cel)
            put(r, 1, row[3], dec if row.ind == "teu" else num)
            put(r, 2, row[4], num)
            put(r, 3, row[5], dec)
            put(r, 4, row[6], pct)
            put(r, 5, row[7], pct)
            r += 1
        r += 1
    for n in notes:
        ws.write(r, 0, n); r += 1
    wb.close()
    return buf.getvalue()
