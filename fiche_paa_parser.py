"""Lecture des fiches PAA par escale (« TRAFIC DE CONTENEURS ET DE VEHICULES PAR NAVIRE »).

Deux présentations existent :
  A. onglets « fiche conteneur import / export » (colonnes vides / pleins / transbordés, véhicules en colonne dédiée) ;
  B. onglets « MATRICE IMPORT / EXPORT » (Nbr 20' / 40' par type, véhicules en colonne « Nbr de Véhicules »).
Une fiche donne : navire, voyage, date d'accostage, TEU (20' + 2 × 40', vides + pleins + transbordés,
import + export) et nombre de véhicules (import + export). Pas de neufs/usagés ni de tranches.
"""
from __future__ import annotations

import io
import re

import pandas as pd

COLS = ["fichier", "navire", "voyage", "accostage", "teu", "vehicules", "remplace"]


class FicheError(ValueError):
    pass


def _s(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def _num(v) -> float:
    try:
        x = float(v)
        return 0.0 if pd.isna(x) else x
    except (TypeError, ValueError):
        return 0.0


def _date(v):
    if isinstance(v, (pd.Timestamp,)) or hasattr(v, "year"):
        return pd.Timestamp(v).normalize()
    try:
        f = float(v)
        if 30000 < f < 60000:
            return pd.Timestamp("1899-12-30") + pd.Timedelta(days=f)
    except (TypeError, ValueError):
        pass
    m = re.search(r"(\d{2})[-/.](\d{2})[-/.](\d{4})", _s(v))
    if m:
        return pd.Timestamp(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def _total_row(df: pd.DataFrame):
    for i in range(len(df)):
        for v in df.iloc[i]:
            if _s(v).upper() in ("TOTAL", "TOTAUX"):
                return i
    return None


def _vehicules_col(df: pd.DataFrame, upto: int):
    """Colonne « Nbre / Nbr de véhicules » (hors « en transbordement » et hors titre du document)."""
    for i in range(min(upto, 25)):
        for j, v in enumerate(df.iloc[i]):
            t = _s(v).upper().replace("É", "E")
            if not t.startswith("NBR") or "TRANSBORD" in t:
                continue
            if "VEHICULE" in t:
                return j
            nxt = _s(df.iloc[i + 1, j]).upper().replace("É", "E") if i + 1 < len(df) else ""
            if "VEHICULE" in nxt:
                return j
    return None


def _teu_vehicules(df: pd.DataFrame, matrice: bool) -> tuple[float, float]:
    t = _total_row(df)
    if t is None:
        return 0.0, 0.0
    r = df.iloc[t]
    g = lambda j: _num(r.iloc[j]) if j < len(r) else 0.0
    if matrice:   # vides 20'(2) 40'(3) ; pleins 20'(4) 40'(6) ; transbordés 20'(8) 40'(10)
        teu = g(2) + 2 * g(3) + g(4) + 2 * g(6) + g(8) + 2 * g(10)
    else:         # vides 20'(2,4) 40'(3,5) ; pleins 20'(6) 40'(8) ; transbordés 20'(10) 40'(12)
        teu = g(2) + g(4) + g(6) + g(10) + 2 * (g(3) + g(5) + g(8) + g(12))
    vc = _vehicules_col(df, t)
    veh = g(vc) if vc is not None else 0.0
    return teu, veh


def _entete(df: pd.DataFrame) -> dict:
    out = {"navire": "", "voyage": "", "accostage": None}
    for i in range(min(len(df), 20)):
        row = list(df.iloc[i])
        for j, v in enumerate(row):
            t = _s(v)
            low = t.lower()
            nxt = row[j + 1] if j + 1 < len(row) else None
            if low.startswith("nom du navire") or low.rstrip(" :") == "navire":
                val = (t.split(":", 1)[1].strip() if ":" in t else "") or _s(nxt)
                out["navire"] = out["navire"] or re.sub(r"[….\s]+$", "", val).strip()
            elif "voyage" in low and low.startswith("n"):
                val = (t.split(":", 1)[1].strip() if ":" in t else "") or _s(nxt)
                val = re.sub(r"[….\s]+$", "", val).strip()
                out["voyage"] = out["voyage"] or re.sub(r"\.0$", "", val)
            elif "accostage" in low:
                d = _date(t.split(":", 1)[1] if ":" in t and re.search(r"\d", t.split(":", 1)[1]) else nxt)
                out["accostage"] = out["accostage"] or d
    return out


def parse_fiche(data: bytes, name: str) -> dict:
    """Lit une fiche PAA. Lève FicheError si la présentation n'est pas reconnue."""
    try:
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None)
    except Exception as exc:
        raise FicheError(f"fichier illisible ({type(exc).__name__})") from exc
    imp = next((df for n, df in sheets.items() if "import" in n.lower()), None)
    if imp is None:
        raise FicheError("onglet import introuvable")
    exp = next((df for n, df in sheets.items() if "export" in n.lower()), None)
    matrice = any("matrice" in n.lower() for n in sheets)
    ent = _entete(imp)
    if not ent["navire"] or ent["accostage"] is None:
        raise FicheError("navire ou date d'accostage introuvable")
    teu_i, veh_i = _teu_vehicules(imp, matrice)
    teu_e, veh_e = _teu_vehicules(exp, matrice) if exp is not None else (0.0, 0.0)
    return {"fichier": name, "navire": ent["navire"], "voyage": ent["voyage"], "accostage": ent["accostage"],
            "teu": teu_i + teu_e, "vehicules": veh_i + veh_e,
            "remplace": "ANNULE ET REMPLACE" in name.upper().replace("É", "E")}


def lire_fiches(fichiers: list[tuple[str, bytes]]) -> tuple[pd.DataFrame, list[str]]:
    """(tableau des fiches, erreurs). Une fiche « ANNULE ET REMPLACE » l'emporte sur l'originale
    du même navire / voyage ; sinon la dernière par nom est conservée."""
    rows, erreurs = [], []
    for name, data in fichiers:
        try:
            rows.append(parse_fiche(data, name))
        except FicheError as exc:
            erreurs.append(f"« {name} » : {exc}")
    df = pd.DataFrame(rows, columns=COLS)
    if df.empty:
        return df, erreurs
    df["_k"] = df["navire"].str.upper().str.replace(r"\s+", " ", regex=True) + "|" + df["voyage"].astype(str)
    df = df.sort_values(["_k", "remplace", "fichier"]).drop_duplicates("_k", keep="last").drop(columns="_k")
    return df.sort_values("accostage").reset_index(drop=True), erreurs


def n1_periode(fiches: pd.DataFrame, start, end) -> dict:
    """{indicateur: valeur} de la période (dates incluses) : escales, TEU, RORO."""
    if fiches is None or fiches.empty:
        return {}
    d = fiches[(fiches["accostage"] >= pd.Timestamp(start)) & (fiches["accostage"] < pd.Timestamp(end) + pd.Timedelta(days=1))]
    if d.empty:
        return {}
    return {"escales": float(len(d)), "teu": float(d["teu"].sum()), "roro": float(d["vehicules"].sum())}
