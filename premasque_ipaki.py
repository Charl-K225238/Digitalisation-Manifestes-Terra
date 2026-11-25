"""
premasque_ipaki.py — Pré-masque véhicules au format exact des agents (import Ipaki)
et fichier de vérification qui l'accompagne.

Deux fichiers, jamais mélangés :
  - pré-masque Ipaki : UN onglet « MASQUE IPAKI TETRAX », en-tête en ligne 1, les
    26 colonnes du masque agent (mêmes libellés, espaces compris), valeurs seules
    (ni formule, ni couleur, ni commentaire, ni lien) : rien qui puisse gêner l'import ;
  - vérification : onglets « À VÉRIFIER » (points + totaux), « Masque annoté »
    (même contenu, couleurs + commentaires + liens), « GUIDE » ; ajoutés au classeur
    d'export habituel (qui garde « Détail Cargaison », relu par le Reporting).

Règles reprises du masque agent (navire GSL0526 Anvers, 320 unités, cohérentes à 100 %) :
  - BLItem : volume ≤ 15 → VEH < 15m3 ; ≤ 50 → VEH > 15m3 ; > 50 → VEH > 50m3 ;
  - TYPE D'ACTION : Côte d'Ivoire → IMPORT, Togo → TRANSBO, Burkina/Mali/Niger → TRANSIT ;
  - FINAL DESTINATION IPAKI = pays ; POL/POD IPAKI = UN/LOCODE ;
  - unités portées : porteur « RLT », remorque attelée « AT <châssis du porteur> »,
    unité empilée « DS <châssis de la remorque, sinon du porteur> », poids et volume 0.
Pas de dépendance Streamlit : testable seul.
"""
import datetime
import io
import re

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

SHEET = "MASQUE IPAKI TETRAX"
# Libellés exacts du masque agent (espaces doubles et finaux compris ; colonne S sans titre).
COLUMNS = [
    "NBRE", "MODE DE TRANSPORT", "ESCALE TETRAX", "NATURE BL", "POL  TETRAX", "POD TETRAX",
    "FINAL DESTINATION TETRAX", "POIDS TETRAX (KG)", "BL", "ESCALE IPAKI", "POL IPAKI",
    "POD IPAKI", "FINAL DESTINATION IPAKI", "MARQUE ", "MODELE", "MARQUE & MODELE", "ETAT",
    "ANNEE DE FABRICATION ", "", "CHÂSSIS", "TYPE D'ACTION", "POIDS IPAKI (TON)", "VOLUME",
    "BLItem YardItemCode", "CLIENT ", "OBSERVATION",
]
ETAT_NEUF = "VEHICULES NEUFS, VOITURES NEUVES, CAMION"
ETAT_USAGE = "VEHICULES USAGES,VOITURES OCCASIONS"

LOCODE = {
    "ABIDJAN": "CIABJ", "SAN PEDRO": "CISPY", "ANTWERP": "BEANR", "ANVERS": "BEANR",
    "HAMBURG": "DEHAM", "BREMERHAVEN": "DEBRV", "AMSTERDAM": "NLAMS", "ROTTERDAM": "NLRTM",
    "TILBURY": "GBTIL", "LIVERPOOL": "GBLIV", "SOUTHAMPTON": "GBSOU", "PORTBURY": "GBPRU",
    "LE HAVRE": "FRLEH", "VALENCIA": "ESVLC", "SAVONA": "ITSVN", "NAPLES": "ITNAP",
    "SALERNO": "ITSAL", "BALTIMORE": "USBAL", "DAVISVILLE": "USDVV", "HALIFAX": "CAHAL",
    "DURBAN": "ZADUR", "LAGOS": "NGLOS", "TIN CAN": "NGTIN", "COTONOU": "BJCOO",
    "LOME": "TGLFW", "TEMA": "GHTEM", "DAKAR": "SNDKR", "CONAKRY": "GNCKY",
    # Asie (navires à grue, ALIS) — 11/11
    "SHANGHAI": "CNSHA", "TIANJIN": "CNTXG", "XINGANG": "CNTXG", "QINGDAO": "CNTAO",
    "NINGBO": "CNNGB", "GUANGZHOU": "CNCAN", "NANSHA": "CNNSA", "LIANYUNGANG": "CNLYG",
    "DALIAN": "CNDLC", "XIAMEN": "CNXMN", "SHEKOU": "CNSHK", "SHENZHEN": "CNSZX",
    "JINGTANG": "CNJTG", "TAICANG": "CNTAG", "YANTAI": "CNYNT", "ZHANGJIAGANG": "CNZJG",
    "KOBE": "JPUKB", "YOKOHAMA": "JPYOK", "NAGOYA": "JPNGO", "KANDA": "JPKND",
    "ULSAN": "KRUSN", "PYEONGTAEK": "KRPTK", "BUSAN": "KRPUS", "MOKPO": "KRMOK",
    "MUNDRA": "INMUN", "PIPAVAV": "INPAV", "CHENNAI": "INMAA", "NHAVA SHEVA": "INNSA",
    "GUNSAN": "KRKUV", "ENNORE": "INENR", "KAMARAJAR": "INENR",
    "PORT KLANG": "MYPKG", "SINGAPORE": "SGSIN", "LAEM CHABANG": "THLCH", "JEDDAH": "SAJED",
}
# Pays de destination finale -> (libellé Ipaki, type d'action, ville par défaut).
PAYS = {
    "COTE D'IVOIRE": ("COTE D'IVOIRE", "IMPORT", "ABIDJAN"),
    "BURKINA FASO": ("BURKINA FASO", "TRANSIT", "OUAGADOUGOU"),
    "MALI": ("MALI", "TRANSIT", "BAMAKO"),
    "NIGER": ("NIGER", "TRANSIT", "NIAMEY"),
    "TOGO": ("TOGO", "TRANSBO", "LOME"),
}

PIGGY_ATTELEE, PIGGY_EMPILEE = "Attelée", "Empilée"
try:
    import vehicle_models as _vm
    _MARQUES = sorted(_vm.BRANDS, key=len, reverse=True)     # noms complets, plus longs d'abord
except Exception:          # module autonome si vehicle_models est absent
    _MARQUES = []
EPM_RE = re.compile(r"\bDISMOUNTED\b|\bD[EÉ]MONT[EÉ]", re.I)


# Colis sur le B/L d'un véhicule -> OBSERVATION « EPM/<nature des colis> », en anglais comme le
# manifeste (ex. EPM/TOOL KIT BOXES) ; plusieurs sortes de colis ou description longue -> EPM/ACCESSORIES.
_COLIS_BRUIT_RE = re.compile(r"\b(?:BREAKBULK|\d+\s*X|\d+\s*Q'?TY|Q'?TY|\d+\s*P'?KGS?|P'?KGS?|PACKAGES?|PCS|PIECES?|UNITS?|NOS)\b|[:;]", re.I)
_COLIS_GENERIQUE = {"", "COLIS", "COLIS A IDENTIFIER", "COLIS SANS CHASSIS"}
EPM_LIB_MAX = 30


def libelle_epm(descriptions) -> str:
    libs = set()
    for d in descriptions or []:
        t = re.sub(r"\s+", " ", _COLIS_BRUIT_RE.sub(" ", str(d or ""))).strip(" .,-").upper()
        if t not in _COLIS_GENERIQUE:
            libs.add(t)
    if len(libs) == 1:
        lib = libs.pop()
        if len(lib) <= EPM_LIB_MAX:
            return lib
    return "ACCESSORIES"


def _txt_cellule(v) -> str:
    return "" if v is None or (isinstance(v, float) and v != v) or str(v) in ("nan", "None") else str(v)
CHASSIS_SALE_RE = re.compile(r"[^A-Z0-9]")

# Niveaux des points à vérifier (couleur du masque annoté).
ROUGE, ORANGE, JAUNE = "Incohérence", "État à confirmer", "À vérifier"
_COULEUR = {ROUGE: "F8CBAD", ORANGE: "FCE4D6", JAUNE: "FFF2CC"}
_ORDRE = {ROUGE: 0, ORANGE: 1, JAUNE: 2}


_VIN_ANNEES = "ABCDEFGHJKLMNPRSTVWXY123456789"   # 10e caractère du VIN (ISO 3779), cycle de 30 ans


def annee_vin(ch: str):
    """Année-modèle lue au 10e caractère d'un VIN de 17 caractères, ramenée au cycle
    le plus récent qui ne dépasse pas l'an prochain ; None si illisible."""
    ch = str(ch or "").upper()
    if len(ch) != 17 or ch[9] not in _VIN_ANNEES:
        return None
    y = 2010 + _VIN_ANNEES.index(ch[9])
    while y > datetime.date.today().year + 1:
        y -= 30
    # Année-modèle N+1 (VIN « V » en 2026) : construit au plus tard cette année. Les agents
    # écrivent l'année en cours (IF608 : 62 VIN 2027 saisis 2026).
    return min(y, datetime.date.today().year)


# Constructeurs chinois : préfixe du code de modèle (norme GB 9417), quand la marque
# n'est pas écrite au manifeste. Seulement les préfixes sans ambiguïté.
_CODE_CONSTRUCTEUR = {
    "ZK": "YUTONG", "XZJ": "XCMG", "XMQ": "KING LONG", "XML": "GOLDEN DRAGON", "SYM": "SANY",
    "ZLJ": "ZOOMLION", "QL": "QINGLING", "ZZ": "SINOTRUK", "SX": "SHACMAN", "CA": "FAW",
    "BJ": "FOTON", "HFC": "JAC", "SEM": "SEM", "CL": "CHENGLI",   # CL5250JSQ6 : grue sur porteur Chengli
}
# 4e caractère du code GB = catégorie ; « 9 » = semi-remorque (ex. ZCZ9400TPBH, JJD9406GPG)
_SEMI_RE = re.compile(r"^([A-Z]{2,4})9\d{3}([A-Z]*)\d*$")


# ── Nettoyage MARQUE / MODELE (12/11) ───────────────────────────────────────
# Gammes et graphies ramenées à la marque ; valeurs qui ne sont pas des marques.
_MARQUE_CANON = {"HOWO": "SINOTRUK", "MARUTI SUZUKI": "SUZUKI", "MARUTI": "SUZUKI",
                 "ROVER": "LAND ROVER", "RANGE ROVER": "LAND ROVER", "BENZ": "MERCEDES",
                 "MERCEDES-BENZ": "MERCEDES", "MERCEDES BENZ": "MERCEDES"}
_ALIAS_EN_TETE = {"MERCEDES": ("MERCEDES-BENZ", "MERCEDES BENZ", "BENZ"), "SUZUKI": ("MARUTI SUZUKI", "MARUTI")}
_PAS_UNE_MARQUE = {"DIVERS", "TRAILER", "VIN", "CHASSIS", "VARIOUS", "UNKNOWN", "N/A", "NA"}
# Mots d'état, d'emballage ou de phrase : jamais un modèle.
_BRUIT_MODELE = {"NEW", "USED", "UNPACKED", "NOUVELLE", "NOUVEAU", "NEUF", "NEUVE", "BRAND",
                 "AUTOMOBILE", "AUTOMOBILES", "VEHICLE", "VEHICLES", "VEHICULE", "VEHICULES",
                 "UNIT", "UNITS", "PRODUCTION", "DISMOUNTED", "DISMANTLED", "MAKE", "OF", "MODEL",
                 "MODELE", "TYPE", "DONT", "X", "PCS", "PIECES", "UNITE", "UNITES"}
# Étiquette : tout ce qui suit n'est plus le modèle.
_ETIQUETTE_RE = re.compile(r"\b(?:CHASSIS|CHASIS|CHASSI|VIN|ENGINE|MOTEUR|SERIAL|S/N|SERIE|SERIES NO|"
                           r"N[º°]|NO\.?\s*:|HS\s*CODE|PIN)\b.*$")
# Mots de type d'engin : avec un code modèle, le code passe devant (« EC300FL3 CRAWLER EXCAVATOR »).
_TYPE_ENGIN = {"CRAWLER", "EXCAVATOR", "ARTICULATED", "HAULER", "DUMP", "DUMPTRUCK", "TRUCK", "TRUCKS",
               "WHEEL", "LOADER", "WHEELLOADER", "BULLDOZER", "DOZER", "COMPACTOR", "ROLLER", "GRADER",
               "MOTOR", "CRANE", "FORKLIFT", "DRILLING", "RIG", "TRACTOR", "BACKHOE", "PAVER", "MIXER",
               "TIPPER", "HYDRAULIC", "MINI", "SKID", "STEER", "TELEHANDLER", "SINGLE", "DRUM", "TANDEM",
               "TOMBEREAU", "RIGIDE", "PELLE", "CHARGEUSE"}


def _code_modele(t: str) -> bool:
    return 2 <= len(t) <= 11 and bool(re.search(r"\d", t)) and bool(re.search(r"[A-Z]", t))


def nettoyer_marque_modele(marque: str, modele: str, chassis: str = ""):
    """MARQUE ramenée à une vraie marque ; MODELE débarrassé des mots d'état, étiquettes,
    numéros, marque répétée et doublons. La finition des voitures est gardée (choix A)."""
    marque = re.sub(r"\s+", " ", str(marque or "")).strip().upper()
    marque = _MARQUE_CANON.get(marque, marque)
    if marque in _PAS_UNE_MARQUE:
        marque = ""
    m = re.sub(r"\s+", " ", str(modele or "")).strip().upper()
    if m.startswith("SEMI-REMORQUE"):
        return marque, m
    # semi-remorque (code de catégorie 9) : jamais la marque du camion porteur
    if _SEMI_RE.match(re.sub(r"\s+", "", m.split(" ")[0] if m else "")):
        return "", m
    m = _ETIQUETTE_RE.sub("", m).strip(" -:,;/")
    # marque répétée en tête (« RENAULT EXPRESS », « BENZ SPRINTER », « MARUTI ALTO ») ;
    # un nom de gamme qui est le modèle (« RANGE ROVER VOGUE ») reste.
    for tete in sorted({marque, *_ALIAS_EN_TETE.get(marque, ())}, key=len, reverse=True):
        if tete and (m == tete or m.startswith(tete + " ")):
            m = m[len(tete):].strip(" -:,;/")
            break
    mots_marque = {marque} if marque and " " not in marque else set()
    ch_norm = re.sub(r"[^A-Z0-9]", "", str(chassis or "").upper())
    out = []
    for t in m.split():
        nu = t.strip("()[].,;:-*\"'")
        if not nu:
            continue
        if not out and re.fullmatch(r"\(?\d+\)?", nu):                 # quantité en tête
            continue
        if nu in _BRUIT_MODELE or nu.rstrip("(S)") in _BRUIT_MODELE or nu in mots_marque:
            continue
        if (ch_norm and nu == ch_norm) or re.search(r"\d{6,}", nu):
            continue                         # le châssis lui-même, n° de série, code d'usine (ONK1C2E00018000)
        if out and out[-1] == nu:
            continue                                                    # mot doublé
        out.append(t.strip(",;:*"))
    codes = [t for t in out if _code_modele(t)]
    if len(codes) == 1 and out and all(t in _TYPE_ENGIN or t == codes[0] for t in out) and out[0] != codes[0]:
        out = codes + [t for t in out if t != codes[0]]
    return marque, " ".join(out).strip()


# ── Garde-fou : un modèle lu dans la colonne châssis (bug remonté le 23/11) ──
_SERIE_RE = re.compile(r"\d{5,}")                   # n° de série : 5 chiffres d'affilée ou plus


def chassis_est_modele(ch: str, modele: str = "", description: str = "") -> str:
    """Motif si la valeur de la colonne châssis est en fait le modèle (code écrit tel quel
    dans le modèle ou la description, ou simple mot sans chiffre), sinon "".
    Jamais un VIN de 17 caractères ni un n° de série (5 chiffres d'affilée ou plus)."""
    n = re.sub(r"[^A-Z0-9]", "", str(ch or "").upper())
    if not n:
        return ""
    if not re.search(r"\d", n):
        return "mot sans chiffre, pas un châssis"
    if len(n) == 17 or len(n) > 12 or _SERIE_RE.search(n) or not re.search(r"[A-Z]", n):
        return ""
    for texte in (modele, description):
        t = _ETIQUETTE_RE.sub("", re.sub(r"\s+", " ", str(texte or "").upper()))
        mots = {re.sub(r"[^A-Z0-9]", "", w) for w in re.split(r"[\s,;/()]+", t)}
        if n in mots or n == re.sub(r"[^A-Z0-9]", "", t):
            return "identique au modèle écrit au manifeste"
    return ""


def marque_par_code(chassis: str, modele: str):
    """Marque déduite du préfixe constructeur du VIN, sinon du code de modèle chinois.
    Renvoie (marque, modèle, motif du point si la marque reste inconnue)."""
    m_vin = _vm._wmi(chassis) if _MARQUES else None
    if m_vin:
        return m_vin.upper(), modele, ""
    code = re.sub(r"\s+", "", str(modele or "").upper())
    for pref, nom in sorted(_CODE_CONSTRUCTEUR.items(), key=lambda kv: -len(kv[0])):
        if re.match(re.escape(pref) + r"\d", code):
            return nom, modele, ""
    if _SEMI_RE.match(code) or code.startswith("TANKER"):
        # modèle laissé tel qu'écrit au manifeste (en anglais), sans libellé ajouté
        return "", modele, ("Semi-remorque chinoise : fabricant non écrit au manifeste "
                            "(petit constructeur), marque à compléter si l'agent la connaît.")
    return "", modele, ""


def locode(port: str) -> str:
    p = str(port or "").upper()
    for nom, code in LOCODE.items():
        if nom in p:
            return code
    # « TIAN JIN(BH) » : même recherche sans espaces
    p_sans = re.sub(r"\s+", "", p)
    for nom, code in LOCODE.items():
        if re.sub(r"\s+", "", nom) in p_sans:
            return code
    return ""


def yard_code(volume) -> str:
    try:
        v = float(volume or 0)
    except (TypeError, ValueError):
        v = 0.0
    if v != v or v <= 15:          # NaN ou ≤ 15 (unités portées à 0 comprises)
        return "VEH < 15m3"
    return "VEH > 15m3" if v <= 50 else "VEH > 50m3"


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


MAX_PORTEES = 4          # convention agents : 4 unités portées au plus sur un même châssis
MARQUES_REMORQUE = {"KRONE", "SCHMITZ", "FRUEHAUF", "VAN HOOL", "HUMBAUR", "GROENEWEGEN", "ROBUSTE",
                    "ACTM", "KOEGEL", "KÖGEL", "WIELTON", "LAMBERET", "CHEREAU", "PACTON", "GOLDHOFER",
                    "FLIEGL", "KASSBOHRER", "TRAILOR", "SAMRO", "NOOTEBOOM", "FAYMONVILLE"}


def _refs_portage(g_bl) -> dict:
    """châssis porté -> châssis de son porteur, tel que listé au manifeste (colonne _Ref_Portage)."""
    out = {}
    if g_bl is None or len(g_bl) == 0 or "_Ref_Portage" not in g_bl.columns:
        return out
    for v in g_bl["_Ref_Portage"].dropna():
        for paire in str(v).split(";"):
            if ">" in paire:
                c, ref = paire.split(">", 1)
                out.setdefault(c.strip(), ref.strip())
    return out


def _piggy_map(g_bl) -> dict:
    """châssis -> (type de portage ou "", texte descriptif) depuis le DataFrame structuré."""
    out = {}
    if g_bl is None or len(g_bl) == 0:
        return out
    for _, r in g_bl.iterrows():
        tc = str(r.get("Type_Colis") or "")
        kind = PIGGY_ATTELEE if tc.startswith("Attelée") else (PIGGY_EMPILEE if tc.startswith("Empilée") else "")
        texte = " ".join(str(r.get(k) or "") for k in ("Commodity", "Modele", "Type_Colis"))
        for ch in str(r.get("Numeros_Chassis") or "").split(";"):
            if ch.strip():
                out.setdefault(ch.strip(), (kind, texte))
    return out


def build_rows(veh_rows, g_bl=None, escale_ipaki="", mode_transport=""):
    """Lignes du masque (dicts sur COLUMNS) et points à vérifier.

    veh_rows : sortie de manifest_parser._rows_vehicule_detail (1 ligne par châssis, dans
    l'ordre du manifeste) ; g_bl : DataFrame structuré (type de portage par châssis)."""
    piggy = _piggy_map(g_bl)
    refs = _refs_portage(g_bl)
    rows, points = [], []
    vus = {}
    porteur_marque = {}                # B/L -> marque de la dernière unité non portée
    porteur = remorque = None          # châssis courants de la chaîne, par B/L
    bl_courant = None

    def point(i, niveau, colonne, texte):
        points.append({"ligne": i, "niveau": niveau, "colonne": colonne, "texte": texte})

    for i, r in enumerate(veh_rows, start=1):
        ch = str(r.get("Chassis") or "").strip()
        # Modèle lu dans la colonne châssis : ligne gardée, châssis vidé (à saisir), modèle conservé.
        motif = chassis_est_modele(ch, r.get("Modele"), r.get("Description_Modele"))
        if motif:
            if not str(r.get("Modele") or "").strip():
                r = {**r, "Modele": ch}
            point(i, ROUGE, "CHÂSSIS", f"« {ch} » lu comme châssis ({motif}) : châssis vidé, "
                                       "vrai châssis à saisir avant l'intégration dans Ipaki.")
            ch = ""
        bl = str(r.get("BL_Numero") or "")
        kind, texte = piggy.get(ch, ("", r.get("_texte", "")))
        if bl != bl_courant:
            porteur = remorque = None
            bl_courant = bl
        if not bl.strip():
            point(i, ROUGE, "BL", f"B/L absent du manifeste pour le châssis {ch or '?'} : "
                                  "à saisir avant l'intégration dans Ipaki.")

        pays_t = str(r.get("Pays_Transit") or "").strip().upper()
        if pays_t in PAYS:
            pays, action, ville_def = PAYS[pays_t]
        elif pays_t:
            pays, action, ville_def = pays_t, "TRANSIT", ""
        else:
            pays, action, ville_def = PAYS["COTE D'IVOIRE"]
        nature = r.get("Nature_BL") or "Import"
        if nature == "Export":
            action = "EXPORT"
        elif nature in ("Transbo", "Transb.") and action == "IMPORT":
            action = "TRANSBO"
        ville = str(r.get("Destination_Brute") or "").strip().upper() or (
            str(r.get("Port_Dechargement") or "").upper() if action == "IMPORT" else ville_def)
        if action in ("TRANSIT", "TRANSBO") and not str(r.get("Destination_Brute") or "").strip():
            point(i, JAUNE, "FINAL DESTINATION TETRAX",
                  f"Ville non écrite au manifeste : {ville or '?'} proposée pour {pays}.")

        # Chaîne porteur / attelée / empilée
        obs = ""
        if kind == PIGGY_ATTELEE:
            obs = f"AT {porteur}" if porteur else "AT"
            remorque = ch
        elif kind == PIGGY_EMPILEE:
            ref = remorque or porteur
            obs = f"DS {ref}" if ref else "DS"
        else:
            porteur, remorque = ch, None
        if kind and refs.get(ch):         # porteur sous lequel le manifeste liste l'unité
            obs = f"{'AT' if kind == PIGGY_ATTELEE else 'DS'} {refs[ch]}"
        if kind and obs in ("AT", "DS"):
            point(i, ROUGE, "OBSERVATION", "Unité portée sans unité porteuse identifiée sur ce B/L.")
        if not obs and EPM_RE.search(texte):
            obs = "EPM"
            point(i, JAUNE, "OBSERVATION", "Engin démonté (EPM proposé) : confirmer.")
        colis_bl = r.get("_colis_bl")
        if colis_bl is not None and obs in ("", "EPM"):      # AT / DS (portage) restent prioritaires
            obs = "EPM/" + libelle_epm(colis_bl)
            point(i, JAUNE, "OBSERVATION", f"Colis sur ce B/L : « {obs} » proposé, à confirmer.")

        poids = _num(r.get("Poids_Unitaire_Kg"))
        volume = _num(r.get("Volume_CBM"))
        if kind:
            poids, volume = 0.0, 0.0
        elif poids is None:
            point(i, ROUGE, "POIDS TETRAX (KG)", "Poids absent du manifeste pour cette unité.")
        if not kind and volume is None:
            point(i, JAUNE, "VOLUME", "Volume absent : classe BLItem à confirmer.")

        # Année puis état (décision du 23/11) : NEW écrit -> NEUF ; USED écrit -> USAGÉ ;
        # sinon année de fabrication >= année en cours -> NEUF, plus ancienne ou inconnue -> USAGÉ.
        an_courant = datetime.date.today().year
        annee_ecrite = int(_num(r.get("Annee_Fabrication"))) if _num(r.get("Annee_Fabrication")) else ""
        if annee_ecrite and annee_ecrite > an_courant:
            # année-modèle N+1 (VIN « V ») : construit au plus tard cette année, comme les agents
            annee_ecrite = an_courant
        annee_lue = annee_ecrite or annee_vin(ch) or ""
        etat = r.get("Etat") or ""
        if etat == "Neuf":
            etat_lib = ETAT_NEUF
        elif etat == "Usager":
            etat_lib = ETAT_USAGE
            if annee_lue and annee_lue >= an_courant:
                point(i, ORANGE, "ETAT", f"USED écrit au manifeste mais année {annee_lue} : USAGÉ gardé, à confirmer.")
        elif annee_lue and annee_lue >= an_courant:
            etat, etat_lib = "Neuf", ETAT_NEUF
            point(i, JAUNE, "ETAT", f"Aucun état écrit : NEUF car année de fabrication {annee_lue}.")
        else:
            etat_lib = ETAT_USAGE
            point(i, ORANGE, "ETAT", "Aucun état écrit au manifeste : USAGÉ par défaut, NEUF si l'agent le confirme.")

        client = str(r.get("Destinataire_Nom") or "").strip()
        notify = str(r.get("Notify_Nom") or "").strip()
        if not client or re.match(r"TO\s+(THE\s+)?ORDER", client, re.I):
            # Destinataire « à ordre » (banque) : le client est le notify (règle agent).
            if notify and not re.match(r"SAME\s+AS", notify, re.I):
                client = notify
            else:
                point(i, JAUNE, "CLIENT ", "Destinataire « à ordre » sans notify exploitable : client à saisir.")

        if not ch:
            if not motif:
                point(i, ROUGE, "CHÂSSIS", "Châssis absent du manifeste : à saisir (facture / packing list) "
                                           "avant l'intégration dans Ipaki.")
        elif CHASSIS_SALE_RE.search(ch.upper()):
            point(i, ROUGE, "CHÂSSIS", "Caractère inattendu dans le châssis.")
        elif len(ch) != 17:
            point(i, JAUNE, "CHÂSSIS", f"Châssis de {len(ch)} caractères (17 attendus pour un VIN ; normal pour un engin).")
        if ch and ch in vus:
            point(i, ROUGE, "CHÂSSIS", f"Châssis en double (déjà ligne {vus[ch]}).")
        if ch:
            vus.setdefault(ch, i)

        marque = str(r.get("Marque") or "").strip().upper()
        modele = str(r.get("Modele") or "").strip().upper()
        desc = re.sub(r"\s+", " ", str(r.get("Description_Modele") or "")).strip().upper()
        if desc and not kind:
            # Les agents recopient la description commerciale du manifeste, sans la marque.
            desc = re.sub(r"\s+\d{6,}$", "", desc)          # code HS ou n° en fin de ligne
            en_tete = next((k for k in _MARQUES if re.match(re.escape(k) + r"[\s/]", desc)), None)
            if marque and re.match(re.escape(marque) + r"[\s/]", desc):
                desc = desc[len(marque):].strip(" /")
            elif en_tete:
                # Marque connue écrite en tête de description (BAUER, DYNAPAC, IRISBUS…) : elle prime.
                marque, desc = _vm.BRANDS[en_tete].upper(), desc[len(en_tete):].strip(" /")
            elif not marque and len(desc.split()) > 1:
                # Marque inconnue de la liste : premier mot, comme le font les agents (à vérifier).
                marque, desc = desc.split(" ", 1)
                point(i, JAUNE, "MARQUE ", f"Marque « {marque} » hors liste connue : à vérifier.")
            desc = re.sub(r"^NEW\s+", "", desc)
            modele = desc or modele
        elif kind == PIGGY_ATTELEE:
            # Remorque : marque écrite après son châssis, sinon préfixe constructeur du VIN
            # (VFK = Fruehauf) ; jamais celle du camion porteur.
            m_vin = _vm._wmi(ch) if _MARQUES else None
            if m_vin:
                marque = m_vin.upper()
            elif marque and porteur_marque.get(bl) == marque:
                marque = ""
                point(i, JAUNE, "MARQUE ", "Marque de la remorque non écrite : à compléter.")
            modele = "TRAILER"
        if not kind:
            marque, modele = nettoyer_marque_modele(marque, modele, ch)
            if not modele:
                point(i, JAUNE, "MODELE", "Modèle non écrit au manifeste (ou seulement du texte inutile).")
        if not marque:
            marque, modele, motif = marque_par_code(ch, modele)
            if not marque:
                point(i, JAUNE, "MARQUE ", motif or "Marque non reconnue.")
        if not modele and str(marque).upper() in MARQUES_REMORQUE:
            modele = "TRAILER"
        # Année : écrite au manifeste, sinon convention des agents (vérifiée sur GSL0526,
        # 314/321) : véhicule neuf -> année en cours ; usagé -> année du VIN, sinon 2000.
        annee = annee_ecrite
        if not annee:
            if etat == "Neuf":
                annee = datetime.date.today().year
            elif annee_vin(ch):
                annee = annee_vin(ch)
                point(i, JAUNE, "ANNEE DE FABRICATION ", f"Année non écrite : {annee} lue dans le VIN.")
            else:
                annee = 2000
                point(i, JAUNE, "ANNEE DE FABRICATION ", "Année non écrite ni lisible dans le châssis : 2000 par défaut.")

        if not kind:
            porteur_marque[bl] = marque
        rows.append({
            "NBRE": i, "MODE DE TRANSPORT": mode_transport or "", "ESCALE TETRAX": "",
            "NATURE BL": nature, "POL  TETRAX": str(r.get("Port_Chargement") or "").upper(),
            "POD TETRAX": str(r.get("Port_Dechargement") or "").upper(),
            "FINAL DESTINATION TETRAX": ville,
            "POIDS TETRAX (KG)": round(poids) if poids is not None else "",
            "BL": bl, "ESCALE IPAKI": escale_ipaki or "",
            "POL IPAKI": locode(r.get("Port_Chargement")), "POD IPAKI": locode(r.get("Port_Dechargement")),
            "FINAL DESTINATION IPAKI": pays,
            "MARQUE ": marque, "MODELE": modele, "MARQUE & MODELE": f"{marque} {modele}".strip(),
            "ETAT": etat_lib, "ANNEE DE FABRICATION ": annee, "": len(ch), "CHÂSSIS": ch,
            "TYPE D'ACTION": action,
            "POIDS IPAKI (TON)": round(poids / 1000, 3) if poids is not None else "",
            "VOLUME": round(volume, 3) if volume is not None else "",
            "BLItem YardItemCode": yard_code(volume), "CLIENT ": client, "OBSERVATION": obs,
        })
        if not rows[-1]["POL IPAKI"]:
            point(i, JAUNE, "POL IPAKI", "Port de chargement sans code UN/LOCODE connu.")

    # Porteur = toute unité suivie d'au moins une unité portée sur le même B/L.
    for k, row in enumerate(rows):
        if row["OBSERVATION"].startswith(("AT ", "DS ")):
            ref = row["OBSERVATION"][3:]
            for j in range(k - 1, -1, -1):
                if rows[j]["CHÂSSIS"] == ref and rows[j]["BL"] == row["BL"]:
                    if not rows[j]["OBSERVATION"]:
                        rows[j]["OBSERVATION"] = "RLT"
                    break
    # Convention : au plus 4 unités portées (AT / DS) sur un même châssis.
    portees = {}
    for row in rows:
        if row["OBSERVATION"].startswith(("AT ", "DS ")):
            portees.setdefault((row["BL"], row["OBSERVATION"][3:]), []).append(row["CHÂSSIS"])
    for (bl_p, ref), lst in portees.items():
        if len(lst) > MAX_PORTEES:
            points.append({"ligne": None, "niveau": ROUGE, "colonne": "OBSERVATION",
                           "texte": f"B/L {bl_p} : {len(lst)} unités portées par {ref} (convention : "
                                    f"{MAX_PORTEES} au maximum) : vérifier le porteur de chaque unité."})
    rows = _regles_du_fournisseur(rows, points)
    if not escale_ipaki:
        points.insert(0, {"ligne": None, "niveau": JAUNE, "colonne": "ESCALE IPAKI",
                          "texte": "Code escale Ipaki non saisi : à saisir dans l'app avant l'export."})
    if not mode_transport:
        points.insert(0, {"ligne": None, "niveau": JAUNE, "colonne": "MODE DE TRANSPORT",
                          "texte": "Mode de transport (n° Tetrax) non saisi : à saisir dans l'app avant l'export."})
    return rows, points


# ── Fichier 1 : pré-masque pour Ipaki (données seules) ─────────────────────────
def ipaki_xlsx_bytes(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.append(COLUMNS)
    for r in rows:
        ws.append([r[c] for c in COLUMNS])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Fichier 2 : onglets de vérification (ajoutés au classeur d'export) ──────────
_NAVY = "1F3864"
_GUIDE_ETAPES = [
    "1. Saisir dans l'app le mode de transport et le code escale Ipaki avant de télécharger.",
    "2. Onglet À VÉRIFIER : contrôler les totaux (✓ attendu partout).",
    "3. Traiter les points du haut vers le bas (rouge, puis orange, puis jaune) : Ctrl+clic sur « Aller » ouvre la ligne.",
    "4. Corriger dans l'app quand c'est possible (puis re-télécharger), sinon dans le pré-masque Ipaki.",
    "5. Cocher « Vérifié » (x) en colonne A ; le compteur en haut indique ce qui reste.",
    "   État : NEW écrit = neuf ; USED écrit = usagé ; sinon année égale ou postérieure à l'année en cours = neuf, sinon usagé (signalé).",
    "   Année non écrite au manifeste : neuf = année en cours ; usagé = année du VIN, sinon 2000 (signalé).",
    "6. Intégrer dans Ipaki le fichier PREMASQUE_IPAKI (jamais ce fichier de vérification).",
]
_RACCOURCIS = [
    ("Ctrl+Maj+L", "Activer ou retirer les filtres"), ("Alt+↓", "Ouvrir la liste d'un filtre"),
    ("Ctrl+F / Ctrl+H", "Rechercher / remplacer"), ("Ctrl+flèche", "Aller au bout des données"),
    ("Ctrl+Début", "Revenir en haut"), ("F2", "Modifier la cellule"), ("Ctrl+D", "Recopier vers le bas"),
    ("Ctrl+clic", "Suivre un lien (Aller / ↩)"), ("Ctrl+Z", "Annuler"), ("Ctrl+S", "Enregistrer"),
]


def _entete(ws, row, valeurs):
    for j, v in enumerate(valeurs, 1):
        c = ws.cell(row=row, column=j, value=v)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", start_color=_NAVY, end_color=_NAVY)


def add_verification_sheets(wb, rows, points, navire="", voyage="", totaux=None, index=0):
    """Ajoute « À VÉRIFIER », « Masque annoté » et « GUIDE » à un classeur openpyxl.
    totaux : lignes de texte du contrôle des totaux (manifest_totals.agent_message)."""
    # Points identiques sur un même B/L (état non écrit, ville par défaut…) : une seule
    # entrée dans À VÉRIFIER, toutes les cellules concernées restent colorées.
    groupes, ordre = {}, []
    for p in points:
        bl = rows[p["ligne"] - 1]["BL"] if p["ligne"] else ""
        k = (p["niveau"], p["colonne"], p["texte"], bl) if p["ligne"] else id(p)
        if k not in groupes:
            groupes[k] = dict(p, lignes=[p["ligne"]] if p["ligne"] else [])
            ordre.append(k)
        else:
            groupes[k]["lignes"].append(p["ligne"])
    points = [groupes[k] for k in ordre]
    for p in points:
        if len(p["lignes"]) > 1:
            p["texte"] = f"{p['texte']} ({len(p['lignes'])} lignes de ce B/L)"
    points = sorted(points, key=lambda p: (_ORDRE[p["niveau"]], p["ligne"] or 0))
    wv = wb.create_sheet("À VÉRIFIER", index)
    wm = wb.create_sheet("Masque annoté", index + 1)

    # Masque annoté : mêmes colonnes, + lien retour.
    _entete(wm, 1, COLUMNS + ["↩"])
    for r in rows:
        wm.append([r[c] for c in COLUMNS])
    col_idx = {c: j for j, c in enumerate(COLUMNS, 1)}
    for p in points:
        for ligne in p.get("lignes") or ([p["ligne"]] if p["ligne"] else []):
            cell = wm.cell(row=ligne + 1, column=col_idx.get(p["colonne"], 1))
            cell.fill = PatternFill("solid", start_color=_COULEUR[p["niveau"]], end_color=_COULEUR[p["niveau"]])
            old = cell.comment.text + "\n" if cell.comment else ""
            cell.comment = Comment(old + f"{p['niveau']} : {p['texte']}", "Manifestes Terra")
    wm.freeze_panes = "A2"
    wm.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{len(rows) + 1}"

    # À VÉRIFIER
    wv["A1"] = f"À VÉRIFIER — {navire} / {voyage}".strip(" —/")
    wv["A1"].font = Font(bold=True, size=13)
    wv["A2"] = ("Aide : traiter du rouge au jaune · Ctrl+clic sur « Aller » ouvre la ligne · "
                "mettre x en colonne A une fois vérifié · voir l'onglet GUIDE.")
    n = len(points)
    wv["A5"] = "Contrôle des totaux"
    wv["A5"].font = Font(bold=True)
    r0 = 6
    lignes_tot = [f"Unités dans le masque : {len(rows)}"] + list(totaux or [])
    for k, t in enumerate(lignes_tot):
        wv.cell(row=r0 + k, column=1, value=t).alignment = Alignment(wrap_text=True)
    h = r0 + len(lignes_tot) + 1
    _entete(wv, h, ["Vérifié (x)", "Niveau", "Ligne", "B/L", "Châssis", "Colonne", "Point", "Aller"])
    for k, p in enumerate(points, h + 1):
        r = rows[p["ligne"] - 1] if p["ligne"] else {}
        vals = ["", p["niveau"], p["ligne"] or "", r.get("BL", ""), r.get("CHÂSSIS", ""), p["colonne"], p["texte"]]
        for j, v in enumerate(vals, 1):
            c = wv.cell(row=k, column=j, value=v)
            if j == 2:
                c.fill = PatternFill("solid", start_color=_COULEUR[p["niveau"]], end_color=_COULEUR[p["niveau"]])
        if p["ligne"]:
            go = wv.cell(row=k, column=8, value="Aller")
            col = get_column_letter(col_idx.get(p["colonne"], 1))
            go.hyperlink = f"#'Masque annoté'!{col}{p['ligne'] + 1}"
            go.font = Font(color="0563C1", underline="single")
            back = wm.cell(row=p["ligne"] + 1, column=len(COLUMNS) + 1, value="↩ À VÉRIFIER")
            back.hyperlink = f"#'À VÉRIFIER'!A{k}"
            back.font = Font(color="0563C1", underline="single")
    wv["A3"] = f'=COUNTIF(A{h + 1}:A{h + max(n, 1)},"x")&" / {n} points vérifiés"'
    wv["A3"].font = Font(bold=True)
    for j, w in enumerate([11, 16, 7, 14, 21, 24, 70, 8], 1):
        wv.column_dimensions[get_column_letter(j)].width = w
    wv.freeze_panes = f"A{h + 1}"

    # GUIDE
    wg = wb.create_sheet("GUIDE", index + 2)
    wg["A1"] = "Guide de vérification du pré-masque"
    wg["A1"].font = Font(bold=True, size=13)
    for k, t in enumerate(_GUIDE_ETAPES, 3):
        wg.cell(row=k, column=1, value=t)
    k0 = 4 + len(_GUIDE_ETAPES)
    wg.cell(row=k0, column=1, value="Légende : rouge = incohérence · orange = état à confirmer · jaune = à vérifier.")
    _entete(wg, k0 + 2, ["Raccourci Excel", "Action"])
    for k, (a, b) in enumerate(_RACCOURCIS, k0 + 3):
        wg.cell(row=k, column=1, value=a)
        wg.cell(row=k, column=2, value=b)
    wg.cell(row=k0 + 4 + len(_RACCOURCIS), column=1,
            value="Excel n'a pas de bouton « retour » : utiliser le lien « ↩ À VÉRIFIER » en fin de ligne du masque annoté.")
    wg.column_dimensions["A"].width = 22
    wg.column_dimensions["B"].width = 60
    return wv, wm, wg


# ── Autres formats (navires à grue, ALIS MOL/NYK/K LINE/EUKOR, scans) ─────────
# Ils produisent déjà un DataFrame « pré-masque » (crane_manifest_parser) : on le
# ramène aux champs du parser Grimaldi pour appliquer exactement les mêmes règles.
def _etat_court(v) -> str:
    t = str(v or "").upper()
    if "NEUF" in t or "NEUV" in t or t == "NEW":
        return "Neuf"
    if "USAG" in t or "OCCASION" in t or t == "USED":
        return "Usager"
    return ""


def _pays_depuis_texte(texte: str) -> str:
    import flux_rules
    t = str(texte or "")
    pays = flux_rules.hinterland_country(t)
    if pays:
        return pays
    if re.search(r"\bTOGO\b|\bLOM[EÉ]\b", t, re.I):
        return "Togo"
    return ""


def rows_from_premasque_df(df, escale_ipaki="", mode_transport=""):
    """Lignes du pré-masque Ipaki exact + points à vérifier, depuis le DataFrame
    pré-masque des parsers grue / ALIS / scans. Les colis sans châssis ne vont pas
    dans le pré-masque véhicules : ils sont listés dans les points."""
    try:
        from manifest_parser import ville_destination
    except Exception:
        ville_destination = lambda _a: ""
    veh, notes, colis = [], [], []
    # Colis de chaque B/L : lignes « Colis » du parser + colonne cachée _COLIS_BL (descriptions
    # séparées par « | ») quand le parser ne crée pas de lignes Colis (ex. groupes BREAKBULK EUKOR).
    colis_par_bl = {}
    for _, r in df.iterrows():
        bl_c = _txt_cellule(r.get("BL"))
        if _txt_cellule(r.get("CATEGORIE")).strip().upper() == "COLIS":
            colis_par_bl.setdefault(bl_c, []).append(_txt_cellule(r.get("MARQUE & MODELE") or r.get("MODELE")))
        elif _txt_cellule(r.get("_COLIS_BL")):
            colis_par_bl.setdefault(bl_c, []).extend(_txt_cellule(r.get("_COLIS_BL")).split(" | "))
    for _, r in df.iterrows():
        g = lambda c: ("" if r.get(c) is None or str(r.get(c)) == "nan" else r.get(c))
        ch = str(g("CHÂSSIS")).strip()
        if str(g("CATEGORIE")).strip().upper() == "COLIS":
            colis.append((str(g("BL")), str(g("MARQUE & MODELE") or g("MODELE"))))
            continue
        # véhicule sans châssis au manifeste : gardé, CHÂSSIS vide (point rouge par ligne) ;
        # l'agent le saisit dans l'app ou plus tard dans le fichier exporté (décision du 23/11).
        dest = str(g("FINAL DESTINATION TETRAX") or g("FINAL DESTINATION IPAKI"))
        obs = str(g("OBSERVATION"))
        pays = _pays_depuis_texte(dest + " " + obs)
        ville = ville_destination([dest, obs]) if pays else ""
        nature = str(g("NATURE BL") or "Import")
        veh.append({
            "Chassis": ch, "BL_Numero": str(g("BL")), "Pays_Transit": pays,
            "Destination_Brute": ville, "Nature_BL": "Transbo" if nature.upper().startswith("TRANSB") else nature,
            "Port_Chargement": g("POL TETRAX"), "Port_Dechargement": g("POD TETRAX") or "ABIDJAN",
            "Poids_Unitaire_Kg": g("POIDS TETRAX (KG)") or None,
            "Volume_CBM": g("VOLUME") or g("VOLUME TETRAX") or None,
            "Etat": _etat_court(g("ETAT")), "Destinataire_Nom": g("CLIENT"), "Notify_Nom": "",
            "Marque": g("MARQUE"), "Modele": g("MODELE"), "Description_Modele": "",
            "Annee_Fabrication": g("ANNEE DE FABRICATION"),
            "_texte": f"{g('MODELE')} {obs}",          # « DISMANTLED » -> EPM
            "_colis_bl": colis_par_bl.get(str(g("BL"))),  # colis du même B/L -> EPM/<nature>
        })
        # remarques déjà traduites dans les colonnes (transit, n° BSC) : pas de point
        reste = re.sub(r"TRANSIT\s+VERS\s+[A-Z' -]+|BSC\s*#?\s*[A-Z0-9-]+|AUCUN\s+CHASSIS\s+EXTRAIT[^;|]*|CHASSIS\s+ABSENT\s+DU\s+MANIFESTE[^;|]*|[;,|]",
                       " ", obs, flags=re.I).strip()       # châssis absent : déjà un point rouge
        if reste:
            notes.append((len(veh), obs.strip()))
    rows, points = build_rows(veh, None, escale_ipaki, mode_transport)
    for i, obs in notes:
        points.append({"ligne": i, "niveau": JAUNE, "colonne": "OBSERVATION",
                       "texte": f"Remarque de l'app (non recopiée dans Ipaki) : {obs[:150]}"})
    if colis:
        points.append({"ligne": None, "niveau": JAUNE, "colonne": "BL",
                       "texte": f"{len(colis)} colis sans châssis hors pré-masque véhicules "
                                f"(B/L {', '.join(dict.fromkeys(b for b, _ in colis))[:200]})."})
    return ordonner_portage(rows, points)


_FOREUSE_RE = re.compile(r"DRILL|\bRIG\b", re.I)


def a_completer(df) -> dict:
    """Véhicules à compléter (rappel informatif, jamais bloquant) depuis le DataFrame du
    pré-masque : {"lignes": [{N°, B/L, Manque}], "pieces": bool, "foreuse": bool, "complets": n, "total": n}."""
    lignes, pieces, foreuse, complets, total = [], False, False, 0, 0
    if df is None or not len(df):
        return {"lignes": lignes, "pieces": pieces, "foreuse": foreuse, "complets": 0, "total": 0}
    for k, r in df.reset_index(drop=True).iterrows():
        g = lambda c: _txt_cellule(r.get(c)).strip()
        if g("CATEGORIE").upper() == "COLIS":
            continue
        total += 1
        manque = [lib for lib, ok in (("Châssis", g("CHÂSSIS")),
                                      ("Volume", _num(r.get("VOLUME TETRAX")) or _num(r.get("VOLUME"))),
                                      ("Marque", g("MARQUE")), ("Modèle", g("MODELE"))) if not ok]
        if g("CHÂSSIS") and "Volume" not in manque:
            complets += 1
        if manque:
            lignes.append({"N°": g("NBRE") or k + 1, "B/L": g("BL"), "Manque": " · ".join(manque)})
            pieces = pieces or _txt_cellule(r.get("_PIECES_JOINTES")) == "True"
            foreuse = foreuse or bool(_FOREUSE_RE.search(g("MODELE")))
    return {"lignes": lignes, "pieces": pieces, "foreuse": foreuse, "complets": complets, "total": total}


def ordonner_portage(rows, points):
    """Chaque porteur suivi de ses unités portées, B/L par B/L : le porteur (RLT), sa remorque
    attelée (AT), les unités empilées sur cette remorque (DS), puis celles empilées sur le
    porteur. Les autres lignes gardent leur place ; NBRE est renuméroté et les points
    à vérifier suivent leurs lignes."""
    if not any(str(r.get("OBSERVATION") or "").startswith(("AT ", "DS ")) for r in rows):
        return rows, points
    cles = {(r["BL"], r["CHÂSSIS"]) for r in rows if r["CHÂSSIS"]}
    enfants, portees = {}, set()
    for k, r in enumerate(rows):
        o = str(r.get("OBSERVATION") or "")
        if o.startswith(("AT ", "DS ")) and (r["BL"], o[3:].strip()) in cles:
            enfants.setdefault((r["BL"], o[3:].strip()), []).append(k)
            portees.add(k)
    ordre, poses = [], set()

    def poser(k):
        if k in poses:
            return
        poses.add(k)
        ordre.append(k)
        fils = enfants.get((rows[k]["BL"], rows[k]["CHÂSSIS"]), []) if rows[k]["CHÂSSIS"] else []
        for j in [j for j in fils if rows[j]["OBSERVATION"].startswith("AT ")]:
            poser(j)                    # la remorque attelée, puis ce qui est empilé dessus
        for j in [j for j in fils if rows[j]["OBSERVATION"].startswith("DS ")]:
            poser(j)

    for k in range(len(rows)):
        if k not in portees:
            poser(k)
    for k in range(len(rows)):          # porteur introuvable dans l'ordre (cas anormal) : à la suite
        poser(k)
    nouveau = {old + 1: new + 1 for new, old in enumerate(ordre)}
    rows = [rows[k] for k in ordre]
    for n, r in enumerate(rows, start=1):
        r["NBRE"] = n
    for p in points:
        if p.get("ligne"):
            p["ligne"] = nouveau.get(p["ligne"], p["ligne"])
        p["texte"] = re.sub(r"(déjà ligne )(\d+)", lambda m: m.group(1) + str(nouveau.get(int(m.group(2)), m.group(2))),
                            str(p.get("texte") or ""))
    return rows, points


def verification_from_premasque_df(xls_app_bytes: bytes, df, navire="", voyage="",
                                   escale_ipaki="", mode_transport="") -> bytes:
    """Fichier de vérification : onglets À VÉRIFIER / Masque annoté / GUIDE ajoutés
    devant le classeur habituel de l'app (gardé tel quel pour le Reporting)."""
    from openpyxl import load_workbook
    rows, points = rows_from_premasque_df(df, escale_ipaki, mode_transport)
    wb = load_workbook(io.BytesIO(xls_app_bytes))
    for ws in wb.worksheets:
        ws.sheet_properties.tabColor = "BFBFBF"
    if rows:
        add_verification_sheets(wb, rows, points, navire, voyage, None, index=0)
        wb.active = 0
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Règles apprises (PR B2) ───────────────────────────────────────────────────
# L'app branche ici un fournisseur de règles actives (regles_store.regles_actives) ;
# sans fournisseur (tests, scripts), aucune règle n'est appliquée.
_FOURNISSEUR_REGLES = None


def set_fournisseur_regles(fn) -> None:
    global _FOURNISSEUR_REGLES
    _FOURNISSEUR_REGLES = fn


def _norm(v) -> str:
    return re.sub(r"\s+", " ", str(v if v is not None else "")).strip().upper()


def appliquer_regles(rows, regles, points=None):
    """Applique des règles {niveau, colonne, chassis, valeur_app, valeur} aux lignes.
    Niveau 1/2 : colonne = valeur_app -> valeur ; niveau 3 : châssis précis.
    Chaque modification est signalée en point jaune. Renvoie (rows, ids utilisés)."""
    utilises = set()
    points = points if points is not None else []
    for rg in regles or []:
        col = rg.get("colonne") or rg.get("Colonne")
        if col not in COLUMNS:
            continue
        niveau = int(rg.get("niveau") or rg.get("Niveau") or 0)
        ch_rg = re.sub(r"[^A-Z0-9]", "", str(rg.get("chassis") or rg.get("Châssis") or "").upper())
        v_app = _norm(rg.get("valeur_app") if "valeur_app" in rg else rg.get("Si l'app donne"))
        val = rg.get("valeur") if "valeur" in rg else rg.get("Mettre")
        for i, r in enumerate(rows, start=1):
            if niveau == 3:
                ok = ch_rg and re.sub(r"[^A-Z0-9]", "", str(r["CHÂSSIS"]).upper()) == ch_rg
            else:
                ok = bool(v_app) and _norm(r[col]) == v_app
            if ok and _norm(r[col]) != _norm(val):
                ancien = r[col]
                r[col] = val
                if col == "POIDS IPAKI (TON)":
                    r["POIDS TETRAX (KG)"] = round(float(val) * 1000) if _num(val) is not None else ""
                if col == "MARQUE " or col == "MODELE":
                    r["MARQUE & MODELE"] = f"{r['MARQUE ']} {r['MODELE']}".strip()
                utilises.add(rg.get("id"))
                points.append({"ligne": i, "niveau": JAUNE, "colonne": col,
                               "texte": f"Règle apprise n° {rg.get('id', '?')} : « {ancien or '(vide)'} » → « {val} »."})
    utilises.discard(None)
    return rows, utilises


def _regles_du_fournisseur(rows, points):
    if _FOURNISSEUR_REGLES is None:
        return rows
    try:
        regles = _FOURNISSEUR_REGLES() or []
    except Exception:          # base indisponible : le pré-masque sort quand même, sans règles
        return rows
    rows, utilises = appliquer_regles(rows, regles, points)
    if utilises and hasattr(_FOURNISSEUR_REGLES, "compter"):
        try:
            _FOURNISSEUR_REGLES.compter(utilises)
        except Exception:
            pass
    return rows
