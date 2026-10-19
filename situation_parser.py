"""Lecture du fichier « Situation navires RORO » (classeur .xlsm tenu par les agents).

Fonctions pures (pandas), sans Streamlit. Deux sources dans le classeur :

* onglet « SITUATION NAVIRES RORO » (et « NAVIRES EN INSTANCE ») : sections
  VESSELS COMPLETED / OPERATING / EXPECTED, une ligne par navire avec les
  unités import / export (20', 40', RR, MAFI…), le total des mouvements et
  l'Observation saisie par l'agent (« dt 155ro neufs, 158ro de plus 50m3 /
  29 Rlts en transit / 27x40' Vides export ») ;
* onglets « CUMUL <MOIS> <ANNEE> » : la liste des navires terminés du mois
  (type, armateur, dates). Le nom de l'onglet peut porter une année erronée
  (« CUMUL JUIN 2025 » dans le classeur 2026) : seul le mois est lu.

Le détail d'un navire terminé disparaît de la section COMPLETED au fil des
jours : l'app mémorise donc chaque ligne lue (voir note_volumes_store).
Rien n'est deviné : une valeur absente reste None.
"""
from __future__ import annotations

import io
import re
import unicodedata

import pandas as pd

MOIS = ["JANVIER", "FEVRIER", "MARS", "AVRIL", "MAI", "JUIN", "JUILLET", "AOUT",
        "SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DECEMBRE"]
SECTIONS = {"VESSELS COMPLETED": "Terminé", "VESSELS OPERATING": "En cours", "VESSELS EXPECTED": "Prévu"}
TYPES = {"COMBONG": "LOLO"}          # règle validée 19/10/2026 : LOLO = COMBONG

# Colonnes d'unités : (bloc, libellé normalisé de l'en-tête) -> nom interne
_UNIT_COLS = {
    ("imp", "20"): "imp_20", ("imp", "40"): "imp_40", ("imp", "FULL BOLST"): "imp_bolst_full",
    ("imp", "MTY BOLST"): "imp_bolst_mty", ("imp", "RR"): "imp_rr", ("imp", "MAFI"): "imp_mafi",
    ("imp", "GAL CGO"): "imp_gc",
    ("exp", "20"): "exp_20", ("exp", "40"): "exp_40", ("exp", "MTY BOLST"): "exp_bolst_mty",
    ("exp", "FULL BOLST"): "exp_bolst_full", ("exp", "RR"): "exp_rr", ("exp", "MTY MAFI"): "exp_mafi_mty",
    ("exp", "MAFI FULL"): "exp_mafi_full", ("exp", "FULL MAFI"): "exp_mafi_full",
    ("exp", "SAWN TIMB."): "exp_bois", ("exp", "GAL CGO"): "exp_gc",
}
UNIT_FIELDS = sorted(set(_UNIT_COLS.values()))


def _norm(v) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)                     # en-tête « 40 » lu 40.0
    s = unicodedata.normalize("NFKD", str(v if v is not None else "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def _num(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _date(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "":
        return None
    t = pd.to_datetime(v, errors="coerce", dayfirst=True)
    return None if pd.isna(t) else t.to_pydatetime()


def ship_key(name) -> str:
    """Nom sans le voyage : « GREAT LAGOS GTL0726 » -> « GREAT LAGOS »,
    « VIMC BRAVE V.26261 » -> « VIMC BRAVE »."""
    words = _norm(name).replace(".", ". ").split()
    out = []
    for w in words:
        if w in ("V.", "V", "VOY", "VOY.", "VGE") or re.fullmatch(r"[A-Z]{2,4}\d{3,}[A-Z]?", w) \
                or re.fullmatch(r"\d{2,}[A-Z]?", w):
            break
        out.append(w)
    return " ".join(out).replace(". ", ".").strip()


def voyage_key(v) -> str:
    """Voyage comparable entre sources : « V.26261 » / « 26261 » -> « 26261 »,
    « GTL0726 » -> « GTL0726 »."""
    s = _norm(v)
    s = re.sub(r"^(?:V\.?|VOY\.?|VGE\.?)\s*", "", s)
    return re.sub(r"[^A-Z0-9]", "", s)


def split_name(full) -> tuple[str, str]:
    """« GREAT LAGOS GTL0726 » -> (« GREAT LAGOS », « GTL0726 »)."""
    key = ship_key(full)
    rest = _norm(full)[len(key):].strip()
    return key, voyage_key(rest)


def escale_id(navire, voyage) -> str:
    return f"{ship_key(navire)}|{voyage_key(voyage)}"


def ligne_of(armateur) -> str:
    """« GRIMALDI (ATL) » -> « ATL » ; sinon ""."""
    m = re.search(r"\((ATL|MED)\)", _norm(armateur))
    return m.group(1) if m else ""


def type_of(t) -> str:
    t = _norm(t)
    return TYPES.get(t, t)


# ── Observation ──────────────────────────────────────────────────────────────
_RE_NEUFS = re.compile(r"(\d+)\s*RO\s*NEUFS?")
_RE_GT50 = re.compile(r"(\d+)\s*RO\s*(?:DE\s*)?PLUS\s*(?:DE\s*)?50\s*M3")
_RE_TRANSIT = re.compile(r"(\d+)\s*RLTS?\s*EN\s*TRANSIT")
_RE_TC = re.compile(r"(\d+)\s*X\s*(20|40|45)\s*'?")


def _tc_count(part: str) -> dict:
    out = {"20": 0, "40": 0}
    for n, size in _RE_TC.findall(part):
        out["20" if size == "20" else "40"] += int(n)
    return out


def parse_observation(text) -> dict:
    """Extrait les compteurs saisis par l'agent dans l'Observation.
    Les vides sont lus dans le morceau de phrase qui contient « VIDE » et
    « EXPORT » (resp. « IMPORT ») : « 52x20' + 17x40' vides export »,
    « import vides: 25x20' tanks »."""
    t = _norm(text)
    out = {"obs_neufs": None, "obs_gt50": None, "obs_transit": None,
           "obs_vides_exp_20": None, "obs_vides_exp_40": None,
           "obs_vides_imp_20": None, "obs_vides_imp_40": None}
    if not t:
        return out
    for key, rx in (("obs_neufs", _RE_NEUFS), ("obs_gt50", _RE_GT50), ("obs_transit", _RE_TRANSIT)):
        m = rx.search(t)
        if m:
            out[key] = int(m.group(1))
    for part in re.split(r"[/;]|\.\s", t):
        if "VIDE" not in part:
            continue
        sens = "exp" if "EXPORT" in part else ("imp" if "IMPORT" in part else None)
        if not sens:
            continue
        c = _tc_count(part)
        for size in ("20", "40"):
            k = f"obs_vides_{sens}_{size}"
            out[k] = (out[k] or 0) + c[size]
    return out


# ── Lecture du classeur ──────────────────────────────────────────────────────
def _sections(df: pd.DataFrame, sheet: str, default_statut: str | None = None) -> list[dict]:
    rows, statut, header, blocks = [], default_statut, None, {}
    n = len(df)
    i = 0
    while i < n:
        c0 = _norm(df.iat[i, 0]) if df.shape[1] else ""
        if c0 in SECTIONS:
            statut, header, blocks = SECTIONS[c0], None, {}
            i += 1
            continue
        c1 = _norm(df.iat[i, 1]) if df.shape[1] > 1 else ""
        if c1.startswith("TYPE") and statut:
            header = [_norm(x) for x in df.iloc[i].tolist()]
            # Blocs import / export : la ligne au-dessus porte IMPORT/DISCHARGE et EXPORT/LOADING
            above = [_norm(x) for x in df.iloc[i - 1].tolist()] if i else []
            imp_start = next((j for j, x in enumerate(above) if x.startswith("IMPORT")), 11)
            exp_start = next((j for j, x in enumerate(above) if x.startswith("EXPORT")), 18)
            tot = next((j for j, x in enumerate(above) if x.startswith("TOTAL")), len(header) - 2)
            blocks = {"imp": (imp_start, exp_start), "exp": (exp_start, tot), "tot": tot}
            i += 1
            continue
        if header and c0 and c0 not in ("", " "):
            r = df.iloc[i].tolist()
            if not re.search(r"[A-Z]", c0):          # numéro de ligne isolé en bas d'onglet
                i += 1
                continue
            rec = {"navire_brut": str(df.iat[i, 0]).strip(), "statut": statut, "onglet": sheet,
                   "type": type_of(r[1]), "armateur": str(r[2] or "").strip() if r[2] is not None else "",
                   "agent": str(r[3] or "").strip() if r[3] is not None else "",
                   "debut": _date(r[6]), "fin": _date(r[7]), "sortie": _date(r[8]),
                   "poste": str(r[9] or "").strip() if len(r) > 9 and r[9] is not None else ""}
            if pd.isna(rec["armateur"]) if isinstance(rec["armateur"], float) else False:
                rec["armateur"] = ""
            for f in UNIT_FIELDS:
                rec[f] = None
            for bloc in ("imp", "exp"):
                a, b = blocks[bloc]
                for j in range(a, min(b, len(header))):
                    name = _UNIT_COLS.get((bloc, header[j]))
                    if name and rec.get(name) is None:
                        rec[name] = _num(r[j])
            tj = blocks["tot"]
            rec["total_moves"] = _num(r[tj]) if tj < len(r) else None
            obs = r[tj + 1] if tj + 1 < len(r) else None
            rec["observation"] = "" if obs is None or (isinstance(obs, float) and pd.isna(obs)) else str(obs).strip()
            rec.update(parse_observation(rec["observation"]))
            rec["navire"], rec["voyage"] = split_name(rec["navire_brut"])
            rec["ligne"] = ligne_of(rec["armateur"])
            rec["escale"] = f'{rec["navire"]}|{rec["voyage"]}'
            rows.append(rec)
        elif header and not c0 and i + 1 < n and _norm(df.iat[i + 1, 0]) in SECTIONS:
            header = None
        i += 1
    return rows


def _cumul(df: pd.DataFrame) -> list[dict]:
    hdr = None
    for i in range(min(len(df), 15)):
        if _norm(df.iat[i, 1]) == "NAVIRES":
            hdr = i
            break
    if hdr is None:
        return []
    cols = [_norm(x) for x in df.iloc[hdr].tolist()]

    def col(prefix):
        return next((j for j, x in enumerate(cols) if x.startswith(prefix)), None)

    jt, ja, jacc, jdeb, jfin, jsor = col("TYPE"), col("ARMATEUR"), col("DATE"), col("DEBUT"), col("FINITION"), col("SORTIE")
    out = []
    for i in range(hdr + 1, len(df)):
        name = df.iat[i, 1]
        if name is None or (isinstance(name, float) and pd.isna(name)) or not str(name).strip():
            continue
        if _norm(df.iat[i, 0]).startswith("CUMUL"):
            break
        nav, voy = split_name(name)
        arm = df.iat[i, ja] if ja is not None else ""
        arm = "" if arm is None or (isinstance(arm, float) and pd.isna(arm)) else str(arm).strip()
        out.append({"navire_brut": str(name).strip(), "navire": nav, "voyage": voy, "escale": f"{nav}|{voy}",
                    "type": type_of(df.iat[i, jt]) if jt is not None else "", "armateur": arm,
                    "ligne": ligne_of(arm),
                    "accostage": _date(df.iat[i, jacc]) if jacc is not None else None,
                    "debut": _date(df.iat[i, jdeb]) if jdeb is not None else None,
                    "fin": _date(df.iat[i, jfin]) if jfin is not None else None,
                    "sortie": _date(df.iat[i, jsor]) if jsor is not None else None})
    return out


def read_situation(data: bytes) -> dict:
    """Lit le classeur. Retourne {"navires": DataFrame (une ligne par navire
    des sections COMPLETED/OPERATING/EXPECTED et NAVIRES EN INSTANCE),
    "cumul": {n_mois: DataFrame des navires terminés}}.
    Lève ValueError si l'onglet SITUATION est introuvable."""
    try:
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None)
    except Exception as exc:
        raise ValueError(f"classeur illisible ({type(exc).__name__})") from exc
    sheets = {k: v.astype(object).where(pd.notna(v), None) for k, v in sheets.items()}
    sit = next((k for k in sheets if _norm(k).startswith("SITUATION")), None)
    if sit is None:
        raise ValueError("onglet « SITUATION NAVIRES RORO » introuvable")
    rows = _sections(sheets[sit], sit)
    inst = next((k for k in sheets if "INSTANCE" in _norm(k)), None)
    if inst:
        rows += _sections(sheets[inst], inst, default_statut=None)
    navires = pd.DataFrame(rows)
    if not navires.empty:
        navires = navires.drop_duplicates("escale", keep="first").reset_index(drop=True)
    cumul = {}
    for k, df in sheets.items():
        nk = _norm(k)
        if not nk.startswith("CUMUL"):
            continue
        mois = next((m for m in MOIS if f" {m}" in f" {nk[5:]} "), None)
        if mois:
            cumul[MOIS.index(mois) + 1] = pd.DataFrame(_cumul(df))
    return {"navires": navires, "cumul": cumul}
