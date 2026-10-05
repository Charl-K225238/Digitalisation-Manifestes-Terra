"""
Parseur du Loading Report (Etat Définitif) Grimaldi — format Excel .xls/.xlsx.

Génère deux fichiers de sortie conformes au format exact attendu par le
logiciel interne Terra :
  - MASQUE TCS EXPORT  : CSV semicolon, 16 colonnes, une ligne / conteneur
  - TYPE ISO           : CSV semicolon, 3 colonnes + trailing semicolon, une ligne / conteneur

Le format de chacun est strict (colonnes, séparateurs, ordre) car ils sont
importés automatiquement dans un logiciel tiers sans transformation.
"""
from __future__ import annotations

import io
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import pandas as pd

# ---------------------------------------------------------------------------
# Mapping LOCODE → nom de ville (EXPORT : POL toujours Abidjan)
# ---------------------------------------------------------------------------
LOCODE_CITY: dict[str, str] = {
    # Côte d'Ivoire
    "CIABJ": "ABIDJAN",
    "CIABJ01": "ABIDJAN",
    # France
    "FRMRS": "MARSEILLE",
    "FRLEH": "LE HAVRE",
    "FRFOS": "FOS-SUR-MER",
    "FRBOD": "BORDEAUX",
    # Pays-Bas
    "NLAMS": "AMSTERDAM",
    "NLRTM": "ROTTERDAM",
    "NLMSV": "AMSTERDAM",
    # Belgique
    "BEANR": "ANVERS",
    "BEANT": "ANVERS",
    # Allemagne
    "DEHAM": "HAMBOURG",
    "DEBRE": "BRÈME",
    # Espagne
    "ESVLC": "VALENCE",
    "ESBCN": "BARCELONE",
    "ESCAD": "CADIX",
    # Italie
    "ITGOA": "GÊNES",
    "ITSAL": "SALERNE",
    "ITGIT": "GIOIA TAURO",
    "ITNAP": "NAPLES",
    "ITLIV": "LIVOURNE",
    # Royaume-Uni
    "GBTIL": "TILBURY",
    "GBLGP": "LONDON GATEWAY",
    "GBSOU": "SOUTHAMPTON",
    # Sénégal
    "SNDKR": "DAKAR",
    # Ghana
    "GHTEM": "TEMA",
    "GHTKD": "TEMA",
    # Togo
    "TGLFW": "LOMÉ",
    # Bénin
    "BJCOO": "COTONOU",
    # Nigeria
    "NGLAG": "LAGOS",
    "NGTIN": "TINCAN",
    # Cameroun
    "CMDLA": "DOUALA",
    # Gabon
    "GALBV": "LIBREVILLE",
    # Congo
    "CGPNR": "POINTE-NOIRE",
    "CDDIL": "MATADI",
    # Angola
    "AOLAD": "LUANDA",
    "AOLOB": "LOBITO",
    # Maroc
    "MACAS": "CASABLANCA",
    "MAAGA": "AGADIR",
    # Tunisie
    "TNTUN": "TUNIS",
    "TNBIZ": "BIZERTE",
    # Égypte
    "EGPSD": "PORT SAÏD",
    "EGALX": "ALEXANDRIE",
    # Turquie
    "TRIST": "ISTANBUL",
    "TRMER": "MERSIN",
}

# ---------------------------------------------------------------------------
# Mapping code ISO (4 chars) → libellé TYPE CONTENEUR
# ---------------------------------------------------------------------------
ISO_TYPE_LABEL: dict[str, str] = {
    # 20 pieds
    "22G0": "20'DRY",
    "22G1": "20'DRY",
    "22R0": "20'RF",
    "22R1": "20'RF",
    "22U0": "20'OT",
    "22U1": "20'OT",
    "22P0": "20'FR",
    "22P1": "20'FR",
    "22B0": "20'BK",
    "22B1": "20'BK",
    "22H0": "20'HC",
    "22H1": "20'HC",
    "22T0": "20'TK",
    "22T1": "20'TK",
    # 40 pieds standard
    "42G0": "40'DRY",
    "42G1": "40'DRY",
    "42R0": "40'RF",
    "42R1": "40'RF",
    "42U0": "40'OT",
    "42U1": "40'OT",
    "42P0": "40'FR",
    "42P1": "40'FR",
    "42H0": "40'HC",
    "42H1": "40'HC",
    "42T0": "40'TK",
    "42T1": "40'TK",
    # 40 pieds High Cube
    "45G0": "40'HC",
    "45G1": "40'HC",
    "45R0": "40'HC RF",
    "45R1": "40'HC RF",
    "45U0": "40'HC OT",
    "45U1": "40'HC OT",
    # 45 pieds High Cube
    "L5G0": "45'HC",
    "L5G1": "45'HC",
    # MAFI / flat bed
    "9900": "40' MAFI",
    "99": "40' MAFI",
    # Divers
    "22VG": "20'DRY",
    "42VG": "40'DRY",
}
_ISO_DEFAULT = "CONTENEUR"


def _locode_to_city(code: str) -> tuple[str, bool]:
    """Résout un LOCODE en nom de ville. Retourne (valeur, résolu) — si le
    code est inconnu, la valeur brute est retournée telle quelle (visible
    dans l'aperçu éditable pour que l'agent puisse corriger) et résolu=False,
    pour permettre au niveau appelant de signaler précisément les lignes à
    vérifier SANS deviner (une regex sur la forme du texte donnerait de
    faux positifs : une ville décodée comme 'DAKAR' ou le libellé 'OPTION'
    ont la même forme qu'un code LOCODE non résolu).

    Cas spécial confirmé sur données réelles : un code se terminant par
    "OPT" (ex. 'FROPT') n'est pas un vrai LOCODE mais un placeholder
    "port optionnel / à définir" -> converti en 'OPTION' (valeur littérale
    utilisée par le logiciel interne, cf. fichier MASQUE de référence)."""
    if not code or not isinstance(code, str):
        return code or "", True
    c = code.strip().upper()
    if c.endswith("OPT"):
        return "OPTION", True
    if c in LOCODE_CITY:
        return LOCODE_CITY[c], True
    return c, False


def _iso_size_code(iso_numeric) -> str:
    """Convertit la taille ISO numérique (20.0 / 40.0 / 45.0) en code 1/2/2.
    20 → '1', tout le reste (40, 45) → '2'."""
    try:
        n = float(iso_numeric)
        return "1" if n < 25 else "2"
    except (TypeError, ValueError):
        return ""


def _iso_type_label(iso_code: str) -> str:
    """Libellé lisible depuis le code ISO 4 caractères (ex. 22G1 → 20'DRY)."""
    if not iso_code or not isinstance(iso_code, str):
        return _ISO_DEFAULT
    return ISO_TYPE_LABEL.get(iso_code.strip().upper(), _ISO_DEFAULT)


def _extract_voyage_code(navire: str, voyage_raw: str) -> str:
    """Extrait le code voyage à partir de la colonne 'Voyage' brute.

    Découverte sur données réelles (LOADING_REPORT_GRANDE_ANGOLA...xls) :
    cette colonne ne contient PAS que le code voyage mais le nom du navire
    concaténé au code (ex. 'GRANDE ANGOLA GRA0825NB' pour le navire
    'GRANDE ANGOLA '), alors que le fichier MASQUE cible attend uniquement
    'GRA0825NB' dans la colonne N° VOY. On retire donc le préfixe navire
    (insensible à la casse/espaces) ; à défaut de correspondance, on prend
    le dernier token contenant un chiffre (forme typique d'un code voyage)."""
    if not voyage_raw:
        return ""
    v = str(voyage_raw).strip()
    if navire:
        n = str(navire).strip()
        if n and v.upper().startswith(n.upper()):
            v = v[len(n):].strip()
    if " " in v:
        tokens = v.split()
        code_tokens = [t for t in tokens if re.search(r'\d', t)]
        if code_tokens:
            v = code_tokens[-1]
    return v


def _format_date(val) -> str:
    """Convertit une valeur date/datetime/float Excel en 'DD/MM/YYYY'."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    if isinstance(val, (datetime, date)):
        return val.strftime("%d/%m/%Y")
    if isinstance(val, str):
        # Tenter les formats courants
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(val.strip(), fmt).strftime("%d/%m/%Y")
            except ValueError:
                pass
        return val.strip()
    # Serial Excel (float) — pandas gère via xlrd/openpyxl donc ce cas est rare
    try:
        return pd.Timestamp(val).strftime("%d/%m/%Y")
    except Exception:
        return str(val)


# ---------------------------------------------------------------------------
# Noms de colonnes attendus dans le Loading Report (recherche insensible à la
# casse, avec variantes pour couvrir les évolutions de format).
# ---------------------------------------------------------------------------
_COL_ALIASES: dict[str, list[str]] = {
    "navire":     ["navire", "vessel", "nom navire", "ship"],
    "voyage":     ["voyage", "n° voy", "no voy", "n voy", "voy"],
    "date":       ["date", "date d'arrivée", "date arrivée", "eta", "arrivée"],
    "conteneur":  ["conteneur", "n° conteneur", "container", "ctr", "ctnr"],
    "iso_num":    ["iso", "20/40", "20'/40'", "size", "taille"],
    "iso_code":   ["type", "type iso", "iso type", "type conteneur"],
    "poids":      ["poids", "weight", "poids(kgs)", "poids (kg)", "brut"],
    # N° BOOKING = numéro de B/L dans le Loading Report Grimaldi.
    # "ARMT B/L" désigne l'armateur (souvent "GRIMALDI"), PAS le numéro BL.
    "booking":    ["n° booking", "no booking", "n°booking", "booking n°",
                   "booking no", "booking", "n° book", "n°book",
                   "réservation", "reservation"],
    "armt_bl":    ["armt b/l", "armt bl", "armateur b/l", "armateur bl",
                   "n° bl", "bl", "b/l", "bol"],
    "vp":         ["v/p", "vide/plein", "vp"],
    "pol":        ["pol", "port charg", "port of loading", "chargement"],
    "pod":        ["pod", "port dech", "port of discharge", "déchargement"],
    "dest":       ["dest", "destination", "dest. fin", "destination finale"],
    "client":     ["client", "libellé client", "exportateur", "shipper"],
    "mouvt":      ["mouvt", "mouvement", "move", "mvt"],
}


def _find_col(df: pd.DataFrame, key: str) -> Optional[str]:
    """Retourne le nom de colonne du DataFrame correspondant à la clé logique."""
    aliases = _COL_ALIASES.get(key, [key])
    for col in df.columns:
        col_lower = str(col).lower().strip()
        for alias in aliases:
            if alias in col_lower:
                return col
    return None


def _detect_header_row(raw: pd.DataFrame, max_rows: int = 10) -> int:
    """Identifie la ligne-en-tête du Loading Report parmi les premières lignes.
    Cherche la ligne qui contient le plus de noms de colonnes reconnus."""
    all_aliases = [alias for aliases in _COL_ALIASES.values() for alias in aliases]
    best_row, best_score = 0, 0
    for i in range(min(max_rows, len(raw))):
        row_vals = " ".join(str(v).lower() for v in raw.iloc[i] if pd.notna(v))
        score = sum(1 for alias in all_aliases if alias in row_vals)
        if score > best_score:
            best_score, best_row = score, i
    return best_row


# ---------------------------------------------------------------------------
# Lecture et parsing du fichier Loading Report
# ---------------------------------------------------------------------------

def parse_loading_report(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """Lit un fichier Loading Report (.xls ou .xlsx) et retourne un DataFrame
    normalisé avec des colonnes canoniques.

    Columns du DataFrame retourné :
        navire, voyage, date_arrivee (str DD/MM/YYYY),
        n_conteneur, iso_num (str), iso_code (str),
        poids_kgs (float), n_bl (str), vp (str),
        pol (str), pod (str), destination (str), client (str)
    """
    fname = filename.lower()
    try:
        if fname.endswith(".xlsx"):
            raw = pd.read_excel(io.BytesIO(file_bytes), header=None, engine="openpyxl")
        else:
            raw = pd.read_excel(io.BytesIO(file_bytes), header=None, engine="xlrd")
    except Exception as e:
        raise ValueError(f"Impossible de lire le fichier '{filename}' : {e}") from e

    if raw.empty:
        raise ValueError(f"Le fichier '{filename}' semble vide.")

    # Détection automatique de la ligne d'en-tête
    header_row = _detect_header_row(raw)
    headers = [str(v).strip() if pd.notna(v) else f"_col{i}"
               for i, v in enumerate(raw.iloc[header_row])]
    df = raw.iloc[header_row + 1:].copy()
    df.columns = headers
    df = df.reset_index(drop=True)

    # Supprime les lignes entièrement vides
    df = df.dropna(how="all").reset_index(drop=True)
    # Supprime les lignes qui sont des sous-totaux / totaux (heuristique)
    if _find_col(df, "conteneur"):
        ctn_col = _find_col(df, "conteneur")
        df = df[df[ctn_col].notna() & (df[ctn_col].astype(str).str.strip() != "")].reset_index(drop=True)

    if df.empty:
        raise ValueError(f"Aucune donnée valide trouvée dans '{filename}'.")

    def _get(key: str) -> pd.Series:
        col = _find_col(df, key)
        if col:
            return df[col].fillna("").astype(str).str.strip()
        return pd.Series([""] * len(df), index=df.index)

    def _get_num(key: str) -> pd.Series:
        col = _find_col(df, key)
        if col:
            return pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        return pd.Series([0.0] * len(df), index=df.index)

    # Navire : PAS d'espaces retirés — le logiciel cible utilise le nom du
    # navire tel qu'exporté par le Loading Report comme clé exacte, espace
    # de fin inclus le cas échéant (confirmé sur fichier MASQUE de référence :
    # "GRANDE ANGOLA ;GRA0825NB", espace conservé avant le point-virgule).
    navire_col = _find_col(df, "navire")
    if navire_col:
        navires = df[navire_col].apply(lambda v: "" if pd.isna(v) else str(v))
    else:
        navires = pd.Series([""] * len(df), index=df.index)

    # Voyage brut (avant extraction du code) — la colonne contient parfois
    # "NAVIRE + CODE VOYAGE" concaténés, voir _extract_voyage_code().
    voyage_col = _find_col(df, "voyage")
    voyages_raw = _get("voyage") if voyage_col else pd.Series([""] * len(df), index=df.index)
    voyages = pd.Series(
        [_extract_voyage_code(nav, voy) for nav, voy in zip(navires, voyages_raw)],
        index=df.index,
    )
    dates_raw_col = _find_col(df, "date")

    # Date d'arrivée : valeur brute → formatée DD/MM/YYYY
    if dates_raw_col:
        dates_formatted = df[dates_raw_col].apply(_format_date)
    else:
        dates_formatted = pd.Series([""] * len(df), index=df.index)

    # N° BL : priorité à la colonne "N° BOOKING" (numéro de réservation/BL).
    # La colonne "ARMT B/L" désigne l'armateur (souvent "GRIMALDI"), pas le
    # numéro BL — elle sert de fallback uniquement si aucune colonne booking
    # n'est détectée (et "GRIMALDI" / vide → "AUCUN").
    booking_raw = _get("booking")
    armt_bl_raw = _get("armt_bl")

    _ignore_vals = {"", "nan", "n/a", "-", "—"}

    def _resolve_nbl(booking: str, armt_bl: str) -> str:
        if booking and booking.lower() not in _ignore_vals:
            return booking
        # Fallback armt_bl : armateur connu → AUCUN ; autre valeur → numéro BL
        if not armt_bl or armt_bl.upper() in ("GRIMALDI", "GRIMALDI LINES", ""):
            return "AUCUN"
        return armt_bl

    n_bl = pd.Series(
        [_resolve_nbl(b, a) for b, a in zip(booking_raw, armt_bl_raw)],
        index=df.index,
    )

    # ISO code (22G1, etc.) — peut être numérique dans le fichier
    iso_code_col = _find_col(df, "iso_code")
    if iso_code_col:
        iso_codes = df[iso_code_col].apply(
            lambda v: str(v).strip() if pd.notna(v) and str(v).strip() not in ("", "nan") else ""
        )
    else:
        iso_codes = pd.Series([""] * len(df), index=df.index)

    # Taille ISO numérique (20 / 40) — normalement une valeur numérique, mais
    # le Loading Report réel contient aussi des valeurs texte ("MAFI") pour
    # les remorques plateau (Type = '9900'/'99') : dans ce cas on déduit la
    # taille depuis le code Type plutôt que de planter sur la conversion.
    def _infer_size_from_code(code: str) -> str:
        c = (code or "").strip().upper()
        if c.startswith("9"):       # 9900/99 -> remorque MAFI 40'
            return "40"
        if c.startswith("2"):       # 22Gx, 22Rx... -> 20'
            return "20"
        if c.startswith(("4", "L")):  # 42Gx, 45Gx, L5Gx... -> 40'
            return "40"
        return ""

    iso_num_col = _find_col(df, "iso_num")
    if iso_num_col:
        iso_nums = pd.Series(
            [
                str(int(float(v))) if pd.notna(v) and str(v).strip().replace(".", "", 1).lstrip("-").isdigit()
                else _infer_size_from_code(code)
                for v, code in zip(df[iso_num_col], iso_codes)
            ],
            index=df.index,
        )
    else:
        iso_nums = iso_codes.apply(_infer_size_from_code)

    # Poids
    poids = _get_num("poids")

    # V/P
    vp = _get("vp").str.upper().str[:1]  # 'V' ou 'P'

    # POL / POD / Destination — chaque décodage retourne (valeur, résolu) ;
    # le flag "résolu" alimente une colonne dédiée pour signaler sans
    # ambiguïté (ni faux positif, ni faux négatif) les lignes à vérifier.
    pol_pairs = _get("pol").apply(_locode_to_city)
    pod_pairs = _get("pod").apply(_locode_to_city)
    # Destination finale : également un LOCODE dans le Loading Report réel
    # (ex. 'FRMRS' répété, ou 'FROPT' -> 'OPTION') — confirmé identique au
    # traitement POD, pas un libellé déjà en clair.
    dest_pairs = _get("dest").apply(_locode_to_city)

    pol = pol_pairs.apply(lambda t: t[0])
    pod = pod_pairs.apply(lambda t: t[0])
    dest = dest_pairs.apply(lambda t: t[0])
    pod_resolved = pod_pairs.apply(lambda t: t[1])
    dest_resolved = dest_pairs.apply(lambda t: t[1])

    # Client
    client = _get("client")

    result = pd.DataFrame({
        "navire":        navires,
        "voyage":        voyages,
        "date_arrivee":  dates_formatted,
        "n_conteneur":   _get("conteneur"),
        "iso_num":       iso_nums,
        "iso_code":      iso_codes,
        "poids_kgs":     poids,
        "n_bl":          n_bl,
        "vp":            vp,
        "pol":           pol,
        "pod":           pod,
        "destination":   dest,
        "pod_resolved":       pod_resolved,
        "destination_resolved": dest_resolved,
        "client":        client,
    })

    # Remplissage en avant pour navire/voyage/date (souvent renseignés
    # uniquement sur la première ligne de chaque groupe, vides ensuite)
    for col in ("navire", "voyage", "date_arrivee", "pol"):
        result[col] = result[col].replace("", pd.NA).ffill().fillna("")

    return result


# ---------------------------------------------------------------------------
# Génération du MASQUE TCS EXPORT CSV
# ---------------------------------------------------------------------------

def generate_masque_tcs(
    df: pd.DataFrame,
    compte_escale: str,
    armateur: str = "GRIMALDI ",
) -> str:
    """Génère le contenu CSV du MASQUE TCS EXPORT depuis le DataFrame normalisé.

    Format : semicolon, pas de guillemets, en-tête sur la 1ère ligne.
    Colonnes : COMPTE D'ESCALE;NAVIRE;N° VOY;ARMATEUR;DATE D'ARRIVEE;N° BL;
               MARCHANDISE;N° CONTENEUR;P/V;EXPORT;PORT DE CHARGEMENT;
               PORT DE DECHARGEMENT;DESTINATION FINALE;NOM CLIENT EXPORTATEUR;
               20'/40';POIDS(KGS)
    """
    lines = [
        "COMPTE D'ESCALE;NAVIRE;N° VOY;ARMATEUR;DATE D'ARRIVEE;"
        "N° BL;MARCHANDISE;N° CONTENEUR;P/V;EXPORT;"
        "PORT DE CHARGEMENT;PORT DE DECHARGEMENT;DESTINATION FINALE;"
        "NOM CLIENT EXPORTATEUR;20'/40';POIDS(KGS)"
    ]
    for _, row in df.iterrows():
        # Taille ISO → code 1 (20') ou 2 (40')
        size_code = _iso_size_code(row["iso_num"]) if row["iso_num"] else ""
        poids_str = str(int(row["poids_kgs"])) if row["poids_kgs"] else "0"
        parts = [
            compte_escale,
            row["navire"],
            row["voyage"],
            armateur,
            row["date_arrivee"],
            row["n_bl"],
            "CONTENEUR",
            row["n_conteneur"],
            row["vp"],
            "E",
            row["pol"] or "ABIDJAN",
            row["pod"],
            row["destination"],
            row["client"],
            size_code,
            poids_str,
        ]
        lines.append(";".join(str(p) for p in parts))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Génération du TYPE ISO CSV
# ---------------------------------------------------------------------------

def generate_type_iso(df: pd.DataFrame) -> str:
    """Génère le contenu CSV TYPE ISO depuis le DataFrame normalisé.

    Format : semicolon + trailing semicolon sur chaque ligne de données,
    en-tête sans trailing semicolon.
    Colonnes : N° CONTENEUR;ISO;TYPE CONTENEUR;
    """
    lines = ["N° CONTENEUR;ISO;TYPE CONTENEUR;"]
    for _, row in df.iterrows():
        iso = row["iso_code"] or ""
        label = _iso_type_label(iso)
        lines.append(f"{row['n_conteneur']};{iso};{label};")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Point d'entrée unique : liste les voyages disponibles dans un fichier
# ---------------------------------------------------------------------------

def list_voyages(df: pd.DataFrame) -> list[dict]:
    """Retourne la liste des voyages distincts trouvés, avec métadonnées.

    Inclut '_source_file' dans la clé de groupement si la colonne est
    présente — permet de distinguer deux fichiers chargés simultanément
    même s'ils décrivent le même navire/voyage.
    """
    group_cols = ["navire", "voyage"]
    if "_source_file" in df.columns:
        group_cols = ["navire", "voyage", "_source_file"]

    groups = (
        df.groupby(group_cols, sort=False)
        .agg(
            date_arrivee=("date_arrivee", "first"),
            nb_conteneurs=("n_conteneur", "count"),
            nb_bl_distincts=("n_bl", lambda s: s[s != "AUCUN"].nunique()),
        )
        .reset_index()
    )
    if "_source_file" not in groups.columns:
        groups["_source_file"] = ""
    return groups.to_dict("records")


# ---------------------------------------------------------------------------
# Encodage fichier — le logiciel interne attend du Windows-1252 (ANSI) avec
# fins de ligne CRLF, PAS de l'UTF-8/LF (vérifié en comparant octet à octet
# les fichiers MASQUE/TYPE ISO de référence fournis par l'utilisateur :
# le caractère 'N°' y est encodé 0xB0, invalide en UTF-8, valide en cp1252).
# Utiliser de l'UTF-8 ici corromprait tous les caractères accentués/° à
# l'import dans le logiciel cible.
# ---------------------------------------------------------------------------

def to_windows_csv_bytes(text: str) -> tuple[bytes, list[str]]:
    """Convertit un texte CSV (lignes séparées par \\n) en bytes cp1252/CRLF,
    tels qu'attendus par le logiciel interne. Retourne (bytes, avertissements) :
    la liste d'avertissements signale les caractères non représentables en
    cp1252 qui ont dû être remplacés par '?' (pour ne jamais échouer
    silencieusement — l'agent doit être informé si des données ont été
    altérées à l'export)."""
    warnings: list[str] = []
    normalized = text.replace("\r\n", "\n").replace("\n", "\r\n")
    try:
        encoded = normalized.encode("cp1252")
    except UnicodeEncodeError:
        # Repère les caractères problématiques ligne par ligne pour un
        # message utile, puis encode avec remplacement pour ne jamais planter.
        for i, line in enumerate(normalized.split("\r\n"), start=1):
            try:
                line.encode("cp1252")
            except UnicodeEncodeError as le:
                bad_char = line[le.start:le.end]
                warnings.append(f"Ligne {i} : caractère non supporté « {bad_char} » remplacé par '?'.")
        encoded = normalized.encode("cp1252", errors="replace")
    return encoded, warnings
