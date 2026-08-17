"""
Page Archives — historique complet et recherche des manifestes et des
Loading Reports déjà traités, avec accès (téléchargement) aux fichiers
conservés pour chaque traitement.
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
    "Retrouvez, recherchez et re-téléchargez tous les traitements archivés — "
    "manifestes structurés (PDF → Excel) et fichiers MASQUE / TYPE ISO générés."
)

tracking.clear_demo_data()

# ---------------------------------------------------------------------------
# Deux onglets : Manifestes (PDF→Excel) | Loading Reports (MASQUE + ISO)
# ---------------------------------------------------------------------------
tab_manifestes, tab_lr = st.tabs(["📦 Manifestes structurés", "📋 Loading Reports"])


# ============================================================================
# ONGLET 1 : Manifestes structurés
# ============================================================================
with tab_manifestes:

    with help_expander("ℹ️ Comment utiliser cet onglet ?"):
        st.markdown(
            """
- **Recherche** filtre sur le navire, le voyage, le nom de fichier et l'agent.
- **Statut** limite l'affichage aux manifestes vérifiés ou non.
- **Tri** permet d'ordonner la liste par date, navire, volume ou nombre de B/L.
- Cliquez sur une ligne du tableau pour ouvrir son détail : indicateurs
  complets, téléchargement du PDF source et de l'Excel structuré, et case à
  cocher pour marquer le manifeste comme vérifié.
- **Exporter cette sélection** télécharge en un clic la liste filtrée.
            """
        )

    df = tracking.read_log()

    if df.empty:
        st.info(
            "Aucun manifeste archivé pour le moment. Cette section se remplit "
            "automatiquement à chaque traitement effectué depuis la page "
            "**📦 Structuration des manifestes**."
        )
    else:
        st.divider()

        # ── Recherche et filtres ─────────────────────────────────────────────
        col_search, col_status, col_type = st.columns([2.2, 1.3, 1.7])
        with col_search:
            query = st.text_input(
                "🔍 Rechercher",
                placeholder="Navire, voyage, fichier, traité par…",
                help="Filtre sur le navire, le voyage, le nom du fichier et l'agent.",
                key="m_search",
            )
        with col_status:
            statut = st.segmented_control(
                "Statut", ["Tous", "✅ Vérifiés", "🕓 À vérifier"],
                default="Tous", required=True,
                help="Filtre les manifestes selon leur statut de vérification.",
                key="m_statut",
            )
        with col_type:
            types_dispo = sorted(t for t in df["type_cargo"].dropna().unique() if t and t != "—")
            types_filtre = st.multiselect(
                "Type de cargaison", types_dispo, placeholder="Tous les types",
                help="Filtre par catégorie de marchandise.",
                key="m_types",
            )

        # ── Tri configurable ─────────────────────────────────────────────────
        col_tri, col_ordre = st.columns([3, 1])
        with col_tri:
            tri_opts = {
                "Date (récent → ancien)":  ("horodatage", False),
                "Date (ancien → récent)":  ("horodatage", True),
                "Navire A → Z":            ("navire", True),
                "Navire Z → A":            ("navire", False),
                "Volume ↓":               ("volume_total", False),
                "Volume ↑":               ("volume_total", True),
                "B/L ↓":                  ("nb_bl", False),
                "B/L ↑":                  ("nb_bl", True),
            }
            tri_label = st.selectbox(
                "Trier par", list(tri_opts.keys()), index=0,
                key="m_tri",
                help="Ordre d'affichage des manifestes dans le tableau.",
            )
        # col_ordre non utilisé (intégré dans le libellé du tri pour la clarté)

        # ── Application des filtres ──────────────────────────────────────────
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

        # Tri
        sort_col, sort_asc = tri_opts[tri_label]
        if sort_col in dff.columns:
            dff = dff.sort_values(sort_col, ascending=sort_asc, na_position="last")

        st.caption(f"{len(dff)} manifeste(s) sur {len(df)} au total.")

        if dff.empty:
            st.warning("Aucun manifeste ne correspond à cette recherche.")
        else:
            # ── Export global ────────────────────────────────────────────────
            export_cols = dff[[
                "horodatage", "agent", "navire", "voyage", "type_cargo", "fichier",
                "nb_bl", "volume_total", "duree_traitement_sec", "verifie",
            ]].rename(columns={
                "horodatage": "Date", "agent": "Traité par", "navire": "Navire",
                "voyage": "Voyage", "type_cargo": "Type de cargaison",
                "fichier": "Fichier", "nb_bl": "B/L", "volume_total": "Volume",
                "duree_traitement_sec": "Durée (s)", "verifie": "Vérifié",
            })
            export_cols["Date"] = export_cols["Date"].dt.tz_localize(None)
            export_buf = BytesIO()
            export_cols.to_excel(export_buf, index=False, sheet_name="Archive")
            st.download_button(
                "⬇ Exporter cette sélection (.xlsx)", data=export_buf.getvalue(),
                file_name="archive_manifestes.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="m_export",
            )

            st.divider()

            # ── Tableau paginé ───────────────────────────────────────────────
            ROWS_PER_PAGE = 15
            dff = dff.reset_index(drop=True)
            total_pages = max(1, (len(dff) + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE)
            page = st.pagination(num_pages=total_pages, key="m_page") if total_pages > 1 else 1
            start = (page - 1) * ROWS_PER_PAGE
            page_df = dff.iloc[start:start + ROWS_PER_PAGE].reset_index(drop=True)

            display_df = page_df[[
                "horodatage", "navire", "voyage", "type_cargo", "agent", "nb_bl",
                "volume_total", "verifie",
            ]].rename(columns={
                "horodatage": "Date", "navire": "Navire", "voyage": "Voyage",
                "type_cargo": "Type", "agent": "Traité par",
                "nb_bl": "B/L", "volume_total": "Volume", "verifie": "Vérifié",
            })
            display_df["Vérifié"] = display_df["Vérifié"].map({True: "✅", False: "—"})

            st.caption("👉 Cliquez sur une ligne pour voir le détail et télécharger les fichiers.")
            event = st.dataframe(
                display_df, width='stretch', hide_index=True, key="m_table",
                on_select="rerun", selection_mode="single-row",
                column_config={"Date": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm")},
            )

            selected_rows = event.selection.rows if event and event.selection else []
            if selected_rows and selected_rows[0] < len(page_df):
                row = page_df.iloc[selected_rows[0]]

                @st.dialog(
                    f"{row['navire'] or 'Manifeste'} — {row['voyage'] or ''}",
                    width="medium", icon="📄",
                )
                def detail_dialog(row=row):
                    d1, d2, d3 = st.columns(3)
                    d1.metric("B/L", int(row["nb_bl"]))
                    d2.metric("Volume", int(row["volume_total"]))
                    d3.metric("Durée", format_duree(row["duree_traitement_sec"]))

                    st.caption(
                        f"Traité par **{row['agent']}** le "
                        f"{row['horodatage'].strftime('%d/%m/%Y à %H:%M')} "
                        f"— fichier `{row['fichier']}`."
                    )
                    if row.get("type_cargo") and row["type_cargo"] != "—":
                        st.caption(f"Type de cargaison : **{row['type_cargo']}**")

                    verifie_val = st.checkbox("Manifeste vérifié", value=bool(row["verifie"]))
                    if verifie_val != bool(row["verifie"]):
                        tracking.set_verifie(row["id"], verifie_val)
                        st.rerun()

                    st.divider()
                    export_path = tracking.archive_file_path(row["export_path"])
                    pdf_path    = tracking.archive_file_path(row["pdf_path"])

                    c1, c2 = st.columns(2)
                    with c1:
                        if export_path:
                            st.download_button(
                                "⬇ Excel structuré", data=export_path.read_bytes(),
                                file_name=(
                                    f"Manifeste_{row['navire']}_{row['voyage']}"
                                    .replace(" ", "_") + ".xlsx"
                                ),
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                width='stretch', key="m_dl_excel",
                            )
                        else:
                            st.caption("Aucun Excel archivé pour ce traitement.")
                    with c2:
                        if pdf_path:
                            st.download_button(
                                "⬇ PDF source", data=pdf_path.read_bytes(),
                                file_name=row["fichier"], mime="application/pdf",
                                width='stretch', key="m_dl_pdf",
                            )
                        else:
                            st.caption("Aucun PDF archivé pour ce traitement.")

                    st.divider()
                    with st.expander("🗑️ Supprimer ce manifeste de l'archive", expanded=False):
                        st.warning(
                            "Cette action est **irréversible** : la ligne est supprimée de "
                            "l'historique et les fichiers archivés (PDF + Excel) sont effacés du disque.",
                            icon="⚠️",
                        )
                        confirm = st.checkbox(
                            "Je confirme vouloir supprimer définitivement ce manifeste",
                            key="m_confirm_delete",
                        )
                        if st.button(
                            "Supprimer définitivement", type="primary",
                            disabled=not confirm, key="m_btn_delete",
                            icon="🗑️",
                        ):
                            tracking.delete_traitement(int(row["id"]))
                            st.success("Manifeste supprimé.")
                            st.rerun()

                detail_dialog()


# ============================================================================
# ONGLET 2 : Loading Reports (MASQUE TCS + TYPE ISO)
# ============================================================================
with tab_lr:

    with help_expander("ℹ️ Comment utiliser cet onglet ?"):
        st.markdown(
            """
- Retrouvez ici tous les fichiers **MASQUE TCS EXPORT** et **TYPE ISO** générés
  depuis la page *Génération MASQUE / TYPE ISO*.
- Utilisez **Rechercher** pour filtrer par navire, voyage, compte d'escale ou agent.
- Cliquez sur une ligne pour télécharger les fichiers ou supprimer l'entrée.
- Les fichiers sont archivés **au moment où vous cliquez sur Archiver** dans la page
  de génération — ils ne s'ajoutent pas automatiquement lors du téléchargement seul.
            """
        )

    df_lr = tracking.read_loading_reports()

    if df_lr.empty:
        st.info(
            "Aucun Loading Report archivé pour le moment. "
            "Cette section se remplit lorsque vous cliquez sur **📥 Archiver** "
            "depuis la page **📋 Génération MASQUE / TYPE ISO**."
        )
    else:
        st.divider()

        # ── Recherche et tri ─────────────────────────────────────────────────
        col_s, col_t = st.columns([3, 2])
        with col_s:
            lr_query = st.text_input(
                "🔍 Rechercher",
                placeholder="Navire, voyage, compte d'escale, agent…",
                key="lr_search",
            )
        with col_t:
            lr_tri_opts = {
                "Date (récent → ancien)": ("horodatage", False),
                "Date (ancien → récent)": ("horodatage", True),
                "Navire A → Z":           ("navire", True),
                "Navire Z → A":           ("navire", False),
                "Conteneurs ↓":           ("nb_conteneurs", False),
            }
            lr_tri = st.selectbox(
                "Trier par", list(lr_tri_opts.keys()), index=0, key="lr_tri"
            )

        dfl = df_lr.copy()
        if lr_query:
            q = lr_query.strip().lower()
            mask = (
                dfl["navire"].fillna("").str.lower().str.contains(q, regex=False)
                | dfl["voyage"].fillna("").str.lower().str.contains(q, regex=False)
                | dfl["compte_escale"].fillna("").str.lower().str.contains(q, regex=False)
                | dfl["agent"].fillna("").str.lower().str.contains(q, regex=False)
                | dfl["source_file"].fillna("").str.lower().str.contains(q, regex=False)
            )
            dfl = dfl[mask]

        lr_col, lr_asc = lr_tri_opts[lr_tri]
        if lr_col in dfl.columns:
            dfl = dfl.sort_values(lr_col, ascending=lr_asc, na_position="last")
        dfl = dfl.reset_index(drop=True)

        st.caption(f"{len(dfl)} Loading Report(s) sur {len(df_lr)} au total.")

        if dfl.empty:
            st.warning("Aucun Loading Report ne correspond à cette recherche.")
        else:
            # ── Tableau paginé ───────────────────────────────────────────────
            LR_PER_PAGE = 15
            total_pages_lr = max(1, (len(dfl) + LR_PER_PAGE - 1) // LR_PER_PAGE)
            page_lr = (
                st.pagination(num_pages=total_pages_lr, key="lr_page")
                if total_pages_lr > 1 else 1
            )
            start_lr = (page_lr - 1) * LR_PER_PAGE
            page_lr_df = dfl.iloc[start_lr:start_lr + LR_PER_PAGE].reset_index(drop=True)

            display_lr = page_lr_df[[
                "horodatage", "navire", "voyage", "compte_escale",
                "nb_conteneurs", "agent", "source_file",
            ]].rename(columns={
                "horodatage":    "Date",
                "navire":        "Navire",
                "voyage":        "Voyage",
                "compte_escale": "Compte escale",
                "nb_conteneurs": "Conteneurs",
                "agent":         "Généré par",
                "source_file":   "Fichier source",
            })

            st.caption("👉 Cliquez sur une ligne pour télécharger MASQUE TCS et TYPE ISO.")
            event_lr = st.dataframe(
                display_lr, width='stretch', hide_index=True, key="lr_table",
                on_select="rerun", selection_mode="single-row",
                column_config={
                    "Date": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
                    "Conteneurs": st.column_config.NumberColumn(width="small"),
                },
            )

            selected_lr = event_lr.selection.rows if event_lr and event_lr.selection else []
            if selected_lr and selected_lr[0] < len(page_lr_df):
                row_lr = page_lr_df.iloc[selected_lr[0]]

                @st.dialog(
                    f"{row_lr['navire'] or 'Loading Report'} — {row_lr['voyage'] or ''}",
                    width="medium", icon="📋",
                )
                def lr_detail_dialog(row=row_lr):
                    d1, d2 = st.columns(2)
                    d1.metric("Conteneurs", int(row["nb_conteneurs"]))
                    d2.metric("Compte d'escale", row["compte_escale"] or "—")

                    st.caption(
                        f"Généré par **{row['agent']}** le "
                        f"{row['horodatage'].strftime('%d/%m/%Y à %H:%M')}"
                        + (f" — fichier source `{row['source_file']}`" if row.get("source_file") else "")
                    )

                    st.divider()
                    masque_path = tracking.archive_file_path(row["masque_path"])
                    iso_path    = tracking.archive_file_path(row["iso_path"])

                    navire_safe = (row["navire"] or "NAVIRE").replace(" ", "_")
                    voyage_safe = (row["voyage"] or "VOY").replace(" ", "_")

                    c1, c2 = st.columns(2)
                    with c1:
                        if masque_path:
                            st.download_button(
                                "⬇ MASQUE TCS EXPORT",
                                data=masque_path.read_bytes(),
                                file_name=f"MASQUE_TCS_EXPORT_{navire_safe}_{voyage_safe}.csv",
                                mime="text/csv",
                                width='stretch', key="lr_dl_masque",
                                type="primary",
                            )
                        else:
                            st.caption("Fichier MASQUE TCS non trouvé sur le disque.")
                    with c2:
                        if iso_path:
                            st.download_button(
                                "⬇ TYPE ISO",
                                data=iso_path.read_bytes(),
                                file_name=f"TYPE_ISO_{navire_safe}_{voyage_safe}.csv",
                                mime="text/csv",
                                width='stretch', key="lr_dl_iso",
                            )
                        else:
                            st.caption("Fichier TYPE ISO non trouvé sur le disque.")

                    st.divider()
                    with st.expander("🗑️ Supprimer ce Loading Report de l'archive", expanded=False):
                        st.warning(
                            "Cette action est **irréversible** : la ligne est supprimée de "
                            "l'historique et les fichiers CSV archivés sont effacés du disque.",
                            icon="⚠️",
                        )
                        confirm_lr = st.checkbox(
                            "Je confirme vouloir supprimer définitivement ce Loading Report",
                            key="lr_confirm_delete",
                        )
                        if st.button(
                            "Supprimer définitivement", type="primary",
                            disabled=not confirm_lr, key="lr_btn_delete",
                            icon="🗑️",
                        ):
                            tracking.delete_loading_report(int(row["id"]))
                            st.success("Loading Report supprimé.")
                            st.rerun()

                lr_detail_dialog()
