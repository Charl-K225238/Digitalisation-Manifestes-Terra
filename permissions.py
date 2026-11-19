"""
Catalogue des fonctionnalités attribuables à un groupe (espace Administration).

Source unique des droits de l'app :
- en mode « comptes » (secret CONNEXION_PAR_COMPTE = true), chaque utilisateur
  hérite des fonctionnalités cochées pour son groupe (table manifestes_groupes) ;
- en mode historique (mot de passe commun), les trois rôles d'accès
  agent / analyste / direction sont traduits dans ces mêmes codes
  (LEGACY_ROLE_PERMS), pour que les pages n'aient qu'UN seul contrôle :
  ui_helpers.has_perm(code).

Toujours accessibles, sans case à cocher : Vue d'ensemble (version simple),
Profil, Avis & retours (lecture et dépôt de messages).

Ajouter une fonctionnalité = ajouter une ligne ici + un has_perm() dans la page.
Ne jamais renommer un code existant : il est stocké en base dans les groupes.
"""

CATALOGUE: list[tuple[str, list[tuple[str, str]]]] = [
    ("Saisie", [
        ("saisie.premasque", "Pré-Masque"),
        ("saisie.fiche", "Fiche de dépouillement"),
        ("saisie.masque_iso", "MASQUE / TYPE ISO"),
        ("saisie.bl_importer", "BL Importer"),
        ("saisie.reporting", "Liste prévisionnelle / Tableau de classification"),
    ]),
    ("Rapports", [
        ("rapports.stats_flash", "Stats Flash : consulter"),
        ("rapports.stats_flash_modifier", "Stats Flash : charger et corriger"),
        ("rapports.note_volumes", "Note volumes mensuels"),
    ]),
    ("Données", [
        ("donnees.archives", "Archives : consulter et retélécharger"),
        ("donnees.archives_sources", "Archives : fichiers sources Stats Flash"),
    ]),
    ("Pilotage", [
        ("pilotage.vue_ensemble", "Vue d'ensemble : indicateurs de pilotage"),
        ("pilotage.activite", "Activité du terminal"),
        ("pilotage.dashboard", "Tableau de bord"),
    ]),
    ("Avis & retours", [
        ("avis.statut", "Changer le statut des demandes"),
    ]),
    ("Administration", [
        ("admin.comptes", "Gérer les groupes et les utilisateurs"),
    ]),
]

ALL_CODES: tuple[str, ...] = tuple(code for _, items in CATALOGUE for code, _ in items)
LABELS: dict[str, str] = {code: label for _, items in CATALOGUE for code, label in items}
ADMIN_PERM = "admin.comptes"

_SAISIE = {c for c in ALL_CODES if c.startswith("saisie.")}
_AGENT = _SAISIE | {"donnees.archives"}
_DIRECTION = _AGENT | {"rapports.stats_flash", "rapports.note_volumes",
                       "pilotage.vue_ensemble", "pilotage.activite", "pilotage.dashboard"}
_ANALYSTE = set(ALL_CODES)

# Mode historique : rôle d'accès -> fonctionnalités (comportement identique à avant).
LEGACY_ROLE_PERMS: dict[str, frozenset] = {
    "agent": frozenset(_AGENT),
    "direction": frozenset(_DIRECTION),
    "analyste": frozenset(_ANALYSTE - {ADMIN_PERM}),   # page Administration = mode comptes uniquement
}

# Groupes créés automatiquement au premier démarrage en mode comptes
# (reprise à l'identique des accès actuels ; modifiables ensuite par l'IT).
GROUPES_INITIAUX: list[tuple[str, str, frozenset]] = [
    ("Agent", "Saisie quotidienne et archives", frozenset(_AGENT)),
    ("Direction", "Saisie, rapports et pilotage en consultation", frozenset(_DIRECTION)),
    ("Analyste Data", "Accès complet, y compris l'administration", frozenset(_ANALYSTE)),
    ("Administrateur IT", "Gestion des groupes et des utilisateurs uniquement", frozenset({ADMIN_PERM})),
]


def clean(codes) -> list[str]:
    """Codes connus uniquement, dans l'ordre du catalogue (ignore les codes retirés)."""
    s = set(codes or ())
    return [c for c in ALL_CODES if c in s]
