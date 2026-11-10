"""
Fiche de dépouillement (intégrée depuis la mini-app « Manifeste parser v5 »).

À partir des B/L déjà extraits par `manifest_parser.parse_manifest`, compte les
unités par catégorie de la fiche : USED / NEW / 20' / 40' / >50m3 / BOLSTER /
DIVERS. La classification suit le libellé de catégorie Grimaldi (pas le volume) :
  - Used/New Small Van, Big Van, Car → USED / NEW ;
  - Used/New LM RoRo → USED / NEW (grand van) ;
  - LM RoRo, LM Cargo, tracteurs, remorques, engins, « bébés au dos » → >50m3 ;
  - Conteneurs → 20' / 40' ; Bolster → BOLSTER ; le reste → DIVERS.

Pas de dépendance Streamlit : testable seul.
"""
import datetime
import io
import re
import uuid

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from manifest_parser import MODEL_YEAR_RE, extract_marque_modele, item_status

ANS_RECENTS = 1     # indice de passage : année écrite >= année en cours - 1
SOUS_TYPE_PASSAGE = "Véhicule NEW (passage agent)"
CAT_PKG_VEH, CAT_PKG_COLIS = "Packages véhicules", "Packages colis"
CATS = ["USED", "NEW", "20'", "40'", ">50m3", "BOLSTER", "DIVERS", CAT_PKG_VEH, CAT_PKG_COLIS]

SUBTYPE_LABELS = {
    "USED_SMALL_VAN": "SUV / Petit Van USED",
    "USED_BIG_VAN": "Grand Van / Pickup USED",
    "USED_CAR": "Voiture USED",
    "NEW_SMALL_VAN": "SUV / Petit Van NEW",
    "NEW_BIG_VAN": "Grand Van / Pickup NEW",
    "NEW_CAR": "Voiture NEW",
    "CONT_20": "Container 20'",
    "CONT_40HC": "Container 40' HC",
    "CONT_40OT": "Container 40' OT",
    "MAFI": "LM RoRo / >50m3",
    "BOLSTER": "BOLSTER",
    "DIVERS": "DIVERS",
    # Manifestes sans libellé de catégorie (voir fiche_sources)
    "VEH_USED": "Véhicule USED",
    "VEH_NEW": "Véhicule NEW",
    "COLIS": "Colis sans châssis",
}
SUBTYPE_CAT = {
    "USED_SMALL_VAN": "USED", "USED_BIG_VAN": "USED", "USED_CAR": "USED",
    "NEW_SMALL_VAN": "NEW", "NEW_BIG_VAN": "NEW", "NEW_CAR": "NEW",
    "CONT_20": "20'", "CONT_40HC": "40'", "CONT_40OT": "40'",
    "MAFI": ">50m3", "BOLSTER": "BOLSTER", "DIVERS": "DIVERS",
    "VEH_USED": "USED", "VEH_NEW": "NEW", "COLIS": CAT_PKG_COLIS,
}

# Ordre significatif : le premier motif qui correspond gagne.
_PATTERNS = [
    (r'used\s+small\s+van', 'USED_SMALL_VAN'),
    (r'used\s+big\s+van', 'USED_BIG_VAN'),
    (r'used\s+car', 'USED_CAR'),
    (r'new\s+small\s+van', 'NEW_SMALL_VAN'),
    (r'new\s+big\s+van', 'NEW_BIG_VAN'),
    (r'new\s+car', 'NEW_CAR'),
    (r'used\s+lm\s+roro', 'USED_BIG_VAN'),
    (r'new\s+lm\s+roro', 'NEW_BIG_VAN'),
    (r'lm\s+roro', 'MAFI'),
    (r'lm\s+cargo', 'MAFI'),
    (r'bolster', 'BOLSTER'),
    (r'20\s*ft', 'CONT_20'),
    (r'40\s*ft\.?\s*(open\s*top|flat\s*rack)', 'CONT_40OT'),
    (r'40\s*ft', 'CONT_40HC'),
    (r'tractor|trailer|construction\s+equip|heavy\s+equip|excavat|bulldozer|'
     r'forklift|crane|generator|compressor|truck|\bbus\b|ambulance', 'MAFI'),
    (r'boat|yacht|motor\s*cycle', 'DIVERS'),
]
_PATTERNS = [(re.compile(p, re.I), c) for p, c in _PATTERNS]
_BARE_VEHICLE = [  # véhicule sans « used/new » dans le libellé : statut à chercher
    (re.compile(r'small\s+van', re.I), "SMALL_VAN"),
    (re.compile(r'big\s+van', re.I), "BIG_VAN"),
    (re.compile(r'\bcar(?:\(s\))?\b', re.I), "CAR"),
]


def classify_item(type_raw, is_mafi=False, piggyback=False, context=""):
    """Retourne (sous_type, fiabilité). Fiabilité : HIGH (libellé explicite),
    MEDIUM (statut Used/New déduit du contexte B/L), LOW (à vérifier)."""
    if piggyback or is_mafi:
        return "MAFI", "HIGH"
    t = type_raw or ""
    for rx, sub in _PATTERNS:
        if rx.search(t):
            return sub, "HIGH"
    for rx, kind in _BARE_VEHICLE:
        if rx.search(t):
            st = item_status(t, context)
            if st == "Neuf":
                return f"NEW_{kind}", "MEDIUM"
            if st == "Usager":
                return f"USED_{kind}", "MEDIUM"
            return f"USED_{kind}", "LOW"
    # Libellé absent (« 1-UNIT(S) » / « NEW UNPACKED VEHICLE ») : véhicule si le B/L le dit
    if not t.strip() and re.search(r"UNPACKED\s+VEHICLE", context, re.I):
        st = item_status("", context)
        if st == "Neuf":
            return "VEH_NEW", "MEDIUM"
        return ("VEH_USED", "MEDIUM") if st == "Usager" else ("VEH_USED", "LOW")
    return "DIVERS", ("LOW" if t.strip() else "MEDIUM")


def _split_vessel(vv):
    m = re.match(r'^(.*?)\s*:\s*(\S+)$', vv or "")
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return (vv or "").strip() or "(navire non détecté)", ""


def _per_unit(total, qty, nd):
    try:
        return round(float(total) / qty, nd) if total else None
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def build_units(records):
    """Une ligne par unité physique (qty éclatée). Liste de dicts."""
    units = []
    lot = uuid.uuid4().hex[:8]     # identifiant de ce lot de records : 2 fichiers = 2 lots
    for n_rec, r in enumerate(records):
        navire, voyage = _split_vessel(r.get("vessel_voyage"))
        ctx = " | ".join(dict.fromkeys(r.get("raw_desc_lines", [])))
        # Unités attelées / empilées (TRAILER ATTACHED, S.T.B. STACKED WITH) : avec leur
        # unité porteuse (dernière unité non portée du B/L), elles forment 1 package véhicules.
        porteur, groupe, n_groupes = None, None, 0
        for it in r.get("items", []):
            debut = len(units)
            raw = it.get("type_raw", "")
            sub, conf = classify_item(raw, it.get("is_mafi", False),
                                      it.get("_piggyback", False), ctx)
            chassis = it.get("chassis") or []
            qty = max(int(it.get("qty") or 1), 1)
            if not raw.strip():     # sans libellé, seule la liste de châssis donne le nombre
                qty = max(qty, len(chassis))
            marque, modele = extract_marque_modele(raw)
            if not marque:
                marque, modele = extract_marque_modele(ctx)
            ym = MODEL_YEAR_RE.search(raw + " " + ctx)
            annee = (ym.group(1) or ym.group(2)) if ym else ""
            conts = it.get("container_no") or []
            w, c = _per_unit(it.get("weight"), qty, 1), _per_unit(it.get("cbm"), qty, 3)
            for i in range(qty):
                units.append({
                    "Navire": navire, "Voyage": voyage,
                    "BL": r.get("bl_number", ""),
                    "Catégorie": SUBTYPE_CAT[sub], "Sous-type": SUBTYPE_LABELS[sub],
                    "Identification manifeste": raw,
                    "Marque/Modèle": " ".join(x for x in (marque, modele) if x),
                    "N° conteneur": conts[i] if i < len(conts) else "",
                    "Châssis/VIN": chassis[i] if i < len(chassis) else "",
                    "Année": annee, "Poids (kg)": w, "CBM": c,
                    "Fiabilité": conf,
                })
            nouvelles = units[debut:]
            if it.get("_piggyback", False):
                if groupe is None:
                    n_groupes += 1
                    groupe = f"{lot}|{n_rec}|{r.get('bl_number', '')}|empilées {n_groupes}"
                    if porteur is not None and porteur["Catégorie"] in ("USED", "NEW", ">50m3"):
                        nouvelles = [porteur] + nouvelles
                for u in nouvelles:
                    u.update({"Catégorie": CAT_PKG_VEH, "Groupe package": groupe, "Packages du groupe": 1})
            else:
                groupe = None
                if nouvelles:
                    porteur = nouvelles[-1]
    return units


def _cle_passage(u):
    return (str(u.get("BL") or ""), u.get("Marque/Modèle") or u.get("Identification manifeste") or "",
            str(u.get("Année") or ""))


def propositions_passage(units):
    """Véhicules USED sans état écrit, regroupés par B/L, modèle et année : l'agent
    décide du passage en NEW. Lignes avec indice (année récente écrite) en premier."""
    groupes = {}
    for u in units:
        if u["Catégorie"] == "USED" and u["Fiabilité"] == "LOW":
            k = _cle_passage(u)
            groupes[k] = groupes.get(k, 0) + 1
    seuil = datetime.date.today().year - ANS_RECENTS
    out = []
    for (bl, modele, annee), n in groupes.items():
        indice = f"Année {annee} au manifeste" if annee.isdigit() and int(annee) >= seuil else "Aucun indice"
        out.append({"cle": (bl, modele, annee), "B/L": bl, "Unités": n, "Modèle": modele,
                    "Année": annee, "Indice": indice})
    return sorted(out, key=lambda p: (p["Indice"] == "Aucun indice", p["B/L"], p["Modèle"]))


def appliquer_passage(units, cles):
    """Copie des unités où les groupes choisis par l'agent passent en NEW."""
    cles = set(cles)
    out = []
    for u in units:
        if u["Catégorie"] == "USED" and u["Fiabilité"] == "LOW" and _cle_passage(u) in cles:
            u = {**u, "Catégorie": "NEW", "Sous-type": SOUS_TYPE_PASSAGE, "Fiabilité": "AGENT"}
        out.append(u)
    return out


def count_by_category(units):
    counts = {c: 0 for c in CATS}
    for u in units:
        counts[u["Catégorie"]] += 1
    return counts


def normaliser_categories(units):
    """Fiche générée avant le renommage et gardée en session (mise à jour à chaud)."""
    anciens = {"Package véhicules": CAT_PKG_VEH, "Package colis": CAT_PKG_COLIS}
    return [{**u, "Catégorie": anciens.get(u["Catégorie"], u["Catégorie"])} for u in units]


def count_packages(units):
    """Packages de véhicules groupés -> (nombre de packages, véhicules dedans)."""
    groupes = {u["Groupe package"]: u["Packages du groupe"] for u in units if u.get("Groupe package")}
    return sum(groupes.values()), sum(1 for u in units if u.get("Groupe package"))


def resume_packages(units):
    """Packages véhicules + packages colis = packages (1 colis = 1 package)."""
    pkg_veh, vehicules = count_packages(units)
    colis = sum(1 for u in units if u["Catégorie"] == CAT_PKG_COLIS)
    return {"veh": pkg_veh, "vehicules": vehicules, "colis": colis, "total": pkg_veh + colis}


def detail_packages(units):
    """Une ligne par châssis des packages véhicules, groupe par groupe."""
    rows = [{"N° B/L": u["BL"], "Packages du groupe": u["Packages du groupe"],
             "Véhicules du groupe": 0, "Modèle": u.get("Marque/Modèle") or "",
             "Châssis": u.get("Châssis/VIN") or "", "Année": u.get("Année") or "",
             "_g": u["Groupe package"]} for u in units if u.get("Groupe package")]
    for r in rows:
        r["Véhicules du groupe"] = sum(1 for x in rows if x["_g"] == r["_g"])
    return [{k: v for k, v in r.items() if k != "_g"} for r in rows]


def count_by_subtype(units):
    out = {}
    for u in units:
        k = (u["Catégorie"], u["Sous-type"])
        out[k] = out.get(k, 0) + 1
    return out


# ── Méthode de décompte (affichée sur la page et dans l'onglet « Méthode ») ──
METHODE_CATEGORIES = [
    ("USED", "Libellé Used, ou véhicule sans Used ni New écrit (fiabilité LOW).",
     "Mot USED écrit au manifeste, ou aucun état écrit (fiabilité LOW)."),
    ("NEW", "Libellé New, ou mot NEW écrit dans le B/L.",
     "Mot NEW ou NEUF écrit au manifeste."),
    ("20'", "Libellé 20 ft.", "Non concerné."),
    ("40'", "Libellé 40 ft (HC, Open Top, Flat Rack).", "Non concerné."),
    (">50m3", "LM RoRo sans Used/New, LM Cargo, tracteurs, remorques, engins, MAFI.",
     "Volume unitaire strictement supérieur à 50 m3. Sans volume au manifeste : engin nommé "
     "(camion, foreuse, pelle...), à vérifier."),
    ("BOLSTER", "Libellé Bolster.", "Non concerné."),
    (CAT_PKG_VEH, "Unité porteuse et unités attelées ou empilées (TRAILER ATTACHED, S.T.B. STACKED WITH) : "
     "1 package.", "Plusieurs véhicules dans moins de packages (7 PACKAGES=21 UNITS, ou plus de "
     "VIN que de packages). La carte compte les packages et indique les véhicules ; leurs châssis "
     "sont détaillés à part. Un véhicule par package reste en USED ou NEW."),
    (CAT_PKG_COLIS, "—", "Colis sans châssis : pièces, caisses, outils, wagons."),
    ("DIVERS", "Tout autre libellé (caisses, pièces, bateaux, motos...).",
     "Non concerné : les colis vont en Package colis."),
]
METHODE_NOTES = [
    "Une ligne = une unité physique, selon la quantité du manifeste.",
    "Packages véhicules + Packages colis = Packages. TOTAL unités compte les véhicules et les colis, "
    "pas les packages.",
    "Fiabilité HIGH : libellé ou état explicite. MEDIUM : mot trouvé dans le B/L. LOW : à vérifier. "
    "AGENT : passage décidé par l'agent.",
    "Colis du même B/L qu'un véhicule : poids compris dans le poids du B/L, ligne sans poids.",
    "VIN absents du manifeste (« see attachment ») : les unités restent comptées, châssis à compléter.",
    "Grimaldi : chaque unité portée (attelée ou empilée) et chaque MAFI comptent à part dans TOTAL unités ; "
    "une unité porteuse et ses unités portées font 1 package véhicules. Le tableau "
    "de classification compte par colis et sans les MAFI : son total peut donc être plus bas.",
    "Un même fichier chargé deux fois n'est compté qu'une fois ; un châssis présent dans deux "
    "fichiers est signalé.",
]


METHODE_PASSAGE = [
    "NEW ne vient que du mot écrit au manifeste : ni l'année ni le VIN ne classent une unité.",
    "L'application propose les véhicules USED sans état écrit, par B/L et modèle. Une année écrite "
    "récente (année en cours ou précédente) est signalée comme indice.",
    "L'agent coche « Passer en NEW » : rien ne bascule sans lui. Le décompte et l'Excel suivent, "
    "et ces unités sont marquées « passage agent » (fiabilité AGENT).",
]


# ── Export Excel (design repris de la mini-app v5) ─────────────────────────
_NAVY, _ACCENT = "1B2B4B", "2563EB"
_ROW_COLORS = {
    "USED": ("FEF3C7", "92400E"), "NEW": ("D1FAE5", "065F46"),
    "20'": ("E0E7FF", "3730A3"), "40'": ("F3E8FF", "6B21A8"),
    ">50m3": ("FCE7F3", "9D174D"), "BOLSTER": ("FEE2E2", "991B1B"),
    "DIVERS": ("F3F4F6", "6B7280"),
    CAT_PKG_VEH: ("E0E7FF", "3730A3"),
    CAT_PKG_COLIS: ("FEF3C7", "92400E"),
}
_FONT = "Segoe UI"
_thin = Side(style="thin", color="D1D5DB")
_BORDER = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)


def _fill(hex_):
    return PatternFill("solid", fgColor=hex_)


def build_fiche_excel(units, navire="", voyage=""):
    wb = Workbook()
    ws = wb.active
    ws.title = "Fiche"
    counts = count_by_category(units)
    total = sum(counts.values())

    ws.merge_cells("A1:K1")
    ws["A1"] = f"FICHE DE DÉPOUILLEMENT — {navire} {voyage}".strip()
    ws["A1"].font = Font(name=_FONT, size=14, bold=True, color="FFFFFF")
    ws["A1"].fill = _fill(_NAVY)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    pkg = resume_packages(units)
    valeurs = {**counts, CAT_PKG_VEH: pkg["veh"], "Packages": pkg["total"], "TOTAL unités": total}
    heads = CATS + ["Packages", "TOTAL unités"]
    for j, h in enumerate(heads, 1):
        c = ws.cell(row=3, column=j, value=h)
        bg, fg = _ROW_COLORS.get(h, (_NAVY, "FFFFFF"))
        c.fill = _fill(bg)
        c.font = Font(name=_FONT, bold=True, color=fg)
        c.alignment = Alignment(horizontal="center")
        c.border = _BORDER
        v = ws.cell(row=4, column=j, value=valeurs[h])
        v.font = Font(name=_FONT, size=16, bold=True)
        v.alignment = Alignment(horizontal="center")
        v.border = _BORDER
        if h == CAT_PKG_VEH:
            note = ws.cell(row=5, column=j, value=f"{pkg['vehicules']} véhicules")
            note.font = Font(name=_FONT, size=9, color="6B7280")
            note.alignment = Alignment(horizontal="center")

    ws["A6"] = "Détail par sous-type"
    ws["A6"].font = Font(name=_FONT, bold=True, color=_ACCENT)
    r = 7
    for j, h in enumerate(["Catégorie", "Sous-type", "Nombre"], 1):
        c = ws.cell(row=r, column=j, value=h)
        c.font = Font(name=_FONT, bold=True, color="FFFFFF")
        c.fill = _fill(_NAVY)
        c.border = _BORDER
    for (cat, sub), n in sorted(count_by_subtype(units).items(),
                                key=lambda kv: (CATS.index(kv[0][0]), kv[0][1])):
        r += 1
        bg, fg = _ROW_COLORS[cat]
        for j, val in enumerate([cat, sub, n], 1):
            c = ws.cell(row=r, column=j, value=val)
            c.fill, c.border = _fill(bg), _BORDER
            c.font = Font(name=_FONT, color=fg)
    for j in range(1, 12):
        ws.column_dimensions[get_column_letter(j)].width = 22 if j == 2 else 13

    wd = wb.create_sheet("Détail")
    cols = ["BL", "Catégorie", "Sous-type", "Identification manifeste", "Marque/Modèle",
            "N° conteneur", "Châssis/VIN", "Année", "Poids (kg)", "CBM", "Fiabilité"]
    for j, h in enumerate(cols, 1):
        c = wd.cell(row=1, column=j, value=h if h != "BL" else "N° B/L")
        c.font = Font(name=_FONT, bold=True, color="FFFFFF")
        c.fill = _fill(_NAVY)
        c.border = _BORDER
    for i, u in enumerate(units, 2):
        bg, fg = _ROW_COLORS[u["Catégorie"]]
        for j, h in enumerate(cols, 1):
            c = wd.cell(row=i, column=j, value=u[h])
            c.fill, c.border = _fill(bg), _BORDER
            c.font = Font(name=_FONT, color=fg)
    widths = [18, 11, 24, 42, 22, 16, 22, 8, 11, 9, 11]
    for j, w in enumerate(widths, 1):
        wd.column_dimensions[get_column_letter(j)].width = w
    wd.freeze_panes = "A2"
    wd.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{max(len(units), 1) + 1}"

    lignes = detail_packages(units)
    if lignes:
        wp = wb.create_sheet("Packages véhicules")
        for j, h in enumerate(lignes[0], 1):
            c = wp.cell(row=1, column=j, value=h)
            c.font = Font(name=_FONT, bold=True, color="FFFFFF")
            c.fill = _fill(_NAVY)
            c.border = _BORDER
            wp.column_dimensions[get_column_letter(j)].width = 24 if h in ("Modèle", "Châssis", "N° B/L") else 12
        for i, l in enumerate(lignes, 2):
            for j, val in enumerate(l.values(), 1):
                c = wp.cell(row=i, column=j, value=val)
                c.font, c.border = Font(name=_FONT), _BORDER
        wp.freeze_panes = "A2"

    wm = wb.create_sheet("Méthode")
    wm.column_dimensions["A"].width = 16
    wm.column_dimensions["B"].width = 58
    wm.column_dimensions["C"].width = 58
    wm["A1"] = "Décompte et passage USED vers NEW"
    wm["A1"].font = Font(name=_FONT, size=14, bold=True, color=_NAVY)
    for j, h in enumerate(["Catégorie", "Grimaldi", "Autres manifestes"], 1):
        c = wm.cell(row=3, column=j, value=h)
        c.font = Font(name=_FONT, bold=True, color="FFFFFF")
        c.fill, c.border = _fill(_NAVY), _BORDER
    r = 3
    for ligne in METHODE_CATEGORIES:
        r += 1
        for j, val in enumerate(ligne, 1):
            c = wm.cell(row=r, column=j, value=val)
            c.font = Font(name=_FONT, bold=j == 1)
            c.alignment = Alignment(wrap_text=True, vertical="top")
            c.border = _BORDER
    for titre, notes in (("Passage USED vers NEW", METHODE_PASSAGE), ("À savoir", METHODE_NOTES)):
        r += 2
        wm.cell(row=r, column=1, value=titre).font = Font(name=_FONT, bold=True, color=_ACCENT)
        for note in notes:
            r += 1
            wm.merge_cells(start_row=r, start_column=1, end_row=r, end_column=3)
            c = wm.cell(row=r, column=1, value=note)
            c.font = Font(name=_FONT)
            c.alignment = Alignment(wrap_text=True, vertical="top")
            wm.row_dimensions[r].height = 32

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
