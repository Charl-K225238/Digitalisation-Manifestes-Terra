"""Lecture des sources du reporting « Statistiques flash et reporting RORO / TEU ».

Deux sources, toutes deux produites par les agents ou le Port :

1. Classeur des volumes d'activité du mois — deux variantes connues, même
   mise en page par navire :
     - « VOLUMES D'ACTIVITES <MOIS>_<AAAA>_ELVIS.xls » (feuille « Feuil1 »)
     - « STATS FLASH VOLUMES TCS BOLS MAFIS ET VEHICULES OPN <MOIS> <AAAA>.xls »
       (feuille « VOLUMES D'ACTIVITES 2026 »)
   Un bloc IMPORT puis un bloc EXPORT, une ligne par escale, ligne « TOTAL »
   en fin de bloc. Fournit : escales, conteneurs (TEU), véhicules totaux,
   neufs / usagés, transit (= Hinterland).

2. Extrait PAA mensuel (39 colonnes MDNORD…MFILL2) — facturation par
   rubrique. Fournit les tranches de volume <15 / 15-50 / >50 m³ et le type
   de navire (MSTNAV : RORO / CARCAR / COMBONG = Lo/Lo).

Chaque valeur lue garde sa trace (fichier, feuille, ligne Excel) pour pouvoir
répondre à « d'où vient ce chiffre ? » dans l'app.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd
import xlrd

# Colonnes du classeur volumes (index 0 = colonne A). Validées sur les
# classeurs d'août et septembre 2026 ; vérifiées à la lecture (voir
# _check_header) pour détecter un changement de mise en page.
VOL_COLS = {
    "ordre": 0, "navire": 1, "armateur": 2, "debut": 3, "fin": 4,
    "c20_plein": 5, "c40_plein": 6, "mafi20_plein": 7, "mafi40_plein": 8, "bol_plein": 9,
    "c20_vide": 10, "c40_vide": 11, "mafi20_vide": 12, "mafi40_vide": 13, "bol_vide": 14,
    "veh_total": 15, "veh_neufs": 16, "veh_usages": 17, "veh_sup50": 18,
    "veh_transit": 19, "veh_tbt": 20,
}
NUM_FIELDS = [k for k in VOL_COLS if k not in ("ordre", "navire", "armateur", "debut", "fin")]

MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"]

TRANCHES = ["<15", "15-50", ">50"]


class SourceError(ValueError):
    """Fichier non reconnu : message clair à afficher tel quel à l'utilisateur."""


@dataclass
class VolumesResult:
    fichier: str
    feuille: str
    annee: int
    mois: int
    escales: pd.DataFrame            # une ligne par (navire, sens)
    totaux_fichier: dict             # {"Import": {...}, "Export": {...}} lus sur les lignes TOTAL
    alertes: list = field(default_factory=list)


@dataclass
class PaaResult:
    fichier: str
    feuille: str
    annee: int | None
    mois: int | None
    lignes: pd.DataFrame             # une ligne par (escale PAA, rubrique véhicule retenue)
    exclues: pd.DataFrame            # rubriques véhicule non comptées (shifting, bord à bord)
    alertes: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------
def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def ship_key(name: str) -> str:
    """Nom de navire sans le voyage : « TJ VANDA V.26K » -> « TJ VANDA »,
    « GRANDE LUANDA GLU0526 » -> « GRANDE LUANDA »."""
    words = _norm(name).replace(".", ". ").split()
    out = []
    for w in words:
        if w in ("V.", "V", "VOY", "VOY.") or re.fullmatch(r"[A-Z]{2,4}\d{3,}[A-Z]?", w) or re.fullmatch(r"\d{2,}[A-Z]?", w):
            break
        out.append(w)
    return " ".join(out).replace(". ", ".").strip()


def _num(v) -> float:
    if v in ("", None):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _xl_date(v, datemode) -> datetime | None:
    if isinstance(v, float) and v > 20000:
        try:
            return xlrd.xldate_as_datetime(v, datemode)
        except Exception:
            return None
    return None


def _paa_date(v) -> date | None:
    """MDATDC/MDATFC : JJMMAAAA en nombre, sans zéro de tête (1092026 = 01/09/2026)."""
    try:
        s = f"{int(float(v)):08d}"
        return date(int(s[4:]), int(s[2:4]), int(s[:2]))
    except Exception:
        return None


def _open(data: bytes) -> xlrd.Book:
    try:
        return xlrd.open_workbook(file_contents=data)
    except Exception as exc:
        raise SourceError(
            "Fichier illisible. Chargez le classeur .xls tel qu'il est enregistré dans le dossier PAA "
            f"(détail technique : {exc})."
        ) from exc


# ---------------------------------------------------------------------------
# 1. Classeur volumes d'activité (ELVIS / STATS FLASH)
# ---------------------------------------------------------------------------
def _pick_volumes_sheet(book: xlrd.Book) -> xlrd.sheet.Sheet:
    names = [s.name for s in book.sheets()]
    for i, n in enumerate(names):
        nn = _norm(n)
        if "VOLUMES D'ACTIVITES" in nn and "LOLO" not in nn and "CUMUL" not in nn:
            return book.sheet_by_index(i)
    for i, n in enumerate(names):
        if _norm(n) == "FEUIL1":
            return book.sheet_by_index(i)
    raise SourceError(
        "Feuille des volumes introuvable. Attendu : « Feuil1 » (classeur ELVIS) ou "
        "« VOLUMES D'ACTIVITES 2026 » (classeur Stats Flash). Feuilles trouvées : " + ", ".join(names)
    )


def _find_blocks(sh) -> list[tuple[int, int, int]]:
    """Retourne [(ligne_entête, première_ligne_navire, ligne_TOTAL)] pour chaque bloc."""
    blocks, r = [], 0
    while r < sh.nrows:
        if _norm(sh.cell_value(r, 1)) == "NAVIRES" and _norm(sh.cell_value(r, 0)) == "ORDRE":
            start = r + 1
            t = start
            while t < sh.nrows and _norm(sh.cell_value(t, 4)) != "TOTAL":
                t += 1
            if t >= sh.nrows:
                break
            blocks.append((r, start, t))
            r = t
        r += 1
    return blocks


def _check_header(sh, head_row: int, alertes: list):
    """Vérifie que les colonnes 20'/40' et véhicules sont bien là où on les attend."""
    labels = {}
    for rr in range(head_row, min(head_row + 3, sh.nrows)):
        for c in range(sh.ncols):
            v = _norm(sh.cell_value(rr, c))
            if v:
                labels.setdefault(c, v)
    ok = labels.get(5, "").startswith("20") or any(_norm(sh.cell_value(rr, 5)).startswith("20")
                                                  for rr in range(head_row, min(head_row + 3, sh.nrows)))
    tv = any("TOTAL VEHICULE" in _norm(sh.cell_value(rr, 15)) for rr in range(head_row, min(head_row + 3, sh.nrows)))
    if not ok or not tv:
        alertes.append(
            f"Mise en page inattendue près de la ligne {head_row + 1} : vérifiez que les colonnes "
            "F (20' plein) et P (TOTAL VEHICULE) sont à leur place habituelle."
        )


def parse_volumes(data: bytes, filename: str) -> VolumesResult:
    book = _open(data)
    sh = _pick_volumes_sheet(book)
    blocks = _find_blocks(sh)
    if len(blocks) < 2:
        raise SourceError(
            f"Blocs IMPORT/EXPORT introuvables dans la feuille « {sh.name.strip()} ». "
            "Chaque bloc doit commencer par une ligne ORDRE / NAVIRES et finir par une ligne TOTAL."
        )
    alertes: list[str] = []
    rows, totaux = [], {}
    for (head, start, tot), sens in zip(blocks[:2], ["Import", "Export"]):
        _check_header(sh, head, alertes)
        for r in range(start, tot):
            nav = str(sh.cell_value(r, VOL_COLS["navire"]) or "").strip()
            if not nav or not isinstance(sh.cell_value(r, 0), float):
                continue
            rec = {
                "sens": sens,
                "navire": nav,
                "navire_cle": ship_key(nav),
                "armateur": str(sh.cell_value(r, VOL_COLS["armateur"]) or "").strip(),
                "debut": _xl_date(sh.cell_value(r, VOL_COLS["debut"]), book.datemode),
                "fin": _xl_date(sh.cell_value(r, VOL_COLS["fin"]), book.datemode),
                "ligne_excel": r + 1,
            }
            for k in NUM_FIELDS:
                rec[k] = _num(sh.cell_value(r, VOL_COLS[k]))
            rows.append(rec)
        totaux[sens] = {k: _num(sh.cell_value(tot, VOL_COLS[k])) for k in NUM_FIELDS}
        totaux[sens]["ligne_excel"] = tot + 1

    df = pd.DataFrame(rows)
    if df.empty:
        raise SourceError("Aucune escale lue dans le classeur : les lignes navires sont vides.")

    # Mois du rapport = mois majoritaire des dates de fin d'opérations (FINITION)
    dates = [d for d in df["debut"].dropna()]
    if not dates:
        raise SourceError("Dates de FINITION absentes : impossible de déterminer le mois du classeur.")
    (annee, mois), _ = Counter((d.year, d.month) for d in dates).most_common(1)[0]

    # Contrôle interne : somme des lignes = ligne TOTAL du fichier
    for sens, tot in totaux.items():
        sub = df[df["sens"] == sens]
        for k in ("veh_total", "veh_neufs", "veh_usages", "c20_plein", "c40_plein", "c20_vide", "c40_vide"):
            s = sub[k].sum()
            if round(s) != round(tot[k]):
                alertes.append(
                    f"{sens} · {k} : la somme des navires ({s:.0f}) diffère de la ligne TOTAL du fichier "
                    f"({tot[k]:.0f}, ligne {tot['ligne_excel']})."
                )
    return VolumesResult(filename, sh.name.strip(), annee, mois, df, totaux, alertes)


# ---------------------------------------------------------------------------
# 2. Extrait PAA (tranches de volume)
# ---------------------------------------------------------------------------
PAA_REQUIRED = ["MLIBOR", "MNCHAN", "MCHANT", "MDATDC", "MDATFC", "MLIBRU", "MUNITA", "MTOTLN", "MSTNAV"]
TYPE_NAVIRE = {"RORO": "Ro/Ro", "CARCAR": "Car carrier", "COMBONG": "Lo/Lo"}


def classify_rubrique(libelle: str) -> tuple[str | None, str | None, str]:
    """Retourne (sens, tranche, statut) pour une rubrique véhicule PAA.

    Règle (vérifiée sur septembre 2026, = reporting à 1 véhicule près) :
    - comptées : déchargement « UNL… » (Import) et chargement « LOAD… »
      (Export), transbordement TBT compris ;
    - exclues : mouvements bord à bord / shifting (« SHIFT », « SHI », « B/T/B »),
      qui ne sont pas des véhicules débarqués ou embarqués.
    """
    lib = _norm(libelle)
    if lib.startswith(("SHIFT", "SHI ", "B/T/B", "B/B")):
        return None, None, "exclue (shifting / bord à bord)"
    if lib.startswith("UNL"):
        sens = "Import"
    elif lib.startswith("LOA"):
        sens = "Export"
    else:
        return None, None, "exclue (rubrique non reconnue)"
    compact = lib.replace(" ", "")
    if ">50" in compact:
        return sens, ">50", "comptée"
    if ">=15" in compact or "<=50" in compact:
        return sens, "15-50", "comptée"
    if "<15" in compact:
        return sens, "<15", "comptée"
    return None, None, "exclue (tranche non reconnue)"


def parse_paa(data: bytes, filename: str) -> PaaResult:
    book = _open(data)
    sh = book.sheet_by_index(0)
    head = [_norm(x) for x in sh.row_values(0)]
    missing = [c for c in PAA_REQUIRED if c not in head]
    if missing:
        raise SourceError(
            "Ce fichier n'est pas un extrait PAA mensuel : colonnes manquantes "
            + ", ".join(missing) + ". Chargez « STATISTIQUES TERRA <MOIS> <AAAA>.xls »."
        )
    idx = {c: head.index(c) for c in PAA_REQUIRED}
    keep, drop = [], []
    for r in range(1, sh.nrows):
        g = lambda c: sh.cell_value(r, idx[c])
        if _norm(g("MLIBOR")) != "TERRA" or _norm(g("MUNITA")) != "VH":
            continue
        sens, tranche, statut = classify_rubrique(g("MLIBRU"))
        rec = {
            "navire_paa": str(g("MNCHAN")).strip(),
            "navire_cle": ship_key(g("MNCHAN")),
            "escale_paa": str(g("MCHANT")).replace(".0", ""),
            "debut": _paa_date(g("MDATDC")),
            "fin": _paa_date(g("MDATFC")),
            "type_navire": TYPE_NAVIRE.get(_norm(g("MSTNAV")), _norm(g("MSTNAV")).title()),
            "rubrique": str(g("MLIBRU")).strip(),
            "sens": sens,
            "tranche": tranche,
            "quantite": _num(g("MTOTLN")),
            "ligne_excel": r + 1,
            "statut": statut,
        }
        (keep if sens else drop).append(rec)
    lignes, exclues = pd.DataFrame(keep), pd.DataFrame(drop)
    alertes = []
    if lignes.empty:
        raise SourceError("Aucune ligne véhicule TERRA (MLIBOR = TERRA, MUNITA = VH) dans cet extrait PAA.")
    dts = [d for d in lignes["debut"].dropna()]
    annee = mois = None
    if dts:
        (annee, mois), _ = Counter((d.year, d.month) for d in dts).most_common(1)[0]
    return PaaResult(filename, sh.name.strip(), annee, mois, lignes, exclues, alertes)


def match_paa_to_escales(escales: pd.DataFrame, paa: pd.DataFrame) -> dict:
    """Associe chaque escale PAA (MCHANT) à un navire du classeur volumes :
    le nom PAA (tronqué à 14 caractères) doit être le début du nom du
    classeur ; en cas de doublon (même navire deux fois dans le mois), la
    date de début la plus proche l'emporte. Retourne {escale_paa: navire}."""
    nav = escales.drop_duplicates("navire")[["navire", "navire_cle", "debut"]]
    out = {}
    for esc, grp in paa.groupby("escale_paa"):
        key = grp["navire_cle"].iloc[0]
        d0 = grp["debut"].iloc[0]
        cands = nav[nav["navire_cle"].str.startswith(key) | nav["navire_cle"].apply(lambda k: key.startswith(k))]
        if cands.empty:
            continue
        if len(cands) > 1 and d0 is not None:
            cands = cands.assign(_gap=cands["debut"].apply(
                lambda d: abs((d.date() - d0).days) if d is not None else 999)).sort_values("_gap")
        out[esc] = cands["navire"].iloc[0]
    return out
