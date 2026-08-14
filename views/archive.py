"""
Page Archives — historique complet et recherche des manifestes déjà traités,
avec accès (téléchargement) au PDF source et à l'Excel structuré conservés
pour chaque traitement.
"""
import pathlib
import sys
from io import BytesIO

import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import tracking
from ui_helpers import help_expander, format_duree

st.title("🗂️ Archives")
st.caption(
    "Retrouvez, recherchez et re-téléchargez tous les manifestes déjà traités — "
    "le PDF source et l'Excel structuré sont conservés pour chaque traitement."
)

with help_expander("ℹ️ Comment utiliser cette page ?"):
    st.markdown(
        """
- **Recherche** filtre sur le navire, le voyage, le nom de fichier et la
  personne ayant traité le manifeste.
- **Statut** limite l'affichage aux manifestes déjà vérifiés ou non.
- Cliquez sur une ligne du tableau pour ouvrir son détail : indicateurs
  complets, téléchargement du PDF source et de l'Excel structuré, et case à
  cocher pour marquer le manifeste comme vérifié.
- **Exporter cette sélection** télécharge en un clic la liste filtrée (utile
  pour un point hebdo/mensuel).
        """
    )

tracking.clear_demo_data()
df = tracking.read_log()

if df.empty:
    st.info(
        "Aucun manifeste archivé pour le moment. Cette page se remplit "
        "automatiquement à chaque traitement effectué depuis la page "
        "**📦 Structuration des manifestes**."
    )
    st.stop()

st.divider()

# ---------------------------------------------------------------------------
# Recherche et filtres
# ---------------------------------------------------------------------------
col_search, col_status, col_type = st.columns([2.2, 1.3, 1.7])
with col_search:
    query = st.text_input(
        "🔍 Rechercher", placeholder="Navire, voyage, fichier, traité par…",
        help="Filtre sur le navire, le voyage, le nom du fichier et la personne ayant traité le manifeste.",
    )
with col_status:
    statut = st.segmented_control(
        "Statut", ["Tous", "✅ Vérifiés", "🕓 À vérifier"],
        default="Tous", required=True,
        help="Filtre les manifestes selon qu'ils ont été relus et validés ou non.",
    )
with col_type:
    types_dispo = sorted(t for t in df["type_cargo"].dropna().unique() if t and t != "—")
    types_filtre = st.multiselect(
        "Type de cargaison", types_dispo, placeholder="Tous les types",
        help="Filtre les manifestes selon les catégories de marchandise qu'ils contiennent "
        "(véhicules uniquement, mixte, etc.). Laissez vide pour tout inclure.",
    )

dff = df.copy()
if query:
    q = query.strip().lower()
    mask = (
        dff["navire"].fillna("").str.lower().str.contains(q, regex=False)
        | dff["voyage"].fillna("").str.lower().str.contains(q, regex=False)
        | dff["fichier"].fillna("").str.lower().str.contains(q, regex=False)
        | dff["agent"].fillna("").str.lower().str.contains(q, regex=False)
    )
    dff = dff[mask]

if statut == "✅ Vérifiés":
    dff = dff[dff["verifie"]]
elif statut == "🕓 À vérifier":
    dff = dff[~dff["verifie"]]

if types_filtre:
    dff = dff[dff["type_cargo"].isin(types_filtre)]

st.caption(f"{len(dff)} manifeste(s) sur {len(df)} au total.")

if dff.empty:
    st.warning("Aucun manifeste ne correspond à cette recherche.")
    st.stop()

# ---------------------------------------------------------------------------
# Export global de la sélection filtrée
# ---------------------------------------------------------------------------
export_cols = dff[[
    "horodatage", "agent", "navire", "voyage", "type_cargo", "fichier", "nb_bl", "volume_total",
    "duree_traitement_sec", "verifie",
]].rename(columns={
    "horodatage": "Date", "agent": "Traité par", "navire": "Navire", "voyage": "Voyage",
    "type_cargo": "Type de cargaison", "fichier": "Fichier", "nb_bl": "B/L", "volume_total": "Volume",
    "duree_traitement_sec": "Durée (s)", "verifie": "Vérifié",
})
# Excel ne supporte pas les datetimes avec fuseau horaire — on retire le tz
# (les horodatages sont enregistrés en UTC, l'info reste implicite).
export_cols["Date"] = export_cols["Date"].dt.tz_localize(None)
export_buf = BytesIO()
export_cols.to_excel(export_buf, index=False, sheet_name="Archive")
st.download_button(
    "⬇ Exporter cette sélection (.xlsx)", data=export_buf.getvalue(),
    file_name="archive_manifestes.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

st.divider()

# ---------------------------------------------------------------------------
# Tableau paginé — cliquer une ligne ouvre le détail
# ---------------------------------------------------------------------------
ROWS_PER_PAGE = 15
total_pages = max(1, (len(dff) + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE)
page = st.pagination(num_pages=total_pages, key="archive_page") if total_pages > 1 else 1
start = (page - 1) * ROWS_PER_PAGE
page_df = dff.iloc[start:start + ROWS_PER_PAGE].reset_index(drop=True)

display_df = page_df[
    ["horodatage", "navire", "voyage", "type_cargo", "agent", "nb_bl", "volume_total", "verifie"]
].rename(
    columns={
        "horodatage": "Date", "navire": "Navire", "voyage": "Voyage", "type_cargo": "Type",
        "agent": "Traité par", "nb_bl": "B/L", "volume_total": "Volume", "verifie": "Vérifié",
    }
)
display_df["Vérifié"] = display_df["Vérifié"].map({True: "✅", False: "—"})

st.caption("👉 Cliquez sur une ligne pour voir le détail et télécharger les fichiers.")
event = st.dataframe(
    display_df, width='stretch', hide_index=True, key="archive_table",
    on_select="rerun", selection_mode="single-row",
    column_config={"Date": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm")},
)

selected_rows = event.selection.rows if event and event.selection else []
if selected_rows:
    row = page_df.iloc[selected_rows[0]]

    @st.dialog(f"{row['navire'] or 'Manifeste'} — {row['voyage'] or ''}", width="medium", icon="📄")
    def detail_dialog(row=row):
        d1, d2, d3 = st.columns(3)
        d1.metric("B/L", int(row["nb_bl"]))
        d2.metric("Volume", int(row["volume_total"]))
        d3.metric("Durée", format_duree(row["duree_traitement_sec"]))

        st.caption(
            f"Traité par **{row['agent']}** le "
            f"{row['horodatage'].strftime('%d/%m/%Y à %H:%M')} — fichier `{row['fichier']}`."
        )
        if row.get("type_cargo") and row["type_cargo"] != "—":
            st.caption(f"Type de cargaison : **{row['type_cargo']}**")

        verifie_val = st.checkbox("Manifeste vérifié", value=bool(row["verifie"]))
        if verifie_val != bool(row["verifie"]):
            tracking.set_verifie(row["id"], verifie_val)
            st.rerun()

        st.divider()
        export_path = tracking.archive_file_path(row["export_path"])
        pdf_path = tracking.archive_file_path(row["pdf_path"])

        c1, c2 = st.columns(2)
        with c1:
            if export_path:
                st.download_button(
                    "⬇ Excel structuré", data=export_path.read_bytes(),
                    file_name=f"Manifeste_{row['navire']}_{row['voyage']}".replace(" ", "_") + ".xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width='stretch', key="dl_excel",
                )
            else:
                st.caption("Aucun Excel archivé pour ce traitement.")
        with c2:
            if pdf_path:
                st.download_button(
                    "⬇ PDF source", data=pdf_path.read_bytes(),
                    file_name=row["fichier"], mime="application/pdf",
                    width='stretch', key="dl_pdf",
                )
            else:
                st.caption("Aucun PDF archivé pour ce traitement.")

    detail_dialog()
