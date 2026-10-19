"""Note volumes mensuels — « volumes des N escales traitées sur M navires prévus ».

Fonctions pures (pandas), sans Streamlit. Règles validées par Charlie (19/10/2026) :

* seuls les navires TERMINÉS comptent dans les volumes ; l'en-tête compte les
  navires prévus du mois (terminés + en cours + attendus), hors navires à
  0 mouvement prévu (« A ORDRE », escale non confirmée) ;
* LOLO = COMBONG ; ligne ATL / MED lue dans l'armateur « GRIMALDI (ATL) » ;
* « plus de 50 m3 » = véhicules de volume unitaire STRICTEMENT > 50 m3 ;
* véhicules empilés / attelés (bébés au dos, remorques) hors total : ils n'ont
  ni poids ni volume propres (même règle que le tableau de classification) ;
* hinterland = Import vers Mali / Burkina Faso / Niger ; transbo = Place of
  Delivery hors Côte d'Ivoire (flux_rules) ;
* conteneurs : TEU = 20' x1, 40'/45' x2, MAFI x2, BOLSTER x1 ;
  TOTAL = vides + pleins ; IMPORT / EXPORT = pleins ;
* export : colonnes EXPORT/LOADING du fichier situation, vides export lus
  dans l'Observation (toujours saisis là par les agents).

Priorité des sources par escale : manifeste > fichier situation (navire
terminé) > vide (à compléter). Chaque valeur garde sa source.
"""
from __future__ import annotations

import re
from datetime import datetime

import pandas as pd

import flux_rules as fr
import situation_parser as sp

MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
           "septembre", "octobre", "novembre", "décembre"]

VEH = ["veh_total", "veh_gt50", "veh_neufs", "veh_usages", "veh_transbo", "veh_hinterland"]
TC = ["tc_vides", "tc_pleins_imp", "tc_pleins_exp", "tc_transbo"]
LABELS = {
    "veh_total": "Véhicules", "veh_gt50": "Plus de 50 m3", "veh_neufs": "Neufs", "veh_usages": "Usagés",
    "veh_transbo": "Transbo véh.", "veh_hinterland": "Hinterland",
    "tc_vides": "TEU vides", "tc_pleins_imp": "TEU pleins import", "tc_pleins_exp": "TEU pleins export",
    "tc_transbo": "TEU transbo",
}
SRC_MANIF, SRC_SIT, SRC_SAISIE = "Manifeste", "Fichier situation", "Saisie"


# ── Volumes d'un manifeste ───────────────────────────────────────────────────
def _teu(type_colis) -> int:
    t = str(type_colis or "").upper()
    if "BOLSTER" in t:
        return 1
    if "MAFI" in t:
        return 2
    m = re.search(r"\d{2}", t)
    return 1 if m and m.group(0) == "20" else 2


def volumes_grimaldi(df: pd.DataFrame) -> dict:
    """Volumes d'un manifeste Grimaldi (tableau des B/L de manifest_parser).
    Retourne les compteurs + des contrôles (véhicules sans volume, empilés)."""
    out = {k: 0 for k in VEH + TC}
    out.update({"veh_sans_volume": 0, "veh_empiles": 0, "tc_vides_imp": 0})
    if df is None or df.empty:
        return out
    d = df.copy()
    nature = d.get("Nature_BL", pd.Series([""] * len(d), index=d.index)).fillna("")
    d = d[~nature.astype(str).str.upper().str.startswith("EXP")]      # import + transbo seulement
    nb = pd.to_numeric(d["Nb_Unites"], errors="coerce").fillna(0)
    transbo = d.get("Nature_BL", pd.Series([""] * len(d), index=d.index)).fillna("").astype(str).str.startswith("Transb")
    pays = d.get("Pays_Transit", pd.Series([""] * len(d), index=d.index)).fillna("").astype(str)

    v = d["_cat_code"] == "V"
    stacked = d["Type_Colis"].fillna("").astype(str).str.startswith(("Empilée", "Attelée"))
    vv = v & ~stacked
    out["veh_empiles"] = int(nb[v & stacked].sum())
    out["veh_total"] = int(nb[vv].sum())
    out["veh_neufs"] = int(nb[vv & (d["Etat"].fillna("") == "Neuf")].sum())
    out["veh_usages"] = out["veh_total"] - out["veh_neufs"]
    vol = pd.to_numeric(d["Volume_CBM"], errors="coerce").fillna(0)
    unit = vol / nb.where(nb > 0)
    out["veh_gt50"] = int(nb[vv & (unit > 50)].sum())
    out["veh_sans_volume"] = int(nb[vv & (vol <= 0)].sum())
    out["veh_transbo"] = int(nb[vv & transbo].sum())
    out["veh_hinterland"] = int(nb[vv & ~transbo & pays.isin(fr.HINTERLAND_COUNTRIES)].sum())

    c = d["_cat_code"] == "C"
    teu = d["Type_Colis"].map(_teu) * nb
    vide = d.get("Statut_VP", pd.Series([""] * len(d), index=d.index)).fillna("").astype(str).str.upper() == "V"
    out["tc_vides"] = out["tc_vides_imp"] = int(teu[c & vide & ~transbo].sum())
    out["tc_pleins_imp"] = int(teu[c & ~vide & ~transbo].sum())
    out["tc_transbo"] = int(teu[c & transbo].sum())
    return out


def volumes_entries(entries) -> dict:
    """Volumes depuis les entrées du moteur de classification (manifestes
    chinois, MOL / NYK) : véhicules seulement, pas de conteneurs."""
    out = {k: 0 for k in VEH + TC}
    out.update({"veh_sans_volume": 0, "veh_empiles": 0, "tc_vides_imp": 0})
    for e in entries or []:
        if getattr(e, "excluded", False):
            continue
        n = int(e.nombre or 0)
        out["veh_total"] += n
        out["veh_neufs"] += n if e.is_new else 0
        if e.volume and e.volume > 0:
            if e.volume / max(n, 1) > 50:
                out["veh_gt50"] += n
        else:
            out["veh_sans_volume"] += n
        if getattr(e, "transit_pays", "") or fr.hinterland_country(e.description):
            out["veh_hinterland"] += n
        if getattr(e, "pod", "") and fr.is_transbo_place(e.pod):
            out["veh_transbo"] += n
    out["veh_usages"] = out["veh_total"] - out["veh_neufs"]
    return out


def lire_manifeste(name: str, data: bytes, progress_cb=None) -> dict:
    """Lit un manifeste quel que soit son format (Grimaldi PDF, chinois
    XLS/XLSX, MOL / NYK PDF). Retourne {escale, navire_brut, volumes,
    conteneurs (bool : le format décrit les conteneurs), format}.
    Lève ValueError si le format n'est pas reconnu ou le navire introuvable."""
    import io
    import os
    import tempfile

    import classification_vehicules as cv
    import manifest_parser as mp

    suffix = os.path.splitext(name)[1].lower() or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        fmt = cv.detect_format(path)
        if fmt == "grimaldi":
            df = mp.records_to_dataframe(mp.parse_manifest(io.BytesIO(data), name, progress_cb=progress_cb))
            if df.empty:
                raise ValueError("aucun connaissement lu dans le manifeste")
            navire = str(df["Navire"].dropna().iloc[0]) if "Navire" in df and df["Navire"].notna().any() else ""
            voyage = str(df["Voyage"].dropna().iloc[0]) if "Voyage" in df and df["Voyage"].notna().any() else ""
            vols, conteneurs = volumes_grimaldi(df), True
        elif fmt in ("chinese_roro", "mol_alis"):
            entries, meta = (cv.parse_chinese_roro(path) if fmt == "chinese_roro" else cv.parse_mol_alis(path))
            navire = re.sub(r"^.*?(?:VOYAGE|SHIP)\s*:\s*", "", str(meta.get("ship_name", "")), flags=re.I).strip()
            voyage = str(meta.get("voyage", ""))
            vols, conteneurs = volumes_entries(entries), False
        else:
            raise ValueError("format de manifeste non reconnu (attendu : Grimaldi, chinois, MOL / NYK)")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if not sp.ship_key(navire):
        raise ValueError("nom du navire introuvable dans le manifeste")
    return {"escale": sp.escale_id(navire, voyage), "navire_brut": f"{navire} {voyage}".strip(),
            "volumes": vols, "conteneurs": conteneurs, "format": fmt}


def add_volumes(a: dict | None, b: dict) -> dict:
    """Additionne deux jeux de volumes (plusieurs manifestes d'une même escale, un par POL)."""
    if not a:
        return dict(b)
    return {k: (a.get(k) or 0) + (b.get(k) or 0) for k in set(a) | set(b)
            if isinstance(a.get(k, 0), (int, float)) and isinstance(b.get(k, 0), (int, float))}


# ── Volumes tirés du fichier situation (navire terminé) ──────────────────────
def _z(v) -> float:
    return 0.0 if v is None or (isinstance(v, float) and pd.isna(v)) else float(v)


def volumes_situation(row: dict) -> dict:
    """Ce que le fichier situation donne pour un navire TERMINÉ.
    Véhicules : RR import + Observation (neufs, +50 m3, transit) ;
    conteneurs import : 20'/40'/MAFI/BOLSTER moins les vides de l'Observation ;
    export : 20'/40'/MAFI pleins/BOLSTER pleins moins les vides export."""
    r = row or {}
    out = {}
    if r.get("imp_rr") is not None and not pd.isna(r.get("imp_rr")):
        out["veh_total"] = int(_z(r["imp_rr"]))
    for k_obs, k in (("obs_neufs", "veh_neufs"), ("obs_gt50", "veh_gt50"), ("obs_transit", "veh_hinterland")):
        if r.get(k_obs) is not None and not pd.isna(r.get(k_obs)):
            out[k] = int(r[k_obs])
    if "veh_total" in out and "veh_neufs" in out:
        out["veh_usages"] = out["veh_total"] - out["veh_neufs"]
    # Ligne d'un navire TERMINÉ (section VESSELS COMPLETED = réalisé) : une
    # case vide y vaut 0. Les vides sont lus dans l'Observation.
    vi20, vi40 = _z(r.get("obs_vides_imp_20")), _z(r.get("obs_vides_imp_40"))
    ve20, ve40 = _z(r.get("obs_vides_exp_20")), _z(r.get("obs_vides_exp_40"))
    out["tc_pleins_imp"] = int(max(_z(r.get("imp_20")) - vi20, 0) + 2 * max(_z(r.get("imp_40")) - vi40, 0)
                               + 2 * _z(r.get("imp_mafi")) + _z(r.get("imp_bolst_full")))
    out["tc_pleins_exp"] = int(max(_z(r.get("exp_20")) - ve20, 0) + 2 * max(_z(r.get("exp_40")) - ve40, 0)
                               + 2 * _z(r.get("exp_mafi_full")) + _z(r.get("exp_bolst_full")))
    out["tc_vides_imp"] = int(vi20 + 2 * vi40)
    out["tc_vides_exp"] = int(ve20 + 2 * ve40)
    out["tc_transbo"] = 0          # pas de colonne transbo : à corriger à la main si besoin
    out.setdefault("veh_transbo", 0)
    return out


# ── Escales du mois ──────────────────────────────────────────────────────────
def _in_month(d, annee: int, mois: int) -> bool:
    return d is not None and not pd.isna(d) and pd.Timestamp(d).year == annee and pd.Timestamp(d).month == mois


def escales_du_mois(situation: dict, annee: int, mois: int) -> pd.DataFrame:
    """Navires du mois : terminés (onglet CUMUL du mois, hors navires encore
    en opération) + en cours + attendus avec ETA dans le mois.
    Colonnes : escale, navire, voyage, navire_brut, type, ligne, date, statut,
    total_moves, compte_entete (bool), compte_volumes (bool)."""
    nav = situation.get("navires") if situation else None
    nav = nav if nav is not None else pd.DataFrame()
    cum = (situation or {}).get("cumul", {}).get(mois, pd.DataFrame())
    by = {r["escale"]: r for r in nav.to_dict("records")} if not nav.empty else {}
    rows, seen = [], set()
    for r in cum.to_dict("records") if not cum.empty else []:
        s = by.get(r["escale"], {})
        statut = "En cours" if s.get("statut") == "En cours" else "Terminé"
        rows.append({"escale": r["escale"], "navire": r["navire"], "voyage": r["voyage"],
                     "navire_brut": r["navire_brut"], "type": r["type"] or s.get("type", ""),
                     "ligne": r["ligne"] or s.get("ligne", ""), "date": r.get("accostage") or r.get("debut"),
                     "statut": statut, "total_moves": s.get("total_moves")})
        seen.add(r["escale"])
    for s in by.values():
        if s["escale"] in seen or s["statut"] == "Terminé" and not _in_month(s.get("debut"), annee, mois):
            continue
        if s["statut"] in ("En cours", "Prévu", "Terminé") and _in_month(s.get("debut"), annee, mois):
            rows.append({"escale": s["escale"], "navire": s["navire"], "voyage": s["voyage"],
                         "navire_brut": s["navire_brut"], "type": s["type"], "ligne": s["ligne"],
                         "date": s.get("debut"), "statut": s["statut"], "total_moves": s.get("total_moves")})
            seen.add(s["escale"])
    df = pd.DataFrame(rows, columns=["escale", "navire", "voyage", "navire_brut", "type", "ligne",
                                     "date", "statut", "total_moves"])
    if df.empty:
        return df.assign(compte_entete=pd.Series(dtype=bool), compte_volumes=pd.Series(dtype=bool))
    moves = pd.to_numeric(df["total_moves"], errors="coerce")
    df["compte_entete"] = (df["statut"] == "Terminé") | ~(moves.fillna(-1) == 0)
    df["compte_volumes"] = df["statut"] == "Terminé"
    order = {"Terminé": 0, "En cours": 1, "Prévu": 2}
    return df.sort_values(["statut", "date"], key=lambda s: s.map(order) if s.name == "statut" else s) \
             .reset_index(drop=True)


def match_manifeste(escale: str, manifestes: dict) -> str | None:
    """Clé du manifeste mémorisé correspondant à l'escale (navire + voyage ;
    navire seul si un seul manifeste porte ce nom)."""
    if escale in manifestes:
        return escale
    nav, voy = escale.split("|", 1)
    cands = [k for k in manifestes if k.split("|", 1)[0] == nav]
    exact = [k for k in cands if voy and k.split("|", 1)[1] and (k.split("|", 1)[1] in voy or voy in k.split("|", 1)[1])]
    if len(exact) == 1:
        return exact[0]
    return cands[0] if len(cands) == 1 and not voy else None


def volumes_escale(escale: str, manifestes: dict, situations: dict) -> tuple[dict, dict]:
    """(valeurs, sources) d'une escale terminée selon la priorité
    manifeste > fichier situation. Les vides export et l'export plein ne
    viennent que du fichier situation."""
    vals, srcs = {}, {}
    mk = match_manifeste(escale, manifestes)
    man = manifestes.get(mk, {}).get("volumes") if mk else None
    sit_row = situations.get(escale)
    sit = volumes_situation(sit_row) if sit_row and sit_row.get("statut") == "Terminé" else {}
    for k in VEH + ["tc_pleins_imp", "tc_transbo"]:
        if man is not None and (k.startswith("veh") or manifestes[mk].get("conteneurs")):
            vals[k], srcs[k] = man.get(k, 0), SRC_MANIF
        elif k in sit:
            vals[k], srcs[k] = sit[k], SRC_SIT
    vid_imp = (man.get("tc_vides_imp"), SRC_MANIF) if man is not None and manifestes[mk].get("conteneurs") \
        else ((sit["tc_vides_imp"], SRC_SIT) if "tc_vides_imp" in sit else (None, None))
    vid_exp = (sit["tc_vides_exp"], SRC_SIT) if "tc_vides_exp" in sit else (None, None)
    if vid_imp[0] is not None or vid_exp[0] is not None:
        vals["tc_vides"] = int((vid_imp[0] or 0) + (vid_exp[0] or 0))
        srcs["tc_vides"] = " + ".join(dict.fromkeys(s for s in (vid_imp[1], vid_exp[1]) if s))
    if "tc_pleins_exp" in sit:
        vals["tc_pleins_exp"], srcs["tc_pleins_exp"] = sit["tc_pleins_exp"], SRC_SIT
    return vals, srcs


def controles(escale: str, manifestes: dict, situations: dict) -> list[str]:
    """Écarts manifeste / Observation de l'agent (le manifeste prime ; un
    écart est probablement une erreur de saisie à signaler)."""
    mk = match_manifeste(escale, manifestes)
    man = manifestes.get(mk, {}).get("volumes") if mk else None
    row = situations.get(escale) or {}
    out = []
    if man:
        for k_obs, k, lib in (("obs_neufs", "veh_neufs", "neufs"), ("obs_gt50", "veh_gt50", "plus de 50 m3"),
                              ("obs_transit", "veh_hinterland", "en transit / hinterland")):
            o = row.get(k_obs)
            if o is not None and not pd.isna(o) and int(o) != int(man.get(k, 0)):
                out.append(f"{lib} : {int(man.get(k, 0))} au manifeste, {int(o)} dans l'Observation "
                           f"(écart {abs(int(o) - int(man.get(k, 0)))})")
        if man.get("veh_sans_volume"):
            out.append(f"{man['veh_sans_volume']} véhicule(s) sans volume au manifeste : comptés dans le total, "
                       "pas dans « plus de 50 m3 »")
        if man.get("veh_empiles"):
            out.append(f"{man['veh_empiles']} véhicule(s) empilé(s) / attelé(s) hors total")
    return out


# ── Texte de la note ─────────────────────────────────────────────────────────
def _n2(v) -> str:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return "[À COMPLÉTER]"
    return f"{n:02d}"


def _plural(n: int, t: str) -> str:
    return t if n <= 1 or t.endswith("S") else t + "S"


def entete_types(esc: pd.DataFrame) -> str:
    """« 01 CARCAR,03 LOLOS et 05 CONROS (02 ATL, 03 MED) »."""
    e = esc[esc["compte_entete"]] if not esc.empty else esc
    order = ["CARCAR", "LOLO", "CONRO"]
    types = list(dict.fromkeys(order + sorted(set(e["type"].fillna("")) - set(order) - {""})))
    parts = []
    for t in types:
        n = int((e["type"] == t).sum())
        if not n:
            continue
        p = f"{n:02d} {_plural(n, t)}"
        if t == "CONRO":
            lig = [f"{int((e[(e['type'] == t)]['ligne'] == l).sum()):02d} {l}" for l in ("ATL", "MED")
                   if (e[(e["type"] == t)]["ligne"] == l).any()]
            if lig:
                p += f" ({', '.join(lig)})"
        parts.append(p)
    if not parts:
        return ""
    return parts[0] if len(parts) == 1 else ",".join(parts[:-1]) + " et " + parts[-1]


def build_note(esc: pd.DataFrame, totaux: dict, annee: int, mois: int) -> str:
    """Texte de la note, au format exact de la note manuelle. Une valeur
    absente s'écrit « [À COMPLÉTER] » (jamais inventée)."""
    n_vol = int(esc["compte_volumes"].sum()) if not esc.empty else 0
    n_ent = int(esc["compte_entete"].sum()) if not esc.empty else 0
    t = totaux
    tc_pleins = None if t.get("tc_pleins_imp") is None or t.get("tc_pleins_exp") is None \
        else t["tc_pleins_imp"] + t["tc_pleins_exp"]
    tc_total = None if tc_pleins is None or t.get("tc_vides") is None else tc_pleins + t["tc_vides"]
    mois_txt = MOIS_FR[mois - 1].capitalize()
    return "\n".join([
        f"Prière trouver ci-dessous les volumes des {n_vol:02d} escales traitées sur {n_ent:02d} navires "
        f"<< {entete_types(esc)} >>",
        f"prévus pour le mois de {mois_txt} {annee} :",
        "VEHICULES :",
        f"TOTAL :{_n2(t.get('veh_total'))}",
        f"DONT PLUS DE 50 M3 : {_n2(t.get('veh_gt50'))}",
        f"DONT NEUFS :  {_n2(t.get('veh_neufs'))}",
        f"DONT USAGÉS :{_n2(t.get('veh_usages'))}",
        f"DONT TRANSBO : {_n2(t.get('veh_transbo'))} ",
        f"DONT HINTERLAND :{_n2(t.get('veh_hinterland'))}",
        " ",
        "CONTENEURS :",
        f"TOTAL TEUS : {_n2(tc_total)} ",
        f"DONT VIDES : {_n2(t.get('tc_vides'))}   ",
        f"DONT PLEINS : {_n2(tc_pleins)}",
        f"DONT IMPORT :{_n2(t.get('tc_pleins_imp'))}",
        f"DONT EXPORT : {_n2(t.get('tc_pleins_exp'))}",
        f"DONT TRANSBO : {_n2(t.get('tc_transbo'))} ",
    ])


def totaux(detail: pd.DataFrame) -> dict:
    """Somme des escales comptées ; None pour un indicateur dont au moins une
    escale comptée n'a pas de valeur (la note l'affiche à compléter)."""
    out = {}
    d = detail[detail["compte_volumes"]] if not detail.empty else detail
    for k in VEH + TC:
        if d.empty or k not in d:
            out[k] = None if not d.empty else 0
            continue
        col = pd.to_numeric(d[k], errors="coerce")
        out[k] = None if col.isna().any() else int(col.sum())
    return out


def date_label(d) -> str:
    return pd.Timestamp(d).strftime("%d/%m") if d is not None and not pd.isna(d) else ""


def now_month() -> tuple[int, int]:
    t = datetime.now()
    return t.year, t.month
