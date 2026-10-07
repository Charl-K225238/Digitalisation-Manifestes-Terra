"""Contrôle de cohérence des totaux d'un manifeste Grimaldi.

Un agent qui ne regarde que « le total » doit comprendre d'où viennent les
écarts. Trois notions sont donc séparées :

* véhicules du MANIFESTE : ce que le manifeste annonce lui-même dans son
  récapitulatif (« Summary Totals » : LM CARGO + E-TRUCKS + C+V + E-C+V) ;
* véhicules EMPILÉS / ATTELÉS : « bébés au dos » et remorques attelées. Le
  manifeste ne les compte pas à part (ils sont portés par un autre véhicule) et
  ils n'ont ni poids ni volume propres : ils ne peuvent pas entrer dans le
  tableau de classification par volume ;
* total PHYSIQUE : manifeste + empilés/attelés = unités réellement à
  décharger (c'est ce que produit le parseur).
"""
from __future__ import annotations

import io
import re

import pdfplumber

_STACKED_PREFIXES = ("Empilée", "Attelée")


def _num(x) -> int:
    m = re.match(r"\s*(\d+)", str(x or ""))
    return int(m.group(1)) if m else 0


def declared_vehicle_total(pdf_source) -> dict:
    """Lit les lignes « TOTALS » du récapitulatif (une par section POL) et
    retourne {"vehicules": int|None, "par_pol": {POL: int}}. None si le
    récapitulatif est absent/illisible (jamais de valeur inventée)."""
    try:
        fh = io.BytesIO(pdf_source) if isinstance(pdf_source, (bytes, bytearray)) else pdf_source
        if hasattr(fh, "seek"):
            fh.seek(0)
        par_pol, pol, total, found = {}, "", 0, False
        with pdfplumber.open(fh) as pdf:
            for page in pdf.pages[-4:]:          # le récapitulatif est en fin de rapport
                for line in (page.extract_text() or "").split("\n"):
                    s = line.strip()
                    m = re.match(r"^\|?\s*POL\s*:\s*(.+?)\s*\|*$", s)
                    if m:
                        pol = m.group(1).strip()
                        continue
                    cells = [c.strip() for c in s.strip("|").split("|")]
                    if not cells or cells[0].upper() != "TOTALS" or len(cells) < 9:
                        continue
                    # de la fin : E-C+V, C+V, E-TRUCKS(LM,Qty), LM CARGO(LM,Qty)...
                    # les paires sont (Qty, mesure) : la quantité est avant la mesure.
                    n = (_num(cells[-1]) + _num(cells[-2]) + _num(cells[-4]) + _num(cells[-6]))
                    par_pol[pol or "?"] = par_pol.get(pol or "?", 0) + n
                    total += n
                    found = True
        return {"vehicules": total if found else None, "par_pol": par_pol}
    except Exception:
        return {"vehicules": None, "par_pol": {}}


def vehicle_counts(df) -> dict:
    """Compteurs de véhicules d'un DataFrame structuré (records_to_dataframe)."""
    v = df[df["_cat_code"] == "V"]
    tc = v["Type_Colis"].astype(str)
    stacked_mask = tc.str.startswith(_STACKED_PREFIXES)
    empile = int(v.loc[stacked_mask & tc.str.startswith("Empilée"), "Nb_Unites"].sum())
    attele = int(v.loc[stacked_mask & tc.str.startswith("Attelée"), "Nb_Unites"].sum())
    manifeste = int(v.loc[~stacked_mask, "Nb_Unites"].sum())
    return {"manifeste": manifeste, "empiles": empile, "attelees": attele,
            "physique": manifeste + empile + attele}


def coherence_report(df, declared) -> dict:
    """Compare le total parsé « manifeste » au total annoncé par le manifeste.
    statut : "ok" | "ecart" | "inconnu" (récapitulatif absent)."""
    c = vehicle_counts(df)
    d = declared.get("vehicules") if declared else None
    if d is None:
        statut, ecart = "inconnu", None
    else:
        ecart = c["manifeste"] - d
        statut = "ok" if ecart == 0 else "ecart"
    return {**c, "declare": d, "ecart": ecart, "statut": statut}


def bl_discrepancies(df) -> list:
    """B/L portant des véhicules empilés/attelés (explication de l'écart
    entre total physique et total manifeste) : [(BL, nb)]."""
    v = df[df["_cat_code"] == "V"]
    m = v["Type_Colis"].astype(str).str.startswith(_STACKED_PREFIXES)
    g = v[m].groupby("BL_Numero")["Nb_Unites"].sum()
    return [(bl, int(n)) for bl, n in g.items()]
