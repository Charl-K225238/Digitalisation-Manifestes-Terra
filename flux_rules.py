"""Règles uniques de classification d'un B/L : Import, Transbordement, Hinterland.

Deux notions DISTINCTES (le classeur Stats Flash les sépare aussi : colonnes
« DT VEH TRANSIT » et « TBT ») :

* TRANSBORDEMENT (« Transbo ») : la marchandise est déchargée à Abidjan puis
  rechargée sur un autre navire vers un port étranger. Signal fiable côté
  manifeste : le champ « Place of Delivery » est renseigné ET situé hors
  Côte d'Ivoire. Champ vide ou livraison à Abidjan => jamais un transbordement.
  Le marqueur « [T] » collé au n° de B/L ne suffit pas (vu sur des B/L livrés à
  Abidjan : consignataires SOCIDA, MANUCHAR CI...).

* HINTERLAND : la marchandise reste un Import déchargé à Abidjan, puis part par
  la route vers un pays enclavé (Mali, Burkina Faso, Niger). C'est le PAYS de
  destination qui décide, jamais le mot « transshipment » du texte : les
  manifestes chinois écrivent « CARGO TRANSSHIPMENT FROM ABIDJAN TO MALI » pour
  un transit routier.

Un B/L Hinterland a donc Nature = Import et un pays de transit renseigné.
"""
import re

HINTERLAND_COUNTRIES = ("Mali", "Burkina Faso", "Niger")

# \bNIGER\b ne matche pas « NIGERIA » (pas de frontière de mot après « NIGER »).
_HINTERLAND_PATTERNS = [
    (re.compile(r"\bMALI\b|BAMAKO|KALABAN", re.I), "Mali"),
    (re.compile(r"BURKIN\w*|OUAGADOUGOU|BOBO[- ]?DIOULASSO", re.I), "Burkina Faso"),
    (re.compile(r"\bNIGER\b|NIAMEY", re.I), "Niger"),
]

# Lieux ivoiriens (pays ou villes principales) : une livraison ici n'est PAS
# un transbordement. « CI » seul est volontairement absent (trop de faux positifs).
_IVORIAN_RE = re.compile(
    r"ABIDJAN|IVORY\s*COAST|COTE\s*D.?\s*IVOIRE|C.TE\s*D.?\s*IVOIRE|"
    r"BOUAK|YAMOUSSOUKRO|SAN[- ]?PEDRO|DALOA|KORHOGO|MAN\b|GAGNOA|ABENGOUROU|"
    r"DIVO|SOUBRE|ODIENNE|BONDOUKOU|FERKESSEDOUGOU|GRAND[- ]?BASSAM|"
    r"BINGERVILLE|ANYAMA|YOPOUGON|COCODY|TREICHVILLE|MARCORY|KOUMASSI",
    re.I)


def is_ivorian(text) -> bool:
    return bool(_IVORIAN_RE.search(str(text or "")))


def hinterland_country(text) -> str:
    """Pays enclavé (Mali, Burkina Faso, Niger) cité dans le texte, sinon ""."""
    t = str(text or "")
    for pat, name in _HINTERLAND_PATTERNS:
        if pat.search(t):
            return name
    return ""


def is_transbo_place(place_of_delivery) -> bool:
    """Vrai seulement si Place of Delivery est renseigné ET hors Côte d'Ivoire."""
    p = re.sub(r"[\s,.\-]+", " ", str(place_of_delivery or "")).strip()
    if not p or p.upper() in ("NAN", "NONE"):
        return False
    return not is_ivorian(p)


def nature_from_place_of_delivery(place_of_delivery) -> str:
    """Nature du B/L pour les manifestes qui portent « Place of Delivery »
    (Grimaldi, MOL) : "Transb." (libellé historique de l'app) ou "Import"."""
    return "Transb." if is_transbo_place(place_of_delivery) else "Import"


def nature_from_destination(dest_text):
    """Pour les formats sans « Place of Delivery » (manifestes chinois RoRo) :
    déduit la nature de la destination finale citée dans la description.
    Retourne (nature, a_verifier).

    * vide ou ivoirienne                -> Import
    * pays enclavé (Mali, BF, Niger)    -> Import (Hinterland, routier)
    * autre pays étranger               -> Transbo, à vérifier (mer supposée :
                                           aucun champ ne le confirme)
    """
    d = re.sub(r"\s+", " ", str(dest_text or "")).strip()
    # « LIBERIA FROM ABIDJAN » : la destination est ce qui précède « FROM ».
    d = re.split(r"\s+FROM\s+", d, maxsplit=1, flags=re.I)[0]
    if not d or is_ivorian(d):
        return "Import", False
    if hinterland_country(d):
        return "Import", False
    return "Transbo", True
