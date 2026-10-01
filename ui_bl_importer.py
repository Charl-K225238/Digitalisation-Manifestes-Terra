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
        "Le fichier généré est le classeur **IMPORTER VEHICULE** des agents (en-têtes vert / rouge / noir, "
        "mêmes formules). **Pré-rempli depuis le manifeste** : N° B/L et châssis (rouge), nature, destination "
        "finale, port de chargement (UNLOCODE), commodity, client (Comment), volume/poids, modèle, "
        "expéditeur. **À saisir par vous** : Call Number et SlotFile (données d'escale absentes du manifeste). "
        "Les colonnes noires sont déjà calculées."
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
        for k in ("df", "units", "warnings", "errors", "formats", "xls"):
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
        df_new = bli.units_to_dataframe(units) if units else None
        st.session_state[f"{prefix}_df"] = df_new
        st.session_state[f"{prefix}_xls"] = None
        if df_new is not None:
            try:  # généré une seule fois (pas à chaque interaction Streamlit)
                st.session_state[f"{prefix}_xls"] = bli.build_agents_xls_bytes(df_new)
            except Exception as exc:
                st.session_state[f"{prefix}_errors"] = list(errors) + [f"Export Excel impossible : {exc}"]

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
            "BLVolume", "BLWeight", "Port Of Loading City UNLOCODE", "BLItem ChassisNumber",
            "BLItem YardItemCode", "BLItem Commodity Volume", "BLItem Commodity Weight",
            "BLItem VehicleModel"]
    st.dataframe(df[cols].head(20), hide_index=True, use_container_width=True)

    xls_bytes = st.session_state.get(f"{prefix}_xls")
    if xls_bytes is None:
        return
    st.download_button(
        "⬇️ Télécharger le classeur agents IMPORTER VEHICULE (.xls)",
        data=xls_bytes, file_name=bli.default_filename("xls"),
        mime="application/vnd.ms-excel", key=f"{prefix}_dl_xls", type="primary")
    st.caption("Les colonnes calculées (noires) sont déjà renseignées et restent des formules : elles se "
               "mettent à jour si vous modifiez un volume, un poids ou un B/L. Saisissez Call Number et "
               "SlotFile avant l'import dans IPAKI.")
