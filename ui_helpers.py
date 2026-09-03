"""Éléments d'interface partagés (style, aide, contrôle d'accès) entre les
pages de l'application.

Palette et typographie alignées sur un usage BI/corporate (Segoe UI), avec des
couleurs validées pour la lisibilité (contraste, distinction daltonisme).
"""
import pandas as pd
import streamlit as st

# Version affichée en indicatif dans l'app (sidebar) — à incrémenter à
# chaque livraison fonctionnelle notable, sert aussi de traçabilité pour le
# triage des avis (voir tracking.save_avis -> version_app).
APP_VERSION = "7.4.0"

# Palette catégorielle (ordre fixe — ne jamais réordonner selon les filtres)
PALETTE = {
    "blue": "#2a78d6",
    "orange": "#eb6834",
    "aqua": "#1baf7a",
    "yellow": "#eda100",
    "magenta": "#e87ba4",
    "green": "#008300",
    "violet": "#4a3aa7",
    "red": "#e34948",
}
CATEGORICAL_SEQUENCE = [PALETTE["blue"], PALETTE["orange"], PALETTE["aqua"],
                         PALETTE["yellow"], PALETTE["magenta"], PALETTE["violet"]]

# Rampe séquentielle (une seule teinte, pour les grandeurs/classements)
SEQUENTIAL_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#2a78d6", "#184f95"]

STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}

FONT_FAMILY = "Segoe UI, -apple-system, BlinkMacSystemFont, sans-serif"

CSS = f"""
<style>
html, body, [class*="css"], [data-testid="stAppViewContainer"] {{
    font-family: {FONT_FAMILY};
}}
div[data-testid="stMetric"] {{
    background: #ffffff;
    border: 1px solid rgba(11,11,11,0.08);
    border-radius: 10px;
    padding: 14px 16px 10px 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    min-width: 0;
    height: auto !important;
}}
div[data-testid="stMetric"] * {{
    min-width: 0;
}}
div[data-testid="stMetricLabel"], div[data-testid="stMetricLabel"] *,
div[data-testid="stMetricValue"], div[data-testid="stMetricValue"] *,
div[data-testid="stMetricDelta"], div[data-testid="stMetricDelta"] * {{
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: unset !important;
    height: auto !important;
}}
div[data-testid="stMetricLabel"] {{
    font-size: 0.8rem;
    color: #52514e;
}}
div[data-testid="stMetricValue"] {{
    font-size: 1.6rem;
    line-height: 1.2;
}}
div[data-testid="stMetricDelta"] {{
    font-size: 0.8rem;
}}
[data-testid="stSidebarNav"] li div a {{
    font-size: 0.95rem;
}}
.stTabs [data-baseweb="tab"] {{
    font-weight: 600;
}}
div[data-testid="stExpander"] details summary p {{
    font-weight: 600;
}}
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def help_expander(title):
    """Bloc d'aide repliable, discret par défaut, avec des indications concrètes."""
    return st.expander(title, expanded=False)


def combo_with_custom(label, options, default_value="", key="combo",
                       custom_label="✏️ Autre (préciser)…", help=None):
    """Sélecteur "liste + saisie libre" : une liste déroulante alimentée par
    les valeurs déjà connues, plus un choix "Autre" qui révèle un champ texte.

    Permet à l'utilisateur d'utiliser une valeur existante EN UN CLIC, ou d'en
    saisir une nouvelle librement sans être bloqué par une liste figée — toute
    valeur personnalisée saisie une fois devient ensuite une suggestion pour
    les autres (voir tracking.get_known_services/get_known_roles). Retourne la
    valeur finale choisie ou saisie (str, espaces superflus retirés)."""
    opts = list(dict.fromkeys(o for o in options if o))  # dédoublonne, garde l'ordre
    full_opts = opts + [custom_label]
    if default_value and default_value in opts:
        default_idx = full_opts.index(default_value)
    elif default_value:
        default_idx = len(full_opts) - 1  # valeur inconnue -> "Autre", pré-remplie
    else:
        default_idx = 0
    choice = st.selectbox(label, full_opts, index=default_idx, key=f"{key}_select", help=help)
    if choice == custom_label:
        prefill = default_value if default_value not in opts else ""
        return st.text_input(
            f"Préciser « {label} »", value=prefill, key=f"{key}_custom",
        ).strip()
    return choice


def format_duree(sec):
    """Formate une durée en secondes de façon lisible, y compris pour les
    traitements quasi instantanés (extraction déterministe, souvent < 1s).
    Partagé entre le tableau de bord et l'archive pour un affichage cohérent."""
    if pd.isna(sec):
        return "—"
    if sec < 10:
        return f"{sec:.1f} s"
    return f"{sec:.0f} s"


# ---------------------------------------------------------------------------
# Contrôle d'accès par rôle — voir tracking.get_access_role/ACCESS_ROLES.
# Rôles : "agent" (défaut — pages de saisie uniquement), "analyste" (accès
# total + gestion des comptes), "direction" (tableau de bord + classification
# véhicules en lecture). Un rôle élevé nécessite un compte protégé par mot de
# passe personnel (voir views/profil.py) — sans ça, il reste "agent".
# ---------------------------------------------------------------------------
ACCESS_ROLE_LABELS = {
    "agent": "Agent",
    "analyste": "Analyste Data",
    "direction": "Direction",
}


def current_identity() -> dict | None:
    """Identité (nom/service/rôle métier) de la personne actuellement
    identifiée sur ce poste, ou None si personne ne s'est identifiée."""
    return st.session_state.get("identity")


def current_access_role() -> str:
    """Rôle d'ACCÈS (permissions) de la personne actuellement identifiée :
    "agent" si personne n'est identifiée. Mis en cache dans la session pour
    éviter une requête Supabase à chaque rerun Streamlit — le cache est
    invalidé automatiquement dès que le nom identifié change, et peut être
    forcé via invalidate_access_role_cache() après une promotion/modification
    de mot de passe pour la personne elle-même."""
    identity = st.session_state.get("identity")
    if not identity or not identity.get("name"):
        return "agent"
    cache = st.session_state.get("_access_role_cache")
    if cache and cache.get("name") == identity["name"]:
        return cache["role"]
    from tracking import get_access_role  # import différé — évite un cycle au chargement du module
    role = get_access_role(identity["name"])
    st.session_state["_access_role_cache"] = {"name": identity["name"], "role": role}
    return role


def invalidate_access_role_cache() -> None:
    """À appeler après un changement de mot de passe personnel ou de rôle
    d'accès (le sien ou celui d'un autre compte via la gestion des accès),
    pour que le prochain appel à current_access_role() relise Supabase."""
    st.session_state.pop("_access_role_cache", None)
