"""
boeckmans_manifest_parser.py — Manifeste « CARGO MANIFEST » de l'agence Boeckmans
(ligne EURO AFRICA, navires ESL ; ex. ESL AFRICA voyage 48 Antwerp → Abidjan).

Mise en page (PDF texte, colonnes repérées sur les en-têtes de chaque page) :
  SHIPPER(SH); CONSIGNEE(CO); NOTIFY(NF) | B/L NR. | CONTAINER NRS | QTY. |
  KIND OF PACKAGES; DESCR. OF GOODS | GROSS W. kg | MEAS. M3 | …
Nombres au format européen : « 293.800 » = 293 800 kg, « 1.134,890 » = 1 134,890 m³.
« Total BL » donne poids et volume du B/L ; « RECAP VOYAGE / PACKAGES : n » sert de
contrôle global. Sortie : même DataFrame pré-masque que les parsers ALIS / grue, pour
réutiliser le pré-masque Ipaki, la vérification et la comparaison sans code dédié.

Règles validées (11/11) : « N PIECES … » avec moins de châssis que de pièces = véhicules
(poids et volume du B/L entier) + colis annexes sans poids ; « DISMANTLED » = EPM ;
état non écrit = USAGÉ par défaut (proposé au passage, règle habituelle).
"""
from __future__ import annotations

import io
import re

import pandas as pd
import pdfplumber

import vehicle_models as vm
from mol_manifest_parser import ManifestFormatError, ManifestReadError

MARKERS = ("BOECKMANS", "EURO AFRICA")
VIN_RE = re.compile(r"(?<![A-Z0-9])(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{17}(?![A-Z0-9])")
BL_RE = re.compile(r"^[A-Z]{3,}[A-Z0-9]*\d{3,}[A-Z]?$")
NUM_RE = re.compile(r"^\d{1,3}(?:\.\d{3})*(?:,\d+)?$|^\d+(?:,\d+)?$")
_Y_TOL = 2.5


def _num_eu(s: str):
    s = str(s or "").strip()
    if not NUM_RE.match(s):
        return None
    return float(s.replace(".", "").replace(",", "."))


def _open(src):
    try:
        return pdfplumber.open(io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src)
    except Exception as e:                                  # PDF corrompu / chiffré
        raise ManifestReadError(f"PDF illisible ({type(e).__name__}).") from e


def is_boeckmans_format(src) -> bool:
    try:
        with _open(src) as pdf:
            t = (pdf.pages[0].extract_text() or "").upper() if pdf.pages else ""
    except Exception:
        return False
    return "CARGO MANIFEST" in t and any(m in t for m in MARKERS) and "B/L NR" in t


def _lines(page):
    """Mots regroupés en lignes (même hauteur), triés de gauche à droite."""
    rows = []
    for w in sorted(page.extract_words(), key=lambda w: (round(w["top"]), w["x0"])):
        if rows and abs(rows[-1][0] - w["top"]) <= _Y_TOL:
            rows[-1][1].append(w)
        else:
            rows.append([w["top"], [w]])
    return rows


def _colonnes(words):
    """Bornes x des colonnes, lues sur les en-têtes de la page."""
    x = {}
    for w in words:
        t = w["text"].upper()
        if t == "B/L" and "bl" not in x:
            x["bl"] = w["x0"]
        elif t.startswith("CONTAINER") and "cont" not in x:
            x["cont"] = w["x0"]
        elif t == "QTY." and "qty" not in x:
            x["qty"] = w["x0"]
        elif t == "KIND" and "desc" not in x:
            x["desc"] = w["x0"]
        elif t == "GROSS" and "gw" not in x:
            x["gw"] = w["x0"]
        elif t == "MEAS." and "meas" not in x:
            x["meas"] = w["x0"]
        elif t == "TYPE" and "fin" not in x and "meas" in x:
            x["fin"] = w["x0"]
    return x if {"bl", "qty", "desc", "gw", "meas"} <= set(x) else None


def _col(w, x) -> str:
    c = w["x0"] + 1
    if c < x["bl"]:
        return "party"
    if c < x.get("cont", x["qty"]):
        return "bl"
    if c < x["qty"] - 2:
        return "cont"
    if c < x["desc"] - 1:
        return "qty"
    if c < x["gw"] - 4:
        return "desc"
    if c < x["meas"] - 4:
        return "gw"
    if c < x.get("fin", x["meas"] + 60):
        return "meas"
    return "fin"


def _meta(text: str) -> dict:
    g = lambda pat: (re.search(pat, text, re.I | re.M).group(1).strip()
                     if re.search(pat, text, re.I | re.M) else "")
    return {"navire": g(r"VESSEL:\s*(.+?)(?=\s+VOYAGE:|\s+LLOYDS|\s{2,}|$)"),
            "voyage": g(r"VOYAGE:\s*(\S+)"),
            "pol": g(r"POL:\s*([A-Za-z][A-Za-z .'-]+?)(?:\s+POD:|$)"),
            "pod": g(r"POD:\s*([A-Za-z][A-Za-z .'-]+?)(?:\s+ARRIVAL|\s+FIN|$)")}


def parse_boeckmans_manifest(src, source_label: str = "", progress_cb=None):
    """Renvoie (df, avertissements, meta) comme les parsers ALIS."""
    with _open(src) as pdf:
        first = pdf.pages[0].extract_text() or "" if pdf.pages else ""
        if not first.strip():
            raise ManifestReadError("PDF sans texte (scan) : utilisez l'onglet « Manifeste scanné ».")
        if not is_boeckmans_format(src):
            raise ManifestFormatError("Ce PDF n'est pas un manifeste Boeckmans (ligne EURO AFRICA).")
        meta = _meta(first)
        records, cur, total_pkg = [], None, None
        section = None
        n = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            if progress_cb:
                progress_cb(i, n)
            mots = page.extract_words()
            debuts = [w["top"] for w in mots if w["text"].upper() in ("SH:", "SUBTOTAL", "TOTAL")]
            if not debuts:
                continue
            haut = min(debuts) - 1
            x = _colonnes([w for w in mots if w["top"] < haut])     # en-têtes sur plusieurs lignes
            if x is None:
                continue
            for top, words in _lines(page):
                if top < haut:
                    continue
                cells = {}
                for w in words:
                    cells.setdefault(_col(w, x), []).append(w["text"])
                party = " ".join(cells.get("party", []))
                bl = " ".join(cells.get("bl", []))
                desc = " ".join(cells.get("desc", []))
                if party.upper().startswith(("TOTAL BL", "SUBTOTAL", "TOTAL VOYAGE")):
                    if "RECAP VOYAGE" in desc.upper() or party.upper().startswith("TOTAL VOYAGE"):
                        section = "voyage"
                        continue
                    if party.upper().startswith("TOTAL BL") and cur is not None:
                        cur["weight"] = _num_eu("".join(cells.get("gw", []))) or cur["weight"]
                        cur["volume"] = _num_eu("".join(cells.get("meas", []))) or cur["volume"]
                        records.append(cur)
                        cur = None
                    section = "total"
                    continue
                if section == "total":
                    ligne = " ".join(w["text"] for w in words)
                    if "RECAP VOYAGE" in ligne.upper():
                        section = "voyage"
                        continue
                    if not (bl and BL_RE.match(bl)):
                        continue
                    section = None
                if section == "voyage":
                    m = re.search(r"PACKAGES\s*:?\s*(\d+)", " ".join(w["text"] for w in words), re.I)
                    if m:
                        total_pkg = int(m.group(1))
                    if bl and BL_RE.match(bl):
                        section = None
                    else:
                        continue
                if bl and BL_RE.match(bl):
                    cur = {"bl": bl, "qty": None, "desc": [], "parties": {"SH": [], "CO": [], "NF": []},
                           "weight": None, "volume": None, "containers": []}
                    section = None
                if cur is None:
                    continue
                if cells.get("qty") and cur["qty"] is None:
                    q = "".join(cells["qty"])
                    cur["qty"] = int(q) if q.isdigit() else None
                if cur["weight"] is None and cells.get("gw"):
                    cur["weight"] = _num_eu("".join(cells["gw"]))
                    cur["volume"] = _num_eu("".join(cells.get("meas", [])))
                if cells.get("cont"):
                    cur["containers"].append(" ".join(cells["cont"]))
                if desc:
                    cur["desc"].append(desc)
                if party:
                    m = re.match(r"^(SH|CO|NF):\s*(.*)$", party)
                    if m:
                        cur["_p"] = m.group(1)
                        party = m.group(2)
                    if cur.get("_p") and party:
                        cur["parties"][cur["_p"]].append(party)
        if cur is not None:
            records.append(cur)
    return _rows(records, meta, total_pkg)


def _rows(records, meta, total_pkg):
    warnings, rows = [], []
    n_veh = n_colis = 0
    for r in records:
        joined = " ".join(r["desc"]).upper()
        chassis = list(dict.fromkeys(VIN_RE.findall(joined)))
        qty = r["qty"] or len(chassis) or 1
        co = r["parties"]["CO"][0] if r["parties"]["CO"] else ""
        nf = r["parties"]["NF"][0] if r["parties"]["NF"] else ""
        client = nf if re.match(r"TO\s+(THE\s+)?ORDER", co, re.I) and nf else co
        adresse = " ".join(r["parties"]["CO"] + r["parties"]["NF"])
        dest = "ABIDJAN" if re.search(r"ABIDJAN|ABJ\b|COTE D.?IVOIRE", adresse, re.I) else meta["pod"].upper()
        premiere = r["desc"][0] if r["desc"] else ""
        libelle = re.sub(r"^\d*\s*(PIECES?|PACKAGES?|UNITS?|PKGS?)\s+", "", premiere, flags=re.I)
        libelle = re.sub(r"\s*-\s*PARTLY(\s+DISMANTLED.*)?$", "", libelle, flags=re.I).strip() or "Marchandises"
        dismantled = "DISMANTL" in joined or "DISMOUNT" in joined
        base = {"NATURE BL": "Import", "POL TETRAX": meta["pol"].upper(), "POD TETRAX": meta["pod"].upper(),
                "FINAL DESTINATION TETRAX": dest, "TYPE / TAILLE": "", "BL": r["bl"], "TYPE D'ACTION": "",
                "CLIENT": client, "_qty_declaree": qty, "_type_declare": "PACKAGE",
                "_ctrl_qty": qty, "_ctrl_weight": r["weight"]}
        etat = "Neuf" if vm.NEW_ETAT_RE.search(joined) else ("Usager" if re.search(r"\bUSED\b", joined) else "")
        if chassis:
            marque = vm.find_brand(joined, " ".join(r["parties"]["SH"]), chassis) or ""
            k = len(chassis)
            for j, ch in enumerate(chassis):
                p = round((r["weight"] or 0) / k) if r["weight"] else None
                if p is not None and j == k - 1:
                    p = round(r["weight"]) - p * (k - 1)
                modele = ch[3:8].lstrip("0") + " " + libelle if ch.startswith("CAT0") else libelle
                rows.append({**base, "CATEGORIE": "Vehicule", "POIDS TETRAX (KG)": p,
                             "VOLUME TETRAX": round(r["volume"] / k, 3) if r["volume"] else None,
                             "MARQUE": marque, "MODELE": modele.strip(),
                             "MARQUE & MODELE": f"{marque} {modele}".strip(), "ETAT": etat,
                             "ANNEE DE FABRICATION": None,
                             "OBSERVATION": "engin démonté (DISMANTLED) - EPM" if dismantled else "",
                             "CHÂSSIS": ch})
            n_veh += k
        n_annexes = qty - len(chassis) if qty > len(chassis) else 0
        if n_annexes:
            n_colis += n_annexes
            warnings.append(f"B/L {r['bl']} : {qty} colis déclarés pour {len(chassis)} châssis : "
                            f"{n_annexes} colis annexes ajoutés, poids compris dans les véhicules."
                            if chassis else f"B/L {r['bl']} : {qty} colis sans châssis.")
            for _ in range(n_annexes):
                rows.append({**base, "CATEGORIE": "Colis",
                             "POIDS TETRAX (KG)": None if chassis else (round(r["weight"] / n_annexes) if r["weight"] else None),
                             "VOLUME TETRAX": None if chassis else (round(r["volume"] / n_annexes, 3) if r["volume"] else None),
                             "MARQUE": "", "MODELE": f"Pièce de {libelle}" if chassis else libelle,
                             "MARQUE & MODELE": f"Pièce de {libelle}" if chassis else libelle, "ETAT": "",
                             "ANNEE DE FABRICATION": None, "OBSERVATION": "colis sans chassis", "CHÂSSIS": ""})
    df = pd.DataFrame(rows)
    if len(df):
        df.insert(0, "NBRE", range(1, len(df) + 1))
    if total_pkg is not None and total_pkg != n_veh + n_colis:
        warnings.insert(0, f"Total manifeste {total_pkg} colis ≠ {n_veh} véhicules + {n_colis} colis extraits "
                           "— vérifier les B/L.")
    poids = sum(r["weight"] or 0 for r in records)
    meta = {**meta, "total_declare": total_pkg, "nb_bl": len(records), "poids_total": poids,
            "nb_breakbulk": n_colis}
    return df, warnings, meta
