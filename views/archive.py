"""
Page Archives — archive numérique unifiée de tous les fichiers générés
dans l'application (manifestes, pré-masques grue, MASQUE TCS, TYPE ISO).
Accessible à tous les utilisateurs avec filtres et recherche avancés.
"""
import pathlib
import sys
from io import BytesIO
from datetime import timezone

import pandas as pd
import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import tracking
from ui_helpers import help_expander, format_duree

tracking.clear_demo_data()

st.title("Archives")
st.caption(
    "Archive numérique de tous les fichiers générés dans l'application — "
    "manifestes structurés, pré-masques navires à grue, MASQUE TCS et TYPE ISO. "
    "Tous les agents · tous les navires."
)

# ---------------------------------------------------------------------------
# Chargement des données
# ---------------------------------------------------------------------------
df_manifestes = tracking.read_log()
df_lr         = tracking.read_loading_reports()

# Unifier les deux sources pour les métriques globales
_total_manifestes = len(df_manifestes)
_total_lr         = len(df_lr)
_total            = _total_manifestes + _total_lr

_agents_m  = set(df_manifestes["agent"].dropna().unique()) if not df_manifestes.empty else set()
_agents_lr = set(df_lr["agent"].dropna().unique())         if not df_lr.empty         else set()
_all_agents = sorted(_agents_m | _agents_lr)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total archivé", _total)
m2.metric("Manifestes / Pré-masques", _total_manifestes)
m3.metric("MASQUE TCS / TYPE ISO", _total_lr)
m4.metric("Agents distincts", len(_all_agents))

st.divider()

# ---------------------------------------------------------------------------
# Barre de recherche et filtres communs (au-dessus des onglets)
# ---------------------------------------------------------------------------
with st.container():
    col_q, col_agent, col_navire = st.columns([2.5, 1.5, 1.5])
    with col_q:
        query = st.text_input(
            "🔍 Rechercher",
            placeholder="Navire, voyage, agent, fichier…",
            key="arch_query",
        )
    with col_agent:
        agent_filtre = st.multiselect(
            "Agent", _all_agents, placeholder="Tous",
            key="arch_agent",
        )
    with col_navire:
        # Navires issus des deux sources
        _navires_m  = list(df_manifestes["navire"].dropna().unique()) if not df_manifestes.empty else []
        _navires_lr = list(df_lr["navire"].dropna().unique())          if not df_lr.empty         else []
        _navires    = sorted(set(_navires_m + _navires_lr))
        navire_filtre = st.multiselect(
            "Navire", _navires, placeholder="Tous",
            key="arch_navire",
        )

    col_date1, col_date2, col_tri = st.columns([1.5, 1.5, 2])
    with col_date1:
        date_debut = st.date_input("Du", value=None, key="arch_d1", format="DD/MM/YYYY")
    with col_date2:
        date_fin   = st.date_input("Au", value=None, key="arch_d2", format="DD/MM/YYYY")
    with col_tri:
        tri_label = st.selectbox(
            "Trier par",
            ["Date (récent → ancien)", "Date (ancien → récent)", "Navire A → Z", "Agent A → Z"],
            key="arch_tri",
        )


def _apply_filters(df: pd.DataFrame, cols_search: list) -> pd.DataFrame:
    """Applique les filtres communs à un dataframe."""
    if df.empty:
        return df

    # Recherche textuelle
    if query:
        q = query.lower()
        mask = pd.Series(False, index=df.index)
        for col in cols_search:
            if col in df.columns:
                mask = mask | df[col].fillna("").str.lower().str.contains(q, regex=False)
        df = df[mask]

    # Filtre agent
    if agent_filtre:
        df = df[df["agent"].isin(agent_filtre)]

    # Filtre navire
    if navire_filtre and "navire" in df.columns:
        df = df[df["navire"].isin(navire_filtre)]

    # Filtre dates
    if "horodatage" in df.columns:
        ts = pd.to_datetime(df["horodatage"], utc=True, errors="coerce")
        if date_debut:
            ts_debut = pd.Timestamp(date_debut, tz=timezone.utc)
            df = df[ts >= ts_debut]
        if date_fin:
            ts_fin = pd.Timestamp(date_fin, tz=timezone.utc) + pd.Timedelta(days=1)
            df = df[ts < ts_fin]

    # Tri
    if "horodatage" in df.columns:
        asc = "ancien" in tri_label
        if "Navire" in tri_label:
            df = df.sort_values("navire", ascending=True, na_position="last")
        elif "Agent" in tri_label:
            df = df.sort_values("agent", ascending=True, na_position="last")
        else:
            df = df.sort_values("horodatage", ascending=asc)

    return df


# ---------------------------------------------------------------------------
# Trois onglets : Manifestes | Loading Reports | Tout (unifié)
# ---------------------------------------------------------------------------
tab_m, tab_lr_view, tab_all = st.tabs(
    ["📦 Manifestes & Pré-masques", "📋 MASQUE TCS / TYPE ISO", "🗂️ Tout (unifié)"]
)

# ============================================================================
# ONGLET 1 · Manifestes & Pré-masques (PDF + grue)
# ============================================================================
with tab_m:

    df_m = _apply_filters(
        df_manifestes.copy() if not df_manifestes.empty else df_manifestes,
        ["navire", "voyage", "fichier", "agent"],
    )

    if df_m.empty:
        if df_manifestes.empty:
            st.info(
                "Aucun manifeste archivé. "
                "Cette section se remplit automatiquement à chaque traitement "
                "depuis **Pré-Masque**."
            )
        else:
            st.warning("Aucun résultat pour ces filtres.", icon="🔍")
    else:
        st.caption(f"{len(df_m)} entrée(s) affichée(s)")

        for _, row in df_m.iterrows():
            ts    = row.get("horodatage")
            ts_fr = pd.to_datetime(ts, utc=True).strftime("%d/%m/%Y %H:%M") if pd.notna(ts) else "—"
            navire = row.get("navire") or "—"
            voyage = row.get("voyage") or "—"
            agent  = row.get("agent") or "—"
            service= row.get("service") or ""
            verifie= bool(row.get("verifie"))
            type_c = row.get("type_cargo") or "—"
            nb_bl  = int(row.get("nb_bl") or 0)
            nb_veh = int(row.get("nb_vehicules") or 0)
            nb_cont= int(row.get("nb_conteneurs") or 0)
            tid    = int(row.get("id") or 0)

            _badge = "✅" if verifie else "🕔"
            _label = f"{_badge} **{navire}** / {voyage} — {ts_fr} — {agent}"
            if service:
                _label += f" ({service})"

            with st.expander(_label, expanded=False):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("B/L", nb_bl)
                c2.metric("Véhicules", nb_veh)
                c3.metric("Conteneurs", nb_cont)
                c4.metric("Type", type_c.replace("🚗", "").replace("📦", "").replace("🔀", "").strip())

                # Fichier source PDF
                pdf_rel = str(row.get("pdf_path") or "").strip()
                if pdf_rel:
                    pdf_path = tracking.DATA_DIR / pdf_rel
                    if pdf_path.exists():
                        st.download_button(
                            "⬇ PDF source",
                            data=pdf_path.read_bytes(),
                            file_name=pdf_path.name,
                            mime="application/pdf",
                            key=f"pdf_{tid}",
                        )

                # Export Excel archivé
                xls_rel = str(row.get("export_path") or "").strip()
                if xls_rel:
                    xls_path = tracking.DATA_DIR / xls_rel
                    if xls_path.exists():
                        st.download_button(
                            "⬇ Excel archivé",
                            data=xls_path.read_bytes(),
                            file_name=xls_path.name,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"xls_{tid}",
                        )

                # Case vérification
                _vkey = f"arch_verifie_{tid}"
                def _on_v(tid=tid, key=_vkey):
                    tracking.set_verifie(tid, st.session_state[key])
                st.checkbox(
                    "Marqué comme vérifié",
                    value=verifie,
                    key=_vkey,
                    on_change=_on_v,
                )

        # Export CSV de la sélection
        st.divider()
        _export_cols = ["horodatage", "navire", "voyage", "agent", "service", "nb_bl",
                        "nb_vehicules", "nb_conteneurs", "type_cargo", "verifie", "fichier"]
        _avail = [c for c in _export_cols if c in df_m.columns]
        csv_bytes = df_m[_avail].to_csv(index=False, sep=";").encode("utf-8-sig")
        st.download_button(
            "⬇ Exporter cette sélection (.csv)",
            data=csv_bytes,
            file_name="archive_manifestes.csv",
            mime="text/csv",
        )


# ============================================================================
# ONGLET 2 · MASQUE TCS / TYPE ISO
# ============================================================================
with tab_lr_view:

    df_l = _apply_filters(
        df_lr.copy() if not df_lr.empty else df_lr,
        ["navire", "voyage", "agent", "compte_escale", "source_file"],
    )

    if df_l.empty:
        if df_lr.empty:
            st.info(
                "Aucun Loading Report archivé. "
                "Les fichiers MASQUE TCS et TYPE ISO sont archivés automatiquement "
                "à chaque génération depuis **MASQUE / TYPE ISO**."
            )
        else:
            st.warning("Aucun résultat pour ces filtres.", icon="🔍")
    else:
        st.caption(f"{len(df_l)} entrée(s) affichée(s)")

        for _, row in df_l.iterrows():
            ts    = row.get("horodatage")
            ts_fr = pd.to_datetime(ts, utc=True).strftime("%d/%m/%Y %H:%M") if pd.notna(ts) else "—"
            navire = row.get("navire") or "—"
            voyage = row.get("voyage") or "—"
            agent  = row.get("agent") or "—"
            escale = row.get("compte_escale") or "—"
            nb_cont= int(row.get("nb_conteneurs") or 0)
            rid    = int(row.get("id") or 0)

            with st.expander(f"📋 **{navire}** / {voyage} — {ts_fr} — {agent}", expanded=False):
                c1, c2, c3 = st.columns(3)
                c1.metric("Conteneurs", nb_cont)
                c2.metric("Compte escale", escale)
                c3.metric("Agent", agent)

                masque_rel = str(row.get("masque_path") or "").strip()
                iso_rel    = str(row.get("iso_path")    or "").strip()
                source_rel = str(row.get("source_file") or "").strip()

                col_dl1, col_dl2 = st.columns(2)
                with col_dl1:
                    if masque_rel:
                        mp = tracking.DATA_DIR / masque_rel
                        if mp.exists():
                            st.download_button(
                                "⬇ MASQUE TCS EXPORT",
                                data=mp.read_bytes(),
                                file_name=mp.name,
                                mime="text/csv",
                                key=f"masque_{rid}",
                                use_container_width=True,
                            )
                with col_dl2:
                    if iso_rel:
                        ip = tracking.DATA_DIR / iso_rel
                        if ip.exists():
                            st.download_button(
                                "⬇ TYPE ISO",
                                data=ip.read_bytes(),
                                file_name=ip.name,
                                mime="text/csv",
                                key=f"iso_{rid}",
                                use_container_width=True,
                            )

        # Export CSV
        st.divider()
        _lr_cols = ["horodatage", "navire", "voyage", "agent", "compte_escale", "nb_conteneurs", "source_file"]
        _lavail  = [c for c in _lr_cols if c in df_l.columns]
        csv_lr   = df_l[_lavail].to_csv(index=False, sep=";").encode("utf-8-sig")
        st.download_button(
            "⬇ Exporter cette sélection (.csv)",
            data=csv_lr,
            file_name="archive_loading_reports.csv",
            mime="text/csv",
        )


# ============================================================================
# ONGLET 3 · Vue unifiée — tout
# ============================================================================
with tab_all:
    st.caption(
        "Vue chronologique de tous les fichiers archivés, tous types confondus."
    )

    # Construire un dataframe unifié
    rows_unified = []

    if not df_manifestes.empty:
        for _, r in df_manifestes.iterrows():
            ts = r.get("horodatage")
            rows_unified.append({
                "Date":     pd.to_datetime(ts, utc=True) if pd.notna(ts) else pd.NaT,
                "Type":     "Manifeste / Pré-masque",
                "Navire":   r.get("navire") or "—",
                "Voyage":   r.get("voyage") or "—",
                "Agent":    r.get("agent") or "—",
                "Service":  r.get("service") or "—",
                "Détail":   f"{int(r.get('nb_bl') or 0)} B/L · {int(r.get('nb_vehicules') or 0)} véh. · {int(r.get('nb_conteneurs') or 0)} cont.",
                "Vérifié":  "✅" if r.get("verifie") else "🕔",
            })

    if not df_lr.empty:
        for _, r in df_lr.iterrows():
            ts = r.get("horodatage")
            rows_unified.append({
                "Date":     pd.to_datetime(ts, utc=True) if pd.notna(ts) else pd.NaT,
                "Type":     "MASQUE TCS / TYPE ISO",
                "Navire":   r.get("navire") or "—",
                "Voyage":   r.get("voyage") or "—",
                "Agent":    r.get("agent") or "—",
                "Service":  "—",
                "Détail":   f"{int(r.get('nb_conteneurs') or 0)} cont. · escale {r.get('compte_escale') or '—'}",
                "Vérifié":  "—",
            })

    if not rows_unified:
        st.info("Aucune archive disponible pour le moment.")
    else:
        df_uni = pd.DataFrame(rows_unified)

        # Appliquer filtres texte/agent/navire
        if query:
            q = query.lower()
            mask = (
                df_uni["Navire"].str.lower().str.contains(q, regex=False) |
                df_uni["Voyage"].str.lower().str.contains(q, regex=False) |
                df_uni["Agent"].str.lower().str.contains(q, regex=False) |
                df_uni["Détail"].str.lower().str.contains(q, regex=False)
            )
            df_uni = df_uni[mask]
        if agent_filtre:
            df_uni = df_uni[df_uni["Agent"].isin(agent_filtre)]
        if navire_filtre:
            df_uni = df_uni[df_uni["Navire"].isin(navire_filtre)]
        if date_debut:
            df_uni = df_uni[df_uni["Date"] >= pd.Timestamp(date_debut, tz=timezone.utc)]
        if date_fin:
            df_uni = df_uni[df_uni["Date"] < pd.Timestamp(date_fin, tz=timezone.utc) + pd.Timedelta(days=1)]

        # Tri
        if "Navire" in tri_label:
            df_uni = df_uni.sort_values("Navire")
        elif "Agent" in tri_label:
            df_uni = df_uni.sort_values("Agent")
        else:
            df_uni = df_uni.sort_values("Date", ascending="ancien" in tri_label)

        df_uni["Date"] = df_uni["Date"].dt.strftime("%d/%m/%Y %H:%M")

        st.caption(f"{len(df_uni)} entrée(s)")
        st.dataframe(
            df_uni,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Type":    st.column_config.TextColumn(width="medium"),
                "Navire":  st.column_config.TextColumn(width="medium"),
                "Voyage":  st.column_config.TextColumn(width="small"),
                "Agent":   st.column_config.TextColumn(width="medium"),
                "Service": st.column_config.TextColumn(width="small"),
                "Détail":  st.column_config.TextColumn(width="large"),
                "Vérifié": st.column_config.TextColumn(width="small"),
            },
            height=min(40 * (len(df_uni) + 1) + 3, 600),
        )

        # Export unifié
        csv_all = df_uni.to_csv(index=False, sep=";").encode("utf-8-sig")
        st.download_button(
            "⬇ Exporter tout (.csv)",
            data=csv_all,
            file_name="archive_complete.csv",
            mime="text/csv",
        )
