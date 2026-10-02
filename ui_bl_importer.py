"""
Composant UI : génération du classeur d'import IPAKI « BL Importer » (IMPORTER
VEHICULE) depuis un ou plusieurs manifestes bruts, en 3 étapes :
  1 · Charger  →  2 · Vérifier  →  3 · Télécharger.
Les agents saisissent ensuite Call Number et SlotFile dans le classeur.
"""
import streamlit as st

import bl_importer as bli


def render_bl_importer(prefix: str = "bli"):
    seq_key = f"{prefix}_seq"
    if seq_key not in st.session_state:
        st.session_state[seq_key] = 0
    has_result = st.session_state.get(f"{prefix}_df") is not None

    # ── Étape 1 : charger ────────────────────────────────────────────────
    st.subheader("1 · Charger le(s) manifeste(s)")
    st.caption(
        "Formats reconnus automatiquement : **Chinese RoRo** (Excel), **MOL ALIS**, **Grimaldi** "
        "et **Hyundai Glovis** (PDF, y compris scanné — plus lent, une barre de progression s'affiche). "
        "Vous pouvez charger plusieurs manifestes, de formats différents, en une seule fois."
    )
    files = st.file_uploader(
        "Manifeste(s) bruts (PDF, XLSX ou XLS)", type=["pdf", "xlsx", "xls"],
        accept_multiple_files=True, key=f"{prefix}_up_{st.session_state[seq_key]}",
    )
    col_gen, col_reset = st.columns([3, 1])
    do_gen = col_gen.button(
        "🔄 Générer le BL Importer", type="primary", key=f"{prefix}_gen",
        disabled=not files,
        help=None if files else "Chargez d'abord au moins un manifeste.",
    )
    if (files or has_result) and col_reset.button("🗑️ Tout effacer", key=f"{prefix}_reset"):
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
        if not errors and not files:
            st.info("👆 Commencez par charger un manifeste ci-dessus.")
        elif not errors and files:
            st.info("Cliquez sur « Générer le BL Importer » pour lancer le traitement.")
        return

    units = st.session_state.get(f"{prefix}_units")

    # ── Étape 2 : vérifier ───────────────────────────────────────────────
    st.divider()
    st.subheader("2 · Vérifier le résultat")
    m1, m2, m3 = st.columns(3)
    m1.metric("Véhicules (lignes)", len(df))
    m2.metric("B/L", df["BL Number"].nunique())
    m3.metric("Manifestes lus", len(st.session_state.get(f"{prefix}_formats") or {}))

    chk = bli.check_required(df, units)
    if chk["alertes"] or st.session_state.get(f"{prefix}_warnings"):
        st.markdown("**⚠️ Points à contrôler**")
        for a in chk["alertes"]:
            st.warning(a)
        for w in st.session_state.get(f"{prefix}_warnings") or []:
            st.caption("• " + w)
    else:
        st.success("Aucune anomalie détectée dans les manifestes.")

    st.markdown("**Aperçu des 20 premières lignes**")
    cols = ["BL Number", "ImportExport", "Final Destination Country", "Number of Yard Items",
            "BLVolume", "BLWeight", "Port Of Loading City UNLOCODE", "BLItem ChassisNumber",
            "BLItem YardItemCode", "BLItem Commodity Volume", "BLItem Commodity Weight",
            "BLItem VehicleModel"]
    st.dataframe(df[cols].head(20), hide_index=True, use_container_width=True)

    # ── Étape 3 : télécharger ────────────────────────────────────────────
    st.divider()
    st.subheader("3 · Télécharger et compléter")
    xls_bytes = st.session_state.get(f"{prefix}_xls")
    if xls_bytes is None:
        return
    st.download_button(
        "⬇️ Télécharger le classeur IMPORTER VEHICULE (.xls)",
        data=xls_bytes, file_name=bli.default_filename("xls"),
        mime="application/vnd.ms-excel", key=f"{prefix}_dl_xls", type="primary")
    st.markdown(
        "Le fichier est **prêt pour l'import IPAKI** : valeurs uniquement (aucune formule), uniquement les lignes "
        "avec un N° de B/L, cellules sans donnée réellement vides (ni 0, ni texte). "
        "**Il vous reste à saisir** : `Call Number` et `SlotFile` (colonnes vertes) — et les cellules signalées "
        "à l'étape 2 — puis à importer le fichier dans IPAKI."
    )
