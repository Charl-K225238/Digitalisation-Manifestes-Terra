"""
Parseur manifeste EUKOR (« GENERAL CARGO MANIFEST », EUKOR Car Carriers) ->
DataFrame au format pré-masque IPAKI (mêmes colonnes que mol_manifest_parser,
pour réutiliser generate_premasque_excel() et l'écran de vérification tels quels).

Référence : LAKE QARAOUN IF608 (10/2026), 11 pages, 15 B/L, 232 unités.

Structure source : PDF texte, tableau à 4 colonnes (pdfplumber.extract_tables) :
  col0 = « EUKO » + N° B/L (ex. KRCI2108183) — vide sur une ligne de suite
  col1 = (S) chargeur / (C) destinataire / (N) notify
  col2 = Marks & Description (texte libre, parfois tableau N°/MODELE/VIN/MOTEUR)
  col3 = « 44,300 KGS 140.400 CBM 3 UNITS » puis « Chassis No. : » puis des
         groupes « AUTO|RORO|BREAKBULK : <n> Q'TY <description> » suivis des
         n° de châssis (2 par ligne).
En-tête de page : Port of Loading / Port of Discharge (varie selon la page).
Une ligne dont col0 est vide prolonge le B/L précédent (saut de page).

La colonne 3 est la source de vérité des unités : liste structurée et
quantifiée, contrairement à la description libre. BREAKBULK (caisses
d'outils, godet...) = colis : jamais une ligne véhicule, signalé à part.
"""
from __future__ import annotations

import io
import re

import pandas as pd
import pdfplumber

from mol_manifest_parser import ManifestReadError, ManifestFormatError, OUTPUT_COLUMNS

FORMAT_MARKERS = ("GENERAL CARGO MANIFEST", "EUKO")  # logo EUKOR = image ; « EUKO » = préfixe B/L

BL_RE = re.compile(r'EUKO\s*\n?\s*([A-Z]{4}\d{6,})')
TOTALS_RE = re.compile(r'([\d,]+(?:\.\d+)?)\s*KGS\s+([\d,]+(?:\.\d+)?)\s*CBM\s+(\d+)\s*UNITS?', re.I)
GROUP_RE = re.compile(r"^(AUTO|RORO|BREAKBULK)\s*:\s*(\d+)\s*Q'?TY\s*(.*)$", re.I)
CHASSIS_TOKEN_RE = re.compile(r'^[A-Z0-9][A-Z0-9\-]{4,24}$')
VIN_RE = re.compile(r'\b([A-HJ-NPR-Z0-9]{17})\b')
# Tableau de la description : « 1 HFC7151EATV LJ12EKR25T4022207 T3341909 »
MODEL_VIN_ENGINE_RE = re.compile(r'^\d+\s+(\S+)\s+([A-HJ-NPR-Z0-9]{17})\s+(\S+)$')
# Paires « VIN MOTEUR » (MG / SAIC)
VIN_ENGINE_RE = re.compile(r'^([A-HJ-NPR-Z0-9]{17})\s+([A-Z0-9]{6,})$')
YOM_RE = re.compile(r'\bYOM\s*:\s*(\d{4})', re.I)
NEW_RE = re.compile(r'\bNEW\s+(?:VEHICLES?|CARS?|UNITS?)\b', re.I)
USED_RE = re.compile(r'\bUSED\b', re.I)

# Année-modèle ISO 3779 (10e caractère du VIN), cycle 2010-2039.
_VIN_YEAR = {c: 2010 + i for i, c in enumerate("ABCDEFGHJKLMNPRSTVWXY123456789")}

# Marque depuis le chargeur quand la description du groupe ne la porte pas.
_SHIPPER_BRANDS = [
    ("HYUNDAI GLOVIS", "Hyundai"), ("HYUNDAI MOTOR", "Hyundai"),
    ("HD CONSTRUCTION EQUIPMENT", "Develon"), ("JOHN DEERE", "John Deere"),
    ("ANHUI JIANGHUAI", "JAC"), ("SAIC MOTOR", "MG"),
]
# Marques reconnues dans la description du groupe (« CHANGAN VEHICLES »).
_DESC_BRANDS = ["CHANGAN", "JAC", "TOYOTA", "SUZUKI", "KIA", "HYUNDAI", "NISSAN",
                "MITSUBISHI", "ISUZU", "FOTON", "SINOTRUK", "JETOUR", "CHERY",
                "GEELY", "HAVAL", "GWM", "BYD", "KOMATSU", "CATERPILLAR"]


def _as_stream(src):
    return io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src


def _first_page_text(src) -> str:
    try:
        with pdfplumber.open(_as_stream(src)) as pdf:
            if not pdf.pages:
                raise ManifestReadError("Le PDF ne contient aucune page. Rechargez le fichier d'origine.")
            text = pdf.pages[0].extract_text() or ""
    except ManifestReadError:
        raise
    except Exception as e:
        raise ManifestReadError(
            "Impossible d'ouvrir ce PDF (fichier corrompu, protégé ou incomplet). "
            "Rechargez le manifeste d'origine.") from e
    if not text.strip():
        raise ManifestReadError(
            "Ce PDF ne contient pas de texte exploitable (image ou scan). "
            "Chargez le manifeste EUKOR d'origine, pas un scan.")
    return text


def is_eukor_format(src) -> bool:
    try:
        t = _first_page_text(src).upper()
    except ManifestReadError:
        return False
    return all(m in t for m in FORMAT_MARKERS)


def _num(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _clean_port(p: str) -> str:
    """« KUNSAN PORT OF SOUTH KOREA » -> « KUNSAN » ; « SHANGHAI PT, CHINA » -> « SHANGHAI »."""
    p = (p or "").strip().upper()
    p = re.split(r",", p)[0]
    p = re.sub(r"\s+PORT\s+OF\s+.*$", "", p)
    p = re.sub(r"\s+(PORT|PT)\.?$", "", p)
    p = re.sub(r"\s+(COTE\s*D.?\s*IVOIRE|IVORY\s+COAST)$", "", p)
    return p.strip()


def _party(col1: str, tag: str) -> str:
    """1re ligne du bloc (S)/(C)/(N) de la colonne 1."""
    m = re.search(rf'\({tag}\)\s*(.+?)(?=\n\s*\([SCN]\)|\Z)', col1 or "", re.S)
    if not m:
        return ""
    lines = [l.strip() for l in m.group(1).split("\n") if l.strip()]
    if not lines:
        return ""
    first = lines[0]
    # « TO THE ORDER OF : » seul sur sa ligne -> le nom est à la ligne suivante
    if re.fullmatch(r"TO\s+(THE\s+)?ORDER\s+OF\s*:?", first, re.I) and len(lines) > 1:
        first = f"{first.rstrip(' :')} {lines[1]}"
    if re.fullmatch(r"(NOTIFY\s*1\s*:?)", first, re.I) and len(lines) > 1:
        first = lines[1]
    return first.rstrip(",")


def _client(shipper_block: str) -> str:
    """Client = destinataire, sauf B/L « à ordre » d'une banque -> notify."""
    co = _party(shipper_block, "C")
    no = _party(shipper_block, "N")
    if re.match(r"TO\s+(THE\s+)?ORDER", co, re.I) and no and not re.match(r"SAME\s+AS", no, re.I):
        return re.sub(r"^NOTIFY\s*1\s*:\s*", "", no, flags=re.I)
    return co


def _brand_model(group_desc: str, shipper: str) -> tuple[str, str]:
    d = re.sub(r"\s+", " ", group_desc or "").strip()
    up = d.upper()
    if re.match(r"^MG\s*\w", up):                       # « MG5 », « MGZS », « MG T70 »
        rest = d[2:].strip()
        return "MG", (f"MG{rest}" if rest[:1].isdigit() else rest)   # MG5 / MG7, sinon ZS, HS, T70
    for b in _DESC_BRANDS:
        if re.search(rf"(?<![A-Z]){b}(?![A-Z])", up):
            model = re.sub(rf"(?<![A-Z]){b}(?![A-Z])", "", d, flags=re.I)
            model = re.sub(r"\bVEHICLES?\b", "", model, flags=re.I).strip(" -")
            return b.title() if len(b) > 3 else b, model
    su = (shipper or "").upper()
    for key, brand in _SHIPPER_BRANDS:
        if key in su:
            model = re.sub(r"^HD\s+", "", d) if brand == "Hyundai" else d
            return brand, model
    return "", d


def _size_type(vol: float | None) -> str:
    if not vol:
        return ""
    return "C" if vol < 15 else ("V" if vol <= 50 else "T")


def parse_eukor_manifest(src, source_label: str = "", progress_cb=None):
    """-> (DataFrame, warnings, meta). Lève ManifestReadError / ManifestFormatError."""
    first = _first_page_text(src)
    if not all(m in first.upper() for m in FORMAT_MARKERS):
        raise ManifestFormatError(
            "Ce PDF n'est pas un manifeste EUKOR « GENERAL CARGO MANIFEST ». "
            "Utilisez l'onglet du bon type de manifeste (Grimaldi, MOL / NYK, navire à grue).")

    blocks: list[dict] = []
    navire = voyage = ""
    pol = pod = ""
    try:
        with pdfplumber.open(_as_stream(src)) as pdf:
            total = len(pdf.pages)
            for pno, page in enumerate(pdf.pages, 1):
                for table in page.extract_tables():
                    for row in table:
                        cells = [(c or "") for c in row]
                        flat = " ".join(cells)
                        # En-tête de page (navire / ports)
                        if "SHIP'S NAME" in flat and len(cells) >= 2:
                            vv = cells[1].strip()
                            mv = re.match(r"(.+?)\s+(\S+)$", vv)
                            if mv:
                                navire, voyage = mv.group(1).strip(), mv.group(2).strip()
                            continue
                        if cells[0].startswith("NAME OF MASTER") and len(cells) >= 6:
                            pol, pod = cells[4].strip() or pol, cells[5].strip() or pod
                            continue
                        if len(cells) < 4 or cells[0].startswith("B/L No") or "Sailing Date" in flat:
                            continue
                        m = BL_RE.search(cells[0])
                        if m:
                            blocks.append({"bl": m.group(1), "pol": pol, "pod": pod,
                                           "c1": cells[1], "c2": cells[2], "c3": cells[3]})
                        elif blocks and (cells[2].strip() or cells[3].strip()):
                            # Ligne de suite (saut de page) : prolonge le B/L en cours
                            b = blocks[-1]
                            b["c1"] += "\n" + cells[1]
                            b["c2"] += "\n" + cells[2]
                            b["c3"] += "\n" + cells[3]
                page.flush_cache()
                if progress_cb:
                    progress_cb(pno, total)
    except Exception as e:
        raise ManifestReadError(
            "Lecture interrompue au milieu du PDF (fichier tronqué ou corrompu). "
            "Rechargez le manifeste d'origine.") from e

    warnings: list[str] = []
    rows: list[dict] = []
    for b in blocks:
        tm = TOTALS_RE.search(b["c3"])
        w_tot, v_tot, n_tot = (_num(tm.group(1)), _num(tm.group(2)), int(tm.group(3))) if tm else (None, None, 0)

        # Groupes AUTO / RORO / BREAKBULK + leurs châssis
        groups, cur = [], None
        for line in b["c3"].split("\n"):
            line = line.strip()
            gm = GROUP_RE.match(line)
            if gm:
                cur = {"kind": gm.group(1).upper(), "qty": int(gm.group(2)),
                       "desc": gm.group(3).strip(), "chassis": []}
                groups.append(cur)
            elif cur is not None and line:
                toks = line.split()
                if all(CHASSIS_TOKEN_RE.match(t) and re.search(r"\d", t) for t in toks):
                    cur["chassis"].extend(toks)

        # Infos de la description : modèle + moteur par VIN, année de fabrication
        model_by_vin, engine_by_vin = {}, {}
        for line in b["c2"].split("\n"):
            line = line.strip()
            mm = MODEL_VIN_ENGINE_RE.match(line)
            if mm:
                model_by_vin[mm.group(2)] = mm.group(1)
                engine_by_vin[mm.group(2)] = mm.group(3)
                continue
            ve = VIN_ENGINE_RE.match(line)
            if ve:
                engine_by_vin.setdefault(ve.group(1), ve.group(2))
        yom = YOM_RE.search(b["c2"])
        etat = "Neuf" if NEW_RE.search(b["c2"]) else ("Usager" if USED_RE.search(b["c2"]) else "")

        shipper = _party(b["c1"], "S")
        client = _client(b["c1"])
        unit_groups = [g for g in groups if g["kind"] != "BREAKBULK"]
        n_units = sum(len(g["chassis"]) or g["qty"] for g in unit_groups)
        u_w = round(w_tot / n_units) if (w_tot and n_units) else None
        u_v = round(v_tot / n_units, 3) if (v_tot and n_units) else None

        for g in groups:
            if g["kind"] == "BREAKBULK":
                warnings.append(f"B/L {b['bl']} : {g['qty']} colis BREAKBULK ({g['desc'] or 'sans description'}) "
                                "— non repris en véhicule, à traiter en colis si besoin.")
        if not unit_groups:
            continue

        pol_c = _clean_port(b["pol"])
        pod_c = _clean_port(b["pod"]) or "ABIDJAN"
        nature = "Import" if "ABIDJAN" in pod_c else "Export/Transbo"
        n_ch_bl = sum(len(g["chassis"]) for g in unit_groups)
        for g in unit_groups:
            marque, modele_grp = _brand_model(g["desc"], shipper)
            chassis = g["chassis"] or [""] * g["qty"]
            obs_grp = ""
            if g["chassis"] and len(g["chassis"]) != g["qty"]:
                obs_grp = f"ecart quantite groupe : {g['qty']} declares vs {len(g['chassis'])} chassis"
                if n_ch_bl == n_tot:
                    obs_grp += f" (total B/L conforme : {n_tot} unites)"
            elif not g["chassis"]:
                obs_grp = "AUCUN CHASSIS EXTRAIT - a completer manuellement"
            generic = not modele_grp or re.fullmatch(r"VEHICLES?", modele_grp, re.I)
            for ch in chassis:
                modele = model_by_vin.get(ch) if (generic and ch in model_by_vin) else modele_grp
                annee = int(yom.group(1)) if yom else (
                    _VIN_YEAR.get(ch[9]) if len(ch) == 17 and VIN_RE.fullmatch(ch) else None)
                rows.append({
                    "NATURE BL": nature, "POL TETRAX": pol_c, "POD TETRAX": pod_c,
                    "FINAL DESTINATION TETRAX": pod_c,
                    "POIDS TETRAX (KG)": u_w, "TYPE / TAILLE": _size_type(u_v),
                    "VOLUME TETRAX": u_v, "BL": b["bl"],
                    "MARQUE": marque, "MODELE": modele or "",
                    "MARQUE & MODELE": f"{marque} {modele or ''}".strip(),
                    "ETAT": etat, "ANNEE DE FABRICATION": annee,
                    "TYPE D'ACTION": "IMPORT" if nature == "Import" else "",
                    "CLIENT": client, "OBSERVATION": obs_grp, "CHÂSSIS": ch,
                    "_qty_declaree": n_tot, "_type_declare": g["kind"],
                    "_ctrl_qty": n_tot, "_ctrl_weight": w_tot,
                    "_ENGINE_NO": engine_by_vin.get(ch, ""), "_SHIPPER": shipper,
                })

    if rows:
        df = pd.DataFrame(rows)
        # Reste d'arrondi du poids unitaire reporté sur la dernière unité du
        # B/L : la somme des lignes = poids total du B/L (contrôles de totaux).
        for _bl, idx in df.groupby("BL", sort=False).groups.items():
            w_bl = df.loc[idx[0], "_ctrl_weight"]
            if w_bl and df.loc[idx, "POIDS TETRAX (KG)"].notna().all():
                df.loc[idx[-1], "POIDS TETRAX (KG)"] += round(w_bl) - df.loc[idx, "POIDS TETRAX (KG)"].sum()
        df.insert(0, "NBRE", range(1, len(df) + 1))
    else:
        df = pd.DataFrame(columns=OUTPUT_COLUMNS + ["CLIENT", "_ENGINE_NO", "_SHIPPER"])
        warnings.append("Aucun véhicule extrait de ce PDF — vérifier qu'il s'agit bien "
                        "d'un manifeste EUKOR complet (pages non tronquées).")

    # Contrôle global : total « TOTAL ... UNITS » du pied de manifeste
    full_tot = None
    try:
        with pdfplumber.open(_as_stream(src)) as pdf:
            last = pdf.pages[-1].extract_text() or ""
        mt = re.search(r"TOTAL\s+[\d,]+\s*KGS\s+[\d,.]+\s*CBM\s+(\d+)\s*UNITS", last, re.I)
        full_tot = int(mt.group(1)) if mt else None
    except Exception:
        pass
    n_bb = sum(int(re.search(r": (\d+) colis", w).group(1)) for w in warnings if " colis BREAKBULK" in w)
    if full_tot is not None and full_tot != len(df) + n_bb:
        warnings.insert(0, f"Total manifeste {full_tot} unités ≠ {len(df)} véhicules + {n_bb} colis extraits "
                           "— vérifier les B/L signalés.")
    meta = {"navire": navire, "voyage": voyage, "total_declare": full_tot,
            "nb_bl": len(blocks), "nb_breakbulk": n_bb}
    return df, warnings, meta
