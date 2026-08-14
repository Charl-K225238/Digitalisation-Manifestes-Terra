"""Éléments d'interface partagés (style, aide) entre les pages de l'application.

Palette et typographie alignées sur un usage BI/corporate (Segoe UI), avec des
couleurs validées pour la lisibilité (contraste, distinction daltonisme).
"""
import pandas as pd
import streamlit as st

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


def format_duree(sec):
    """Formate une durée en secondes de façon lisible, y compris pour les
    traitements quasi instantanés (extraction déterministe, souvent < 1s).
    Partagé entre le tableau de bord et l'archive pour un affichage cohérent."""
    if pd.isna(sec):
        return "—"
    if sec < 10:
        return f"{sec:.1f} s"
    return f"{sec:.0f} s"
