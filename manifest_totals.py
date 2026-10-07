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


# ── Message aux agents (affiché dans l'app ET dans un onglet du fichier généré) ──
MESSAGE_TITRE = "À LIRE — Comment vérifier les totaux de ce manifeste"


def declared_for_df(df, declared_map):
    """Total annoncé (récapitulatif) pour les fichiers présents dans df, ou
    None si l'un d'eux est inconnu (jamais de total partiel présenté comme complet)."""
    if not declared_map or "Fichier" not in df:
        return None
    total = 0
    for fn in df["Fichier"].dropna().unique():
        d = (declared_map.get(fn) or {})
        d = d.get("vehicules") if isinstance(d, dict) else d
        if d is None:
            return None
        total += d
    return total


def agent_message(counts=None, declared=None, sans_tranche=None) -> list:
    """Lignes de texte (français) expliquant comment lire les totaux.
    counts : résultat de vehicle_counts(df) (facultatif) ; declared : total
    annoncé par le récapitulatif (facultatif) ; sans_tranche : nb de véhicules
    sans poids/volume exploitable (classification)."""
    L = [
        "1. Ne comparez PAS le total de la ligne « TOTALS » du récapitulatif de fin de manifeste "
        "(« Summary Totals ») au nombre de véhicules : cette ligne mélange conteneurs, MAFI, "
        "marchandises générales et véhicules.",
        "2. Total véhicules du manifeste = LM CARGO + E-TRUCKS + C+V + E-C+V (colonnes du récapitulatif). "
        "C'est la seule valeur comparable au nombre de véhicules de ce fichier.",
    ]
    if counts:
        L.append(
            f"3. Ce fichier : {counts['manifeste']} véhicules « manifeste » + {counts['empiles']} empilés "
            f"(« bébé au dos ») + {counts['attelees']} remorques attelées = {counts['physique']} unités "
            f"physiques à décharger.")
    if declared is not None and counts:
        ecart = counts["manifeste"] - declared
        if ecart == 0:
            L.append(f"4. Le récapitulatif annonce {declared} véhicules : cohérent avec le fichier (écart 0).")
        else:
            L.append(
                f"4. ⚠️ Le récapitulatif annonce {declared} véhicules, le fichier en contient {counts['manifeste']} "
                f"(écart {ecart:+d}). Le détail des B/L fait foi : vérifiez les services B/L [T] et les lignes "
                f"sans poids ; le récapitulatif peut omettre des unités.")
    L += [
        "5. Les véhicules empilés et les remorques attelées n'ont ni poids ni volume propres : ils ne "
        "figurent pas dans le tableau de classification par volume. Leur détail (B/L, type, châssis) est "
        "dans l'onglet « Empilés & attelés ».",
    ]
    if sans_tranche:
        L.append(f"6. {sans_tranche} véhicule(s) « sans tranche » sont comptés dans le total mais absents du "
                 f"tableau (ni poids ni volume dans le manifeste) : à classer manuellement.")
    L += [
        "7. Transbordement = Place of Delivery renseigné hors Côte d'Ivoire. Hinterland = import transitant "
        "par la route vers le Mali, le Burkina Faso ou le Niger. Un B/L marqué [T] livré à Abidjan reste un Import.",
    ]
    return L


def stacked_detail_df(df):
    """Détail des véhicules empilés (« bébé au dos ») et remorques attelées :
    une ligne par châssis, ou UNE ligne avec « NON EXTRAIT » quand le châssis
    n'a pas été lu — jamais de ligne perdue. Ces unités sont comptées dans le
    total physique mais pas dans le total « manifeste » ni dans le tableau de
    classification (pas de poids/volume propres)."""
    import pandas as pd
    cols = ["Fichier", "BL_Numero", "Type", "Qté", "Châssis", "Marque", "Modèle", "État",
            "Chargeur", "Destinataire"]
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=cols)
    v = df[df["_cat_code"] == "V"]
    v = v[v["Type_Colis"].astype(str).str.startswith(_STACKED_PREFIXES)]
    rows = []
    for _, r in v.iterrows():
        typ = "Attelé (remorque)" if str(r["Type_Colis"]).startswith("Attelée") else "Empilé (bébé au dos)"
        base = {"Fichier": r.get("Fichier", ""), "BL_Numero": r.get("BL_Numero", ""), "Type": typ,
                "Marque": r.get("Marque", ""), "Modèle": r.get("Modele", ""), "État": r.get("Etat", ""),
                "Chargeur": r.get("Chargeur_Nom", ""), "Destinataire": r.get("Destinataire_Nom", "")}
        chs = [c.strip() for c in str(r.get("Numeros_Chassis", "") or "").split(";") if c.strip()]
        if chs:
            for c in chs:
                rows.append({**base, "Qté": 1, "Châssis": c})
        else:
            rows.append({**base, "Qté": int(r.get("Nb_Unites") or 1), "Châssis": "NON EXTRAIT — à compléter"})
    return pd.DataFrame(rows, columns=cols)
