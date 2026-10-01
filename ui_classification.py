"""
Générateur de tableau de classification des véhicules (POL x tranche de volume).

Composant UI partagé : utilisé par Reporting (sous-onglet Classification) et
MASQUE / TYPE ISO (section 5). `prefix` isole les clés session_state/widgets
de chaque page. Logique métier : classification_vehicules.py (inchangée).
"""
import pandas as pd
import streamlit as st

import classification_vehicules as clsveh
from ui_helpers import help_expander


def render_classification(prefix: str = "cls_veh"):
    st.caption(
        "Tableau de classification des véhicules par port de chargement (POL) et "
        "tranche de volume — recalculé depuis le(s) manifeste(s) bruts uploadés, à la "
        "place du fichier manuel à ~150 onglets."
    )

    with help_expander("ℹ️ Comment utiliser cet onglet"):
        st.markdown(
            "1. **Uploadez le(s) manifeste(s) bruts** (PDF ou XLSX), puis cliquez sur "
            "« Générer la classification ». Le format est détecté automatiquement par "
            "fichier, et le navire, le voyage, ainsi que le port de chargement (POL) de "
            "chaque véhicule sont repris directement du manifeste — aucune sélection "
            "préalable n'est nécessaire. Un résumé (POL en lignes, tranches de volume en "
            "colonnes, nombre + poids cumulés en kg + colonne NEW VEH) s'affiche.\n"
            "2. Le fichier Excel téléchargé va plus loin : détail par POL avec "
            "sous-total puis total général — même mise en page que le fichier de "
            "référence."
        )

    # -------------------------------------------------------------------
    # Le navire/voyage affichés dans le tableau et le nom du fichier
    # Excel sont ceux détectés automatiquement dans le(s) manifeste(s)
    # uploadé(s) ci-dessous — aucune sélection préalable n'est requise.
    # Bug UX corrigé (28/09) : l'upload était auparavant bloqué tant
    # qu'aucun Navire/Voyage n'avait déjà été traité côté Pré-Masque
    # (uploader caché dans le "else" du if voyages_cls.empty), ce qui
    # rendait l'onglet inutilisable au premier lancement et obligeait à
    # traiter un manifeste ailleurs avant de pouvoir s'en servir ici.
    # -------------------------------------------------------------------
    st.subheader("1. Manifeste(s) bruts")
    st.caption(
        "Formats reconnus automatiquement : Chinese RoRo (XLSX), MOL ALIS, Grimaldi et "
        "Hyundai Glovis (PDF, y compris scanné). Les manifestes scannés (Hyundai Glovis) "
        "prennent plus de temps à traiter — une barre de progression s'affiche."
    )

    # Compteur pour forcer le reset du file_uploader (changer la key le vide)
    if f"{prefix}_uploader_seq" not in st.session_state:
        st.session_state[f"{prefix}_uploader_seq"] = 0
    uploader_key = f"{prefix}_upload_{st.session_state[f'{prefix}_uploader_seq']}"

    cls_files = st.file_uploader(
        "Manifeste(s) bruts pour la classification (PDF ou XLSX)",
        type=["pdf", "xlsx", "xls"],
        accept_multiple_files=True,
        key=uploader_key,
        help="Un ou plusieurs manifestes du même Navire/Voyage (un par port de chargement si besoin). "
             "Format détecté automatiquement (Chinese RoRo / MOL ALIS / Grimaldi / Hyundai Glovis scanné).",
    )

    # Boutons Générer / Réinitialiser côte à côte
    col_gen, col_reset = st.columns([3, 1])
    do_generate = cls_files and col_gen.button(
        "🔄 Générer la classification", type="primary", key=f"{prefix}_generate"
    )
    has_results = st.session_state.get(f"{prefix}_entries") is not None
    if (cls_files or has_results) and col_reset.button(
        "🗑️ Réinitialiser", key=f"{prefix}_reset"
    ):
        for k in (f"{prefix}_entries", f"{prefix}_ship", f"{prefix}_voy",
                   f"{prefix}_unreadable"):
            st.session_state.pop(k, None)
        st.session_state[f"{prefix}_uploader_seq"] += 1
        st.rerun()

    if do_generate:
        all_entries = []
        ship_name_detected, voyage_detected = "", ""
        unreadable = []
        progress_bar = st.progress(0.0)
        status = st.empty()
        n_files = len(cls_files)
        for fi, f in enumerate(cls_files):
            status.caption(f"Traitement de « {f.name} » ({fi + 1}/{n_files})…")

            def _cb(page_cur, page_total, _fi=fi, _fname=f.name):
                frac = (_fi + page_cur / max(page_total, 1)) / n_files
                progress_bar.progress(min(frac, 1.0))
                status.caption(f"Traitement de « {_fname} » — page {page_cur}/{page_total}…")

            entries, meta, fmt = clsveh.parse_manifest_bytes(f.name, f.getvalue(), progress_cb=_cb)
            progress_bar.progress((fi + 1) / n_files)
            if fmt == "unknown" or not entries:
                unreadable.append(f.name)
                continue
            all_entries.extend(entries)
            if not ship_name_detected and meta.get("ship_name"):
                ship_name_detected = meta["ship_name"]
            if not voyage_detected and meta.get("voyage"):
                voyage_detected = meta["voyage"]
        status.empty()
        progress_bar.empty()
        st.session_state[f"{prefix}_entries"] = all_entries
        st.session_state[f"{prefix}_ship"] = ship_name_detected or "NAVIRE"
        st.session_state[f"{prefix}_voy"] = voyage_detected or "VOYAGE"
        st.session_state[f"{prefix}_unreadable"] = unreadable

    cls_entries = st.session_state.get(f"{prefix}_entries")
    if cls_entries is not None:
        if st.session_state.get(f"{prefix}_unreadable"):
            st.warning(
                "Format non reconnu ou aucun véhicule trouvé, fichier(s) ignoré(s) : "
                + ", ".join(st.session_state[f"{prefix}_unreadable"])
            )

        diag = clsveh.classification_diag(cls_entries)
        if diag["total_vehicules"] == 0:
            st.warning("Aucun véhicule extrait des manifestes uploadés.")
        else:
            st.divider()
            st.subheader("2. Tableau de classification (POL x tranche de volume)")
            ship_lbl = st.session_state.get(f"{prefix}_ship", "NAVIRE")
            voy_lbl = st.session_state.get(f"{prefix}_voy", "VOYAGE")
            st.caption(f"Navire/Voyage détecté(s) automatiquement : **{ship_lbl} / {voy_lbl}**")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Véhicules (total)", diag["total_vehicules"])
            m2.metric("Dont neufs (NEW VEH)", diag["neufs"])
            m3.metric("B/L / entrées retenues", diag["nb_bl"])
            m4.metric("Sans tranche exploitable", diag["sans_tranche"],
                      help="Ni volume ni poids exploitable dans le manifeste — exclus du "
                           "tableau ci-dessous mais toujours comptés ici, jamais supprimés "
                           "silencieusement.")

            pivot_df = clsveh.entries_to_pivot_df(cls_entries)
            if pivot_df.empty:
                st.caption("Aucune ligne classifiable.")
            else:
                display_df = pivot_df.set_index("POL")

                def _hl_total(row):
                    is_total = row.name == "TOTAL"
                    return ["background-color: #1F4E78; color: white; font-weight: bold;" if is_total else ""] * len(row)

                fmt_map = {}
                for c in display_df.columns:
                    if "VOLUME" in c:
                        fmt_map[c] = "{:,.2f}"
                    else:
                        fmt_map[c] = "{:,.0f}"

                styled = display_df.style.format(fmt_map, na_rep="—").apply(_hl_total, axis=1)
                st.markdown("**Résumé par port de chargement (POL)**")
                st.dataframe(styled, use_container_width=True)

            xbytes = clsveh.build_classification_excel_bytes(cls_entries, ship_lbl, voy_lbl)
            st.download_button(
                "⬇️ Télécharger la classification (Excel — mise en page fidèle au fichier de référence)",
                data=xbytes,
                file_name=f"Classification_VEHICULE_{ship_lbl}_{voy_lbl}.xlsx".replace(" ", "_"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"{prefix}_dl",
            )
    else:
        st.info("Uploadez un ou plusieurs manifestes bruts puis cliquez sur « Générer la classification ».")
