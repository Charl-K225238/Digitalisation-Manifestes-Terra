"""Formulaire d'opérations navire DC_GR-117 : lecture des fichiers et calculs.

Couche métier pure (aucun import Streamlit). Les fichiers sont lus en mémoire
(bytes) et ne sont jamais stockés.

Règles (validées le 13/11/2026) :
- Classe de volume : < 15 m³ / ≥ 15 et < 50 m³ / ≥ 50 m³.
- Volume : cubage du discharging report ; shifting : L × l × H si les
  dimensions sont saisies, sinon la classe choisie par le pointeur.
- Tonnage véhicules et conteneurs : somme des kg de la case, arrondie à la
  tonne supérieure. Cargo général : tonnage exact (3 décimales).
- Opérateur : armateur coque par défaut ; règle client → opérateur
  (Masque Tetrax) ou B/L → opérateur. Loading : colonne Exploitant.
- Shifting imputé à l'armateur coque.
- Loading : lignes « Non embarqué » exclues.
"""
from __future__ import annotations

import io
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

# ---------------------------------------------------------------- rubriques
CLASSES = ("<15", "15-50", ">=50")
LIBELLE_CLASSE = {"<15": "Moins de 15 m³", "15-50": "15 à 50 m³", ">=50": "50 m³ et plus"}

# (page, code) -> (libellé, unité). Seules les rubriques calculées sont listées.
RUBRIQUES = {
    # Discharge
    ("discharge", 201): ("Unl 20' mty", "U"), ("discharge", 202): ("Unl 40' mty", "U"),
    ("discharge", 203): ("Unl Bolster mty", "U"), ("discharge", 220): ("Unl 40' Platf empty", "U"),
    ("discharge", 274): ("Unl MAFI mty", "U"),
    ("discharge", 204): ("Unl 20' full", "U"), ("discharge", 205): ("Unl 20' full tshp", "U"),
    ("discharge", 214): ("Unl 20' full reef", "U"), ("discharge", 215): ("Unl 20' full reef tshp", "U"),
    ("discharge", 206): ("Unl 40' full", "U"), ("discharge", 207): ("Unl 40' full tshp", "U"),
    ("discharge", 216): ("Unl 40' full reefer", "U"), ("discharge", 217): ("Unl 40' full reefer tshp", "U"),
    ("discharge", 208): ("Unl Bolster full", "U"), ("discharge", 209): ("Unl Bolster full tshp", "U"),
    ("discharge", 221): ("Unl 40' Platf full", "U"), ("discharge", 140): ("Unl 40' Platf full tshp", "U"),
    ("discharge", 275): ("Unl MAFI full", "U"), ("discharge", 276): ("Unl MAFI full tshp", "U"),
    ("discharge", 222): ("Unl Cars < 15m3", "U"), ("discharge", 141): ("Unl Cars < 15m3 Tshp", "U"),
    ("discharge", 223): ("Unl Trucks >= 15m3, < 50m3", "U"), ("discharge", 142): ("Unl Trucks Tshp >= 15m3, < 50m3", "U"),
    ("discharge", 224): ("Unl Roro > 50m3", "U"), ("discharge", 143): ("Unl Roro > 50m3 tshp", "U"),
    ("discharge", 263): ("Unl General Cargo", "T"),
    # Loading
    ("loading", 301): ("Load 20' mty", "U"), ("loading", 302): ("Load 40' mty", "U"),
    ("loading", 303): ("Load Bolster mty", "U"), ("loading", 355): ("Load 40' PLATF mty", "U"),
    ("loading", 318): ("Load MAFI mty", "U"),
    ("loading", 304): ("Load 20' full", "U"), ("loading", 305): ("Load 20' full tshp", "U"),
    ("loading", 314): ("Load 20' full reef", "U"), ("loading", 315): ("Load 20' full reef tshp", "U"),
    ("loading", 306): ("Load 40' full", "U"), ("loading", 307): ("Load 40' full tshp", "U"),
    ("loading", 316): ("Load 40' full reefer", "U"), ("loading", 317): ("Load 40' full reefer tshp", "U"),
    ("loading", 308): ("Load Bolster full", "U"), ("loading", 309): ("Load Bolster full tshp", "U"),
    ("loading", 356): ("Load 40' Platf full", "U"), ("loading", 365): ("Load 40' Platf full tshp", "U"),
    ("loading", 0): ("Load MAFI full", "U"),  # pas de code imprimé sur le formulaire
    ("loading", 320): ("Load MAFI full tshp", "U"),
    ("loading", 357): ("Load Cars < 15m3", "U"), ("loading", 366): ("Load Cars < 15m3 tshp", "U"),
    ("loading", 358): ("Load Trucks >= 15m3, < 50m3", "U"), ("loading", 367): ("Load Trucks >= 15m3, < 50m3 tshp", "U"),
    ("loading", 359): ("Load roro > 50m3", "U"), ("loading", 368): ("Load roro > 50m3 tshp", "U"),
    ("loading", 345): ("Load General Cargo", "T"),
    # Shifting
    ("shifting", 127): ("Shift S/S Cars < 15m3", "U"), ("shifting", 128): ("Shift S/S Trucks >= 15m3, < 50m3", "U"),
    ("shifting", 130): ("Shift S/S Roro > 50m3", "U"),
    ("shifting", 134): ("Shift S/S/S Cars < 15m3", "U"), ("shifting", 135): ("Shift S/S/S Trucks >= 15m3, < 50m3", "U"),
    ("shifting", 136): ("Shift S/S/S Roro > 50m3", "U"),
}
CODE_VEHICULE = {  # (page, classe, transbo) -> code
    ("discharge", "<15", False): 222, ("discharge", "<15", True): 141,
    ("discharge", "15-50", False): 223, ("discharge", "15-50", True): 142,
    ("discharge", ">=50", False): 224, ("discharge", ">=50", True): 143,
    ("loading", "<15", False): 357, ("loading", "<15", True): 366,
    ("loading", "15-50", False): 358, ("loading", "15-50", True): 367,
    ("loading", ">=50", False): 359, ("loading", ">=50", True): 368,
}
CODE_SHIFT = {("S/S", "<15"): 127, ("S/S", "15-50"): 128, ("S/S", ">=50"): 130,
              ("S/S/S", "<15"): 134, ("S/S/S", "15-50"): 135, ("S/S/S", ">=50"): 136}
# (taille, vp, reefer, transbo) -> code loading conteneurs
CODE_TC_LOAD = {
    ("20", "V"): 301, ("40", "V"): 302, ("BOL", "V"): 303, ("PLATF", "V"): 355, ("MAFI", "V"): 318,
    ("20", "P"): 304, ("20", "PT"): 305, ("20", "R"): 314, ("20", "RT"): 315,
    ("40", "P"): 306, ("40", "PT"): 307, ("40", "R"): 316, ("40", "RT"): 317,
    ("BOL", "P"): 308, ("BOL", "PT"): 309, ("PLATF", "P"): 356, ("PLATF", "PT"): 365,
    ("MAFI", "P"): 0, ("MAFI", "PT"): 320,
}
SEUIL_PROCHE = 0.1  # m³ autour de 15 et 50 pour l'alerte « proche d'une limite »


# ---------------------------------------------------------------- utilitaires
def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def _num(v) -> float | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("\u00a0", "").replace(" ", "")
    if not s:
        return None
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _v(x):
    """NaN pandas -> None (évite les NaN « vrais » et les classes fausses)."""
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else x


def classe_volume(m3: float | None) -> str | None:
    m3 = _v(m3)
    if m3 is None or m3 <= 0:
        return None
    if m3 < 15:
        return "<15"
    if m3 < 50:
        return "15-50"
    return ">=50"


def tonnes_sup(kg: float) -> int:
    """Somme de kg -> tonnes arrondies à la tonne supérieure (0 kg -> 0)."""
    if not kg:
        return 0
    return math.ceil(round(kg, 3) / 1000 - 1e-9)


def _lire_brut(data: bytes, name: str, sheet=0) -> pd.DataFrame:
    n = name.lower()
    engine = "openpyxl" if n.endswith((".xlsx", ".xlsm")) else ("odf" if n.endswith(".ods") else None)
    if engine is None:
        try:
            return pd.read_excel(io.BytesIO(data), header=None, sheet_name=sheet, engine="calamine")
        except Exception:
            return pd.read_excel(io.BytesIO(data), header=None, sheet_name=sheet, engine="xlrd")
    return pd.read_excel(io.BytesIO(data), header=None, sheet_name=sheet, engine=engine)


def _ligne_entete(raw: pd.DataFrame, mots: tuple[str, ...], max_rows: int = 30) -> int:
    for i in range(min(max_rows, len(raw))):
        cells = " | ".join(_norm(x) for x in raw.iloc[i].tolist())
        if all(m in cells for m in mots):
            return i
    raise ValueError(f"En-tête introuvable (colonnes attendues : {', '.join(mots)})")


def _col(cols: list[str], *cles: str) -> int | None:
    for i, c in enumerate(cols):
        if any(k in c for k in cles):
            return i
    return None


def cle_client(s) -> str:
    """Clé de règle client : majuscules, sans accents ni ponctuation ni forme juridique."""
    k = re.sub(r"[^A-Z0-9 ]", "", _norm(s))
    k = re.sub(r"\b(SARL|SA|SAS|LTD|LIMITED|CO|INC)\b", "", k)
    return re.sub(r"\s+", " ", k).strip()


@dataclass
class Controle:
    niveau: str          # "corriger" | "verifier" | "ok"
    titre: str
    detail: str = ""
    cle: str = ""        # identifiant stable (pour l'interface)


# ---------------------------------------------------------------- lecteurs
def lire_discharging(data: bytes, name: str) -> tuple[pd.DataFrame, dict]:
    """Discharging report (VEHICULES IMPORT …). Une ligne par véhicule."""
    raw = _lire_brut(data, name)
    meta = {}
    for i in range(min(10, len(raw))):
        k, v = _norm(raw.iat[i, 0]), raw.iat[i, 1] if raw.shape[1] > 1 else None
        if k.startswith("NAVIRE"):
            meta["navire"] = str(v).strip()
        elif k.startswith("VOYAGE"):
            meta["voyage"] = str(v).strip()
        elif k.startswith("CONSIGNATAIRE"):
            meta["consignataire"] = str(v).strip()
        elif k.startswith("DATE ARRIV"):
            meta["date_arrivee"] = _date(v)
    h = _ligne_entete(raw, ("CHASSIS", "POIDS", "CUBAGE"))
    cols = [_norm(x) for x in raw.iloc[h].tolist()]
    idx = {k: _col(cols, *c) for k, c in {
        "ordre": ("ORDRE",), "bl": ("BL",), "pol": ("PORT",), "marque": ("MARQUE",),
        "modele": ("GENRE", "MODELE"), "chassis": ("CHASSIS",), "poids_kg": ("POIDS",),
        "volume_m3": ("CUBAGE",), "cycle": ("CYCLE",)}.items()}
    rows = []
    for r in raw.iloc[h + 1:].itertuples(index=False):
        r = list(r)
        ch = str(r[idx["chassis"]] or "").strip() if idx["chassis"] is not None else ""
        if not ch or ch.lower() == "nan":
            continue
        g = lambda k: r[idx[k]] if idx[k] is not None else None
        rows.append({
            "ordre": _num(g("ordre")), "bl": str(g("bl") or "").strip(), "pol": str(g("pol") or "").strip(),
            "marque": str(g("marque") or "").strip(), "modele": str(g("modele") or "").strip(),
            "chassis": ch, "poids_kg": _num(g("poids_kg")), "volume_m3": _num(g("volume_m3")),
            "transbo": "TRANS" in _norm(g("cycle")),
        })
    return pd.DataFrame(rows), meta


def lire_masque_tetrax(data: bytes, name: str) -> tuple[pd.DataFrame, dict]:
    """Masque Tetrax : n° de dossier et client par châssis."""
    raw = _lire_brut(data, name)
    h = _ligne_entete(raw, ("CHASSIS", "CLIENT"))
    cols = [_norm(x) for x in raw.iloc[h].tolist()]
    ic, icl, idos = _col(cols, "CHASSIS"), _col(cols, "CLIENT"), _col(cols, "COMPTE D'ESCALE", "COMPTE D ESCALE")
    iar = _col(cols, "ARMATEUR")
    df = raw.iloc[h + 1:, [ic, icl]].copy()
    df.columns = ["chassis", "client"]
    df["chassis"] = df["chassis"].astype(str).str.strip()
    df["client"] = df["client"].astype(str).str.strip()
    df = df[(df["chassis"] != "") & (df["chassis"].str.lower() != "nan")]
    meta = {}
    if idos is not None and len(raw) > h + 1:
        v = raw.iat[h + 1, idos]
        meta["n_dossier"] = str(int(v)) if isinstance(v, float) and v == int(v) else str(v).strip()
    if iar is not None and len(raw) > h + 1:
        meta["armateur"] = str(raw.iat[h + 1, iar]).strip()
    return df.reset_index(drop=True), meta


_RE_GC = re.compile(r"(\d+)\s*COLIS?\s*=\s*([\d.,]+)\s*KGS?\s*([\d.,]+)\s*M3", re.I)


def _kg_texte(s: str) -> float:
    """'8.820' / '10,280' / '1460' -> kg (séparateur de milliers . ou ,)."""
    s = s.strip()
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):
        return float(re.sub(r"[.,]", "", s))
    return float(s.replace(",", "."))


def lire_general_cargo(data: bytes, name: str) -> tuple[pd.DataFrame, dict]:
    """Rapport general cargo. Les lignes font foi ; la ligne TOTAL sert de contrôle."""
    raw = _lire_brut(data, name)
    h = _ligne_entete(raw, ("BL", "POIDS"))
    cols = [_norm(x) for x in raw.iloc[h].tolist()]
    ibl, ipv, inat = _col(cols, "BL"), _col(cols, "POIDS"), _col(cols, "NATURE")
    lignes, total = [], None
    for r in raw.iloc[h + 1:].itertuples(index=False):
        r = list(r)
        txt = " ".join(str(x) for x in r if str(x) != "nan")
        m = _RE_GC.search(str(r[ipv]) if ipv is not None else txt) or _RE_GC.search(txt)
        if not m:
            continue
        val = {"colis": int(m.group(1)), "poids_kg": _kg_texte(m.group(2)),
               "volume_m3": float(m.group(3).replace(".", "").replace(",", ".")) if "," in m.group(3)
               else float(m.group(3))}
        if "TOTAL" in _norm(txt):
            total = val
            continue
        val.update(bl=str(r[ibl]).strip() if ibl is not None else "",
                   nature=str(r[inat]).strip() if inat is not None else "")
        lignes.append(val)
    return pd.DataFrame(lignes), {"total_fichier": total}


def lire_loading(data: bytes, name: str) -> pd.DataFrame:
    """Loading report (état définitif). Une ligne par conteneur, avec statut."""
    raw = _lire_brut(data, name)
    h = _ligne_entete(raw, ("CONTENEUR", "ISO", "EXPLOITANT"))
    cols = [_norm(x) for x in raw.iloc[h].tolist()]
    g = {k: _col(cols, *c) for k, c in {
        "conteneur": ("CONTENEUR",), "iso": ("ISO",), "type": ("TYPE",), "poids_kg": ("POIDS",),
        "exploitant": ("EXPLOITANT",), "vp": ("V/P",), "validation": ("VALIDATION",), "et": ("E/T",)}.items()}
    rows = []
    for r in raw.iloc[h + 1:].itertuples(index=False):
        r = list(r)
        c = str(r[g["conteneur"]] or "").strip()
        if not c or c.lower() == "nan":
            continue
        rows.append({
            "conteneur": c, "taille_brute": str(r[g["iso"]]).strip(),
            "type_iso": str(r[g["type"]]).strip() if g["type"] is not None else "",
            "poids_kg": _num(r[g["poids_kg"]]), "exploitant": str(r[g["exploitant"]]).strip(),
            "vp": _norm(r[g["vp"]])[:1], "validation": _norm(r[g["validation"]]),
            "transbo": _norm(r[g["et"]]).startswith("T") if g["et"] is not None else False,
        })
    return pd.DataFrame(rows)


COLONNES_SHIFTING = ["N°", "Marque et modèle", "N° châssis", "Poids (t)", "Classe",
                     "Position", "Long (m)", "Larg (m)", "Haut (m)"]
POSITIONS = {"RESTE A BORD": "S/S", "DEBARQUE PUIS REMBARQUE": "S/S/S"}
CLASSES_SAISIE = {_norm(v): k for k, v in LIBELLE_CLASSE.items()}


def lire_fiche_shifting(data: bytes, name: str) -> pd.DataFrame:
    """Modèle Excel Terra « Fiche shifting »."""
    raw = _lire_brut(data, name)
    h = _ligne_entete(raw, ("CHASSIS", "POSITION"))
    cols = [_norm(x) for x in raw.iloc[h].tolist()]
    g = {k: _col(cols, c) for k, c in {
        "chassis": "CHASSIS", "marque": "MARQUE", "poids_t": "POIDS", "classe": "CLASSE",
        "position": "POSITION", "long": "LONG", "larg": "LARG", "haut": "HAUT"}.items()}
    rows = []
    for n, r in enumerate(raw.iloc[h + 1:].itertuples(index=False), start=1):
        r = list(r)
        val = lambda k: r[g[k]] if g[k] is not None else None
        ch = str(val("chassis") or "").strip()
        if not ch or ch.lower() == "nan":
            if all(str(x).strip() in ("", "nan") for x in r):
                continue
        rows.append({
            "ligne": n, "chassis": "" if ch.lower() == "nan" else ch,
            "marque": str(val("marque") or "").replace("nan", "").strip(),
            "poids_t": _num(val("poids_t")),
            "classe_saisie": CLASSES_SAISIE.get(_norm(val("classe"))),
            "position": POSITIONS.get(_norm(val("position"))),
            "long": _num(val("long")), "larg": _num(val("larg")), "haut": _num(val("haut")),
        })
    return pd.DataFrame(rows)


def _date(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, (int, float)):
        return (pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(v))).to_pydatetime()
    if isinstance(v, datetime):
        return v
    try:
        return pd.to_datetime(str(v), dayfirst=True).to_pydatetime()
    except Exception:
        return None


# ---------------------------------------------------------------- calcul
@dataclass
class Entree:
    discharging: tuple[bytes, str] | None = None
    loading: tuple[bytes, str] | None = None
    masque_tetrax: tuple[bytes, str] | None = None
    general_cargo: tuple[bytes, str] | None = None
    shifting: tuple[bytes, str] | None = None
    armateur: str = ""                                          # code opérateur armateur coque
    regles_client: dict[str, str] = field(default_factory=dict)  # cle_client(client) -> code
    regles_bl: dict[str, str] = field(default_factory=dict)      # B/L -> code
    exploitants: dict[str, str] = field(default_factory=dict)   # exploitant loading -> code
    ts_total_vehicules: int | None = None
    ts_total_shifting: int | None = None


@dataclass
class Resultat:
    cases: dict = field(default_factory=dict)   # (page, code, operateur) -> {"unites", "kg", "tonnes"}
    detail: pd.DataFrame = field(default_factory=pd.DataFrame)
    controles: list[Controle] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    clients: pd.DataFrame = field(default_factory=pd.DataFrame)  # client, véhicules, opérateur

    def total(self, page: str, codes=None) -> int:
        return sum(v["unites"] for (p, c, _), v in self.cases.items()
                   if p == page and (codes is None or c in codes) and RUBRIQUES[(p, c)][1] == "U")


def _ajouter(cases, page, code, op, kg, unites=1):
    kg = _v(kg)
    k = (page, code, op)
    c = cases.setdefault(k, {"unites": 0, "kg": 0.0})
    c["unites"] += unites
    c["kg"] += kg or 0.0


def calculer(e: Entree) -> Resultat:
    res, ctr, det = Resultat(), [], []
    cases = {}
    arm = e.armateur

    # --- discharge véhicules
    if e.discharging:
        dis, meta = lire_discharging(*e.discharging)
        res.meta.update(meta)
        clients = {}
        if e.masque_tetrax:
            mt, mmeta = lire_masque_tetrax(*e.masque_tetrax)
            res.meta.update({k: v for k, v in mmeta.items() if v})
            clients = dict(zip(mt["chassis"], mt["client"]))
            absents = sorted(set(dis["chassis"]) - set(clients))
            if absents:
                ctr.append(Controle("verifier", f"{len(absents)} véhicule(s) absent(s) du Masque Tetrax",
                                    ", ".join(absents[:5]), "tetrax_absents"))
        dis["client"] = dis["chassis"].map(clients).fillna("")
        def op_de(r):
            if r["bl"] in e.regles_bl:
                return e.regles_bl[r["bl"]]
            return e.regles_client.get(cle_client(r["client"]), arm)
        dis["operateur"] = dis.apply(op_de, axis=1)
        dis["classe"] = dis["volume_m3"].map(classe_volume)
        dup = dis[dis.duplicated("chassis", keep=False)]
        if len(dup):
            ctr.append(Controle("corriger", "Châssis en double (discharging report)",
                                ", ".join(sorted(set(dup["chassis"]))[:5]), "dis_doublons"))
        sansvol = dis[dis["classe"].isna()]
        if len(sansvol):
            ctr.append(Controle("corriger", f"{len(sansvol)} véhicule(s) sans volume",
                                ", ".join(sansvol["chassis"].head(5)), "dis_sans_volume"))
        sanspoids = dis[dis["poids_kg"].isna() | (dis["poids_kg"] <= 0)]
        if len(sanspoids):
            ctr.append(Controle("corriger", f"{len(sanspoids)} véhicule(s) sans poids",
                                ", ".join(sanspoids["chassis"].head(5)), "dis_sans_poids"))
        proches = dis[dis["volume_m3"].apply(lambda v: v is not None and any(abs(v - s) <= SEUIL_PROCHE for s in (15, 50)))]
        if len(proches):
            ctr.append(Controle("verifier", f"{len(proches)} véhicule(s) proche(s) d'une limite de volume",
                                ", ".join(f"{v:g} m³" for v in proches["volume_m3"].head(5)), "dis_seuils"))
        if dis["ordre"].notna().any():
            attendu = int(dis["ordre"].max())
            if attendu != len(dis):
                ctr.append(Controle("verifier", "Numérotation du discharging report incomplète",
                                    f"{len(dis)} lignes pour un n° d'ordre max de {attendu}", "dis_ordre"))
        for r in dis[dis["classe"].notna()].itertuples():
            code = CODE_VEHICULE[("discharge", r.classe, r.transbo)]
            _ajouter(cases, "discharge", code, r.operateur, r.poids_kg)
            det.append({"page": "discharge", "code": code, "operateur": r.operateur, "reference": r.chassis,
                        "bl": r.bl, "client": r.client, "poids_kg": r.poids_kg, "volume_m3": r.volume_m3,
                        "classe": r.classe})
        res.clients = (dis.groupby(["client", "operateur"], dropna=False).size()
                       .reset_index(name="vehicules").sort_values("vehicules", ascending=False))
        ctr.append(Controle("ok", "Véhicules débarqués", f"{len(dis)} véhicules, {dis['poids_kg'].sum():,.0f} kg"
                            .replace(",", " "), "dis_total"))
        if e.ts_total_vehicules is not None and e.ts_total_vehicules != len(dis):
            ctr.append(Controle("verifier", "Véhicules différents du time sheet",
                                f"{len(dis)} contre {e.ts_total_vehicules}", "ts_vehicules"))

    # --- discharge cargo général
    if e.general_cargo:
        gc, gmeta = lire_general_cargo(*e.general_cargo)
        if len(gc):
            kg = float(gc["poids_kg"].sum())
            _ajouter(cases, "discharge", 263, arm, kg, unites=int(gc["colis"].sum()))
            for r in gc.itertuples():
                det.append({"page": "discharge", "code": 263, "operateur": arm, "reference": r.nature,
                            "bl": r.bl, "poids_kg": r.poids_kg, "volume_m3": r.volume_m3, "colis": r.colis})
            t = gmeta.get("total_fichier")
            if t and (abs(t["poids_kg"] - kg) > 0.5 or abs(t["volume_m3"] - gc["volume_m3"].sum()) > 0.001
                      or t["colis"] != gc["colis"].sum()):
                ctr.append(Controle("verifier", "Total du rapport general cargo différent des lignes",
                                    f"Fichier : {t['colis']} colis, {t['poids_kg']:g} kg, {t['volume_m3']:g} m³ · "
                                    f"lignes : {int(gc['colis'].sum())} colis, {kg:g} kg, "
                                    f"{gc['volume_m3'].sum():g} m³ (les lignes font foi)", "gc_total"))

    # --- loading
    if e.loading:
        ld = lire_loading(*e.loading)
        non = ld[~ld["validation"].str.startswith("EMBARQU")]
        ld = ld[ld["validation"].str.startswith("EMBARQU")]
        if len(non):
            ctr.append(Controle("ok", f"{len(non)} conteneur(s) « non embarqué » écarté(s)",
                                ", ".join(non["conteneur"].head(5)), "ld_non_embarque"))
        dup = ld[ld.duplicated("conteneur", keep=False)]
        if len(dup):
            ctr.append(Controle("corriger", "Conteneur en double (loading report)",
                                ", ".join(sorted(set(dup["conteneur"]))[:5]), "ld_doublons"))
        inconnus = []
        for r in ld.itertuples():
            taille = _taille_tc(r.taille_brute, r.type_iso)
            reef = r.type_iso[2:3].upper() == "R"
            cle_vp = "V" if r.vp == "V" else ("R" if reef else "P") + ("T" if r.transbo else "")
            code = CODE_TC_LOAD.get((taille, cle_vp if r.vp != "V" else "V"))
            if code is None:
                inconnus.append(r.conteneur)
                continue
            op = e.exploitants.get(_norm(r.exploitant), r.exploitant)
            _ajouter(cases, "loading", code, op, r.poids_kg)
            det.append({"page": "loading", "code": code, "operateur": op, "reference": r.conteneur,
                        "poids_kg": r.poids_kg})
        ctr.append(Controle("ok", "Conteneurs chargés", f"{len(ld) - len(inconnus)} conteneurs", "ld_total"))
        if inconnus:
            ctr.append(Controle("corriger", f"{len(inconnus)} conteneur(s) de type inconnu",
                                ", ".join(inconnus[:5]), "ld_type_inconnu"))

    # --- shifting
    if e.shifting:
        sh = lire_fiche_shifting(*e.shifting)
        for r in sh.itertuples():
            ref = r.chassis or f"ligne {r.ligne}"
            L, l, H, poids = _v(r.long), _v(r.larg), _v(r.haut), _v(r.poids_t)
            vol = L * l * H if None not in (L, l, H) else None
            cl_calc = classe_volume(vol)
            classe = cl_calc or r.classe_saisie
            if cl_calc and r.classe_saisie and cl_calc != r.classe_saisie:
                ctr.append(Controle("verifier", "Classe corrigée par les dimensions",
                                    f"{ref} : {vol:.1f} m³ → {LIBELLE_CLASSE[cl_calc]}", f"sh_classe_{r.ligne}"))
            manque = [n for n, ok in (("poids", poids), ("classe", classe), ("position", r.position),
                                      ("châssis", r.chassis)) if not ok]
            if manque:
                ctr.append(Controle("corriger", f"Fiche shifting : {', '.join(manque)} manquant",
                                    ref, f"sh_manque_{r.ligne}"))
                continue
            code = CODE_SHIFT[(r.position, classe)]
            _ajouter(cases, "shifting", code, arm, poids * 1000)
            det.append({"page": "shifting", "code": code, "operateur": arm, "reference": r.chassis,
                        "poids_kg": poids * 1000, "volume_m3": vol, "classe": classe})
        dup = sh[(sh["chassis"] != "") & sh.duplicated("chassis", keep=False)]
        if len(dup):
            ctr.append(Controle("corriger", "Châssis en double (fiche shifting)",
                                ", ".join(sorted(set(dup["chassis"]))[:5]), "sh_doublons"))
        n_sh = sum(v["unites"] for (p, _, _), v in cases.items() if p == "shifting")
        if e.ts_total_shifting is not None and e.ts_total_shifting != n_sh:
            ctr.append(Controle("verifier", "Shifting différent du time sheet",
                                f"{n_sh} contre {e.ts_total_shifting}", "ts_shifting"))

    # --- tonnages
    for (p, c, _), v in cases.items():
        v["tonnes"] = round(v["kg"] / 1000, 3) if RUBRIQUES[(p, c)][1] == "T" else tonnes_sup(v["kg"])
    if e.discharging and "client" in res.clients:
        res.clients["cle"] = res.clients["client"].map(cle_client)
    res.cases, res.controles, res.detail = cases, ctr, pd.DataFrame(det)
    return res


def _taille_tc(taille_brute: str, type_iso: str) -> str | None:
    t = _norm(taille_brute)
    if t.startswith("BOL"):
        return "BOL"
    if "MAFI" in t:
        return "MAFI"
    iso = _norm(type_iso)
    if iso[2:3] == "P":
        return "PLATF"
    n = _num(taille_brute)
    if n in (20.0, 40.0):
        return str(int(n))
    if n is None and iso[:1] in ("2", "4"):
        return "20" if iso[:1] == "2" else "40"
    return None


# ---------------------------------------------------------------- en-tête
SHIFTS = ("Jour", "Nuit")


def entete(eta, accostage, debut, fin, appareillage, premier_shift, dernier_shift) -> tuple[dict, list[Controle]]:
    """premier/dernier shift : (date, 'Jour'|'Nuit'). Calcule attente et nombre de shifts."""
    ctr, out = [], {}
    if eta and accostage:
        d = accostage - eta
        if d.total_seconds() >= 0:
            m = int(d.total_seconds() // 60)
            out["attente_accostage"] = f"{m // 60}:{m % 60:02d}"
    if premier_shift and dernier_shift:
        a = premier_shift[0].toordinal() * 2 + SHIFTS.index(premier_shift[1])
        b = dernier_shift[0].toordinal() * 2 + SHIFTS.index(dernier_shift[1])
        if b >= a:
            out["shifts_engages"] = b - a + 1
        else:
            ctr.append(Controle("corriger", "Le dernier shift est avant le premier", "", "ent_shifts"))
    noms = ("ETA rade", "Accostage", "Début des opérations", "Fin des opérations", "Appareillage")
    vals = (eta, accostage, debut, fin, appareillage)
    for (n1, v1), (n2, v2) in zip(zip(noms, vals), zip(noms[1:], vals[1:])):
        if v1 and v2 and v2 < v1:
            ctr.append(Controle("corriger", f"{n2} avant {n1.lower()}", "", f"ent_{n2}"))
    for n, v in zip(noms, vals):
        if v is None:
            ctr.append(Controle("corriger", f"{n} manquant", "", f"ent_manque_{n}"))
    return out, ctr
