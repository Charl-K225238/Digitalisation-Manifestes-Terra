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


class _XlsxSheet:
    """Feuille .xlsx exposée avec l'interface xlrd utilisée par les lecteurs (valeurs en cache)."""

    def __init__(self, ws):
        self.name = ws.title
        self._rows = [[self._conv(c) for c in row] for row in ws.iter_rows(values_only=True)]
        self.nrows = len(self._rows)
        self.ncols = max((len(r) for r in self._rows), default=0)

    @staticmethod
    def _conv(v):
        from openpyxl.utils.datetime import to_excel
        if v is None:
            return ""
        if isinstance(v, bool):
            return float(v)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, (datetime, date)):
            return float(to_excel(v))
        return v

    def cell_value(self, r, c):
        row = self._rows[r] if r < self.nrows else []
        return row[c] if c < len(row) else ""

    def row_values(self, r):
        return [self.cell_value(r, c) for c in range(self.ncols)]


class _XlsxBook:
    datemode = 0

    def __init__(self, data: bytes):
        import io
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        self._sheets = [_XlsxSheet(ws) for ws in wb.worksheets]

    def sheets(self):
        return self._sheets

    def sheet_by_index(self, i):
        return self._sheets[i]


def _open(data: bytes):
    if data[:2] == b"PK":  # .xlsx (archive zip)
        try:
            return _XlsxBook(data)
        except Exception as exc:
            raise SourceError("Classeur .xlsx illisible.") from exc
    try:
        return xlrd.open_workbook(file_contents=data)
    except Exception as exc:
        raise SourceError(
            "Fichier illisible. Chargez le classeur .xls ou .xlsx tel qu'il est enregistré dans le dossier "
            "PAA."
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


def _cols_for(sh, head_row: int) -> dict:
    """Index de colonnes du bloc : la mise en page de référence, décalée si besoin.
    Le classeur de janvier insère deux colonnes (NB SHIFT, NB EQP) avant les conteneurs ;
    le décalage se déduit de la colonne « TOTAL VEHICULES »."""
    rng = range(head_row, min(head_row + 3, sh.nrows))
    for rr in rng:
        for c in range(5, sh.ncols):
            if "TOTAL VEHICULE" in _norm(sh.cell_value(rr, c)):
                off = c - VOL_COLS["veh_total"]
                return {k: (v + off if v >= 5 else v) for k, v in VOL_COLS.items()}
    return dict(VOL_COLS)


def _check_header(sh, head_row: int, cols: dict, alertes: list):
    """Vérifie que les colonnes 20'/40' et véhicules sont bien là où on les attend."""
    rng = range(head_row, min(head_row + 3, sh.nrows))
    ok = any(_norm(sh.cell_value(rr, cols["c20_plein"])).startswith("20") for rr in rng)
    tv = any("TOTAL VEHICULE" in _norm(sh.cell_value(rr, cols["veh_total"])) for rr in rng)
    if not ok or not tv:
        alertes.append(
            f"Mise en page inattendue près de la ligne {head_row + 1} : vérifiez que les colonnes "
            "20' plein et TOTAL VEHICULE sont à leur place habituelle."
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
        cols = _cols_for(sh, head)
        if max(cols.values()) >= sh.ncols:
            raise SourceError(
                f"Feuille « {sh.name.strip()} » trop étroite : les colonnes attendues "
                "(jusqu'à DT VEHICULES TBT) sont absentes. Vérifiez qu'il s'agit du bon classeur."
            )
        _check_header(sh, head, cols, alertes)
        for r in range(start, tot):
            nav = str(sh.cell_value(r, cols["navire"]) or "").strip()
            if not nav or not isinstance(sh.cell_value(r, 0), float):
                continue
            rec = {
                "sens": sens,
                "navire": nav,
                "navire_cle": ship_key(nav),
                "armateur": str(sh.cell_value(r, cols["armateur"]) or "").strip(),
                "debut": _xl_date(sh.cell_value(r, cols["debut"]), book.datemode),
                "fin": _xl_date(sh.cell_value(r, cols["fin"]), book.datemode),
                "ligne_excel": r + 1,
            }
            for k in NUM_FIELDS:
                rec[k] = _num(sh.cell_value(r, cols[k]))
            rows.append(rec)
        totaux[sens] = {k: _num(sh.cell_value(tot, cols[k])) for k in NUM_FIELDS}
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
    elif lib.startswith(("LOA", "LAOD")):
        sens = "Export"
    else:
        return None, None, "exclue (rubrique non reconnue)"
    compact = lib.replace(" ", "")
    statut = "comptée (faute de frappe PAA : LAOD)" if lib.startswith("LAOD") else "comptée"
    if ">50" in compact:
        return sens, ">50", statut
    if ">=15" in compact or "<=50" in compact:
        return sens, "15-50", statut
    if "<15" in compact:
        return sens, "<15", statut
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
        # dates incohérentes (ex. année mal saisie) : escales hors du mois majoritaire
        hors = lignes[lignes["debut"].notna()]
        hors = hors[hors["debut"].apply(lambda d: abs((d.year * 12 + d.month) - (annee * 12 + mois)) >= 2)]
        for esc, g in hors.groupby("escale_paa"):
            alertes.append(f"PAA : escale {esc} ({g['navire_paa'].iloc[0]}) a une date de début du "
                           f"{g['debut'].iloc[0]:%d/%m/%Y}, à plus d'un mois du mois détecté — date PAA à vérifier.")
    # rubriques véhicule non reconnues : jamais écartées en silence
    if not exclues.empty:
        nr = exclues[exclues["statut"].str.contains("non reconnue")]
        for rub, g in nr.groupby("rubrique"):
            alertes.append(f"PAA : rubrique « {rub} » non reconnue, {g['quantite'].sum():.0f} véhicule(s) "
                           f"NON comptés (escales {', '.join(sorted(set(g['escale_paa'])))}).")
    # types de navire inconnus
    for t in sorted(set(lignes["type_navire"]) - set(TYPE_NAVIRE.values())):
        g = lignes[lignes["type_navire"] == t]
        alertes.append(f"PAA : type de navire « {t} » inconnu ({', '.join(sorted(set(g['navire_paa'])))}, "
                       f"{g['quantite'].sum():.0f} véhicule(s)) — traité comme hors Lo/Lo ; à confirmer.")
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
