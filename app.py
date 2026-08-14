"""
Point d'entrée de l'application — navigation entre les pages.

Lancement inchangé :
    streamlit run app.py
"""
import streamlit as st

from ui_helpers import inject_css

st.set_page_config(page_title="Manifestes Grimaldi", page_icon="📦", layout="wide")
inject_css()

structuration_page = st.Page(
    "views/structuration.py",
    title="Structuration des manifestes",
    icon="📦",
    default=True,
)
dashboard_page = st.Page(
    "views/dashboard.py",
    title="Tableau de bord",
    icon="📊",
)
archive_page = st.Page(
    "views/archive.py",
    title="Archives",
    icon="🗂️",
)
avis_page = st.Page(
    "views/avis.py",
    title="Avis & Retours",
    icon="💬",
)

pg = st.navigation([structuration_page, dashboard_page, archive_page, avis_page])
pg.run()
