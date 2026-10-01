"""
Composant UI : génération du fichier d'import IPAKI « BL Importer » (70 colonnes)
depuis un ou plusieurs manifestes bruts. Les agents complètent ensuite eux-mêmes
les colonnes de booking (Call Number, SlotFile, Consignee, Shipper, Forwarder...).
"""
import streamlit as st

import bl_importer as bli


def render_bl_importer(prefix: str = "bli"):
    st.caption(
        "Génère le fichier d'import IPAKI « BL Importer » (1 ligne par véhicule) à partir "
        "d'un manifeste brut. Formats reconnus automatiquement : Chinese RoRo (XLSX/XLS), "
        "MOL ALIS, Grimaldi et Hyundai Glovis (PDF, y compris scanné)."
    )
    st.info(
        "**Remplissage automatique** : N° B/L, nature, destination finale, port de chargement "
        "(UNLOCODE), nombre d'unités, volume/poids, châssis, modèle, code véhicule, commodity. "
        "**À compléter par vous** dans le fichier : Call Number, SlotFile, Consignee, Shipper, "
        "Forwarder (données de booking absentes du manifeste)."
    )

    seq_key = f"{prefix}_seq"
    if seq_key not in st.session_state:
        st.session_state[seq_key] = 0
    files = st.file_uploader(
        "Manifeste(s) bruts (PDF, XLSX ou XLS)", type=["pdf", "xlsx", "xls"],
        accept_multiple_files=True, key=f"{prefix}_up_{st.session_state[seq_key]}",
        help="Un ou plusieurs manifestes (formats différents acceptés dans le même envoi).",
    )
    col_gen, col_reset = st.columns([3, 1])
    do_gen = bool(files) and col_gen.button("🔄 Générer le BL Importer", type="primary",
                                            key=f"{prefix}_gen")
    if (files or st.session_state.get(f"{prefix}_df") is not None) and col_reset.button(
            "🗑️ Réinitialiser", key=f"{prefix}_reset"):
        for k in ("df", "units", "warnings", "errors", "formats"):
            st.session_state.pop(f"{prefix}_{k}", None)
        st.session_state[seq_key] += 1
        st.rerun()

    if do_gen:
        bar = st.progress(0.0)
        status = st.empty()

        def _cb(fi, n, name, p, tot):
            bar.progress(min((fi + p / max(tot, 1)) / n, 1.0))
            status.caption(f"Traitement de « {name} » — page {p}/{tot}…")

        raw = [(f.name, f.getvalue()) for f in files]
        units, warnings, errors, formats = bli.build_units(raw, progress_cb=_cb)
        bar.empty()
        status.empty()
        st.session_state[f"{prefix}_units"] = units
        st.session_state[f"{prefix}_warnings"] = warnings
        st.session_state[f"{prefix}_errors"] = errors
        st.session_state[f"{prefix}_formats"] = formats
        st.session_state[f"{prefix}_df"] = bli.units_to_dataframe(units) if units else None

    df = st.session_state.get(f"{prefix}_df")
    errors = st.session_state.get(f"{prefix}_errors") or []
    for e in errors:
        st.error(e)
    if df is None:
        if not errors:
            st.info("Uploadez un ou plusieurs manifestes puis cliquez sur « Générer le BL Importer ».")
        return

    units = st.session_state.get(f"{prefix}_units")
    st.divider()
    m1, m2, m3 = st.columns(3)
    m1.metric("Lignes (véhicules)", len(df))
    m2.metric("B/L", df["BL Number"].nunique())
    m3.metric("Fichiers lus", len(st.session_state.get(f"{prefix}_formats") or {}))

    chk = bli.check_required(df, units)
    for a in chk["alertes"]:
        st.warning(a)
    for w in st.session_state.get(f"{prefix}_warnings") or []:
        st.caption("⚠️ " + w)

    with st.expander("✍️ Colonnes obligatoires à compléter dans le fichier", expanded=True):
        st.dataframe(chk["a_completer"], hide_index=True, use_container_width=True)
        if not chk["manquants_manifeste"].empty:
            st.markdown("**Données absentes du manifeste (à saisir ou vérifier) :**")
            st.dataframe(chk["manquants_manifeste"], hide_index=True, use_container_width=True)

    st.markdown("**Aperçu (20 premières lignes — colonnes principales)**")
    cols = ["BL Number", "ImportExport", "Final Destination Country", "Number of Yard Items",
            "BLVolume", "BLWeight", "Port Of Loading City UNLOCODE", "BLItem YardItemNumber",
            "BLItem YardItemCode", "BLItem Commodity Volume", "BLItem Commodity Weight",
            "BLItem VehicleModel"]
    st.dataframe(df[cols].head(20), hide_index=True, use_container_width=True)

    c1, c2 = st.columns(2)
    c1.download_button(
        "⬇️ Télécharger le BL Importer (.xls — format IPAKI)",
        data=bli.build_xls_bytes(df), file_name=bli.default_filename("xls"),
        mime="application/vnd.ms-excel", key=f"{prefix}_dl_xls", type="primary")
    c2.download_button(
        "⬇️ Version .xlsx", data=bli.build_xlsx_bytes(df),
        file_name=bli.default_filename("xlsx"),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"{prefix}_dl_xlsx")
