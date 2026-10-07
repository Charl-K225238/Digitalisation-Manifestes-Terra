"""
Page Archives — archive numérique unifiée de tous les fichiers générés
dans l'application (manifestes, pré-masques grue, MASQUE TCS, TYPE ISO)
et des fichiers sources Stats Flash (analystes uniquement).
Une seule liste, avec recherche, filtres (type, mois, agent, navire, dates)
et trois affichages : liste, groupé par mois, groupé par navire.
"""
import pathlib
import sys
import re
from datetime import timezone

import pandas as pd
import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import tracking
import stats_store

@st.cache_data(ttl=60, show_spinner=False)
def _cached_read_log(): return tracking.read_log()

@st.cache_data(ttl=60, show_spinner=False)
def _cached_read_lr(): return tracking.read_loading_reports()

@st.cache_data(ttl=60, show_spinner=False)
def _cached_sources_sf(): return stats_store.list_sources()

@st.cache_data(ttl=300, show_spinner=False)
def _cached_file(path: str): return tracking.get_archive_file(path)
from ui_helpers import help_expander, format_duree, current_access_role

tracking.clear_demo_data()

st.title("Archives")
st.caption(
    "Archive numérique de tous les fichiers générés dans l'application — "
    "manifestes structurés, pré-masques navires à grue, MASQUE TCS, TYPE ISO "
    "et fichiers sources Stats Flash. Tous les agents · tous les navires."
)

# ---------------------------------------------------------------------------
# Chargement des données — tri chronologique décroissant par défaut
# ---------------------------------------------------------------------------
df_manifestes = _cached_read_log()
df_lr         = _cached_read_lr()

# Garantir le tri récent→ancien dès le chargement (indépendamment de la DB)
if not df_manifestes.empty and "horodatage" in df_manifestes.columns:
    df_manifestes = df_manifestes.sort_values("horodatage", ascending=False).reset_index(drop=True)
if not df_lr.empty and "horodatage" in df_lr.columns:
    df_lr = df_lr.sort_values("horodatage", ascending=False).reset_index(drop=True)

DEFAULT_LIMIT = 10  # Entrées affichées par défaut (sans filtre) — bouton pour tout voir

# Fichiers sources Stats Flash : réservés aux analystes
_is_analyste = current_access_role() == "analyste"
_sf = _cached_sources_sf() if _is_analyste else []

MOIS_FR = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet",
           "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
T_MAN, T_LR, T_SF = "Manifestes & pré-masques", "MASQUE TCS / TYPE ISO", "Stats Flash"


def _mois_key(ts) -> str:
    return ts.strftime("%Y-%m") if pd.notna(ts) else ""


def _mois_label(k: str) -> str:
    try:
        y, m = k.split("-")
        return f"{MOIS_FR[int(m) - 1]} {y}"
    except Exception:
        return "Date inconnue"


_ts_m = pd.to_datetime(df_manifestes["horodatage"], utc=True, errors="coerce") if not df_manifestes.empty else pd.Series(dtype="datetime64[ns, UTC]")
_ts_l = pd.to_datetime(df_lr["horodatage"], utc=True, errors="coerce") if not df_lr.empty else pd.Series(dtype="datetime64[ns, UTC]")
_all_mois = sorted(({_mois_key(t) for t in list(_ts_m) + list(_ts_l)} | {s["mois"] for s in _sf}) - {""}, reverse=True)

_agents_m  = set(df_manifestes["agent"].dropna().unique()) if not df_manifestes.empty else set()
_agents_lr = set(df_lr["agent"].dropna().unique())         if not df_lr.empty         else set()
_all_agents = sorted(_agents_m | _agents_lr)

cols_k = st.columns(5 if _is_analyste else 4)
cols_k[0].metric("Total archivé", len(df_manifestes) + len(df_lr) + len(_sf))
cols_k[1].metric(T_MAN, len(df_manifestes))
cols_k[2].metric(T_LR, len(df_lr))
if _is_analyste:
    cols_k[3].metric(T_SF, len(_sf))
cols_k[-1].metric("Agents distincts", len(_all_agents))

st.divider()

# ---------------------------------------------------------------------------
# Barre de recherche et filtres communs
# ---------------------------------------------------------------------------
_types_dispo = [T_MAN, T_LR] + ([T_SF] if _is_analyste else [])
with st.container():
    col_q, col_type = st.columns([2.5, 2])
    with col_q:
        query = st.text_input(
            "🔍 Rechercher",
            placeholder="Navire, voyage, agent, fichier…",
            key="arch_query",
        )
    with col_type:
        type_filtre = st.multiselect("Type", _types_dispo, placeholder="Tous", key="arch_type")

    col_mois, col_agent, col_navire = st.columns([1.5, 1.5, 2])
    with col_mois:
        mois_filtre = st.selectbox(
            "Mois", ["Tous les mois"] + _all_mois, key="arch_mois",
            format_func=lambda k: k if k == "Tous les mois" else _mois_label(k),
        )
    with col_agent:
        agent_filtre = st.multiselect("Agent", _all_agents, placeholder="Tous", key="arch_agent")
    with col_navire:
        _navires_m  = list(df_manifestes["navire"].dropna().unique()) if not df_manifestes.empty else []
        _navires_lr = list(df_lr["navire"].dropna().unique())          if not df_lr.empty         else []
        _navires    = sorted(set(_navires_m + _navires_lr))
        navire_filtre = st.multiselect("Navire", _navires, placeholder="Tous", key="arch_navire")

    col_date1, col_date2, col_tri, col_vue = st.columns([1.2, 1.2, 1.8, 1.8])
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
    with col_vue:
        vue = st.selectbox("Affichage", ["Liste", "Grouper par mois", "Grouper par navire"], key="arch_vue")

DEFAULT_LIMIT = 10  # Entrées affichées par défaut (sans filtre) en vue « Liste »


def _safe_name(*parts: str) -> str:
    """Construit un nom de fichier propre à partir des parties fournies
    (navire, voyage, etc.) — sans caractères interdits, sans espaces."""
    joined = "_".join(p.strip() for p in parts if p and p != "—")
    return re.sub(r"[^\w\-]", "_", joined, flags=re.UNICODE)


def _filters_active() -> bool:
    """True si l'utilisateur a saisi une recherche ou un filtre (type, mois,
    agent, navire, dates). Le tri et l'affichage ne sont pas des filtres."""
    return bool(query or type_filtre or mois_filtre != "Tous les mois"
                or agent_filtre or navire_filtre or date_debut or date_fin)


def _apply_filters(df: pd.DataFrame, cols_search: list) -> pd.DataFrame:
    """Filtres texte / agent / navire / dates sur un dataframe d'archives."""
    if df.empty:
        return df
    if query:
        q = query.lower()
        mask = pd.Series(False, index=df.index)
        for col in cols_search:
            if col in df.columns:
                mask = mask | df[col].fillna("").str.lower().str.contains(q, regex=False)
        df = df[mask]
    if agent_filtre:
        df = df[df["agent"].isin(agent_filtre)]
    if navire_filtre and "navire" in df.columns:
        df = df[df["navire"].isin(navire_filtre)]
    if "horodatage" in df.columns:
        ts = pd.to_datetime(df["horodatage"], utc=True, errors="coerce")
        if date_debut:
            df = df[ts >= pd.Timestamp(date_debut, tz=timezone.utc)]
            ts = pd.to_datetime(df["horodatage"], utc=True, errors="coerce")
        if date_fin:
            df = df[ts < pd.Timestamp(date_fin, tz=timezone.utc) + pd.Timedelta(days=1)]
    return df


# ---------------------------------------------------------------------------
# Rendu d'une entrée (une fonction par type — logique d'origine conservée)
# ---------------------------------------------------------------------------
def _fmt_ts(ts) -> str:
    return pd.to_datetime(ts, utc=True).strftime("%d/%m/%Y %H:%M") if pd.notna(ts) else "—"


def _confirm_delete(prefix: str, ident: int, delete_fn, clear_cache):
    """Suppression en deux temps (confirmation) — identique pour les deux types."""
    dkey = f"_del_confirm_{prefix}_{ident}"
    if not st.session_state.get(dkey):
        if st.button("🗑️ Supprimer cette entrée", key=f"del_{prefix}_{ident}"):
            st.session_state[dkey] = True
            st.rerun()
    else:
        st.error("⚠️ Confirmer la suppression ? Cette action est irréversible.")
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("✅ Oui, supprimer", key=f"del_{prefix}_yes_{ident}", type="primary"):
                delete_fn(ident)
                clear_cache()
                st.session_state.pop(dkey, None)
                st.rerun()
        with col_no:
            if st.button("Annuler", key=f"del_{prefix}_no_{ident}"):
                st.session_state.pop(dkey, None)
                st.rerun()


def _render_man(row):
    ts_fr = _fmt_ts(row.get("horodatage"))
    navire = row.get("navire") or "—"
    voyage = row.get("voyage") or "—"
    agent = row.get("agent") or "—"
    service = row.get("service") or ""
    verifie = bool(row.get("verifie"))
    type_c = row.get("type_cargo") or "—"
    nb_bl = int(row.get("nb_bl") or 0)
    nb_veh = int(row.get("nb_vehicules") or 0)
    nb_cont = int(row.get("nb_conteneurs") or 0)
    tid = int(row.get("id") or 0)

    label = f"{'✅' if verifie else '🕔'} **{navire}** / {voyage} — {ts_fr} — {agent}"
    if service:
        label += f" ({service})"
    with st.expander(label, expanded=False):
        st.caption(T_MAN)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("B/L", nb_bl)
        c2.metric("Véhicules", nb_veh)
        c3.metric("Conteneurs", nb_cont)
        c4.metric("Type", type_c.replace("🚗", "").replace("📦", "").replace("🔀", "").strip())

        pdf_rel = str(row.get("pdf_path") or "").strip()
        if pdf_rel:
            _pdf_bytes = tracking.get_archive_file(pdf_rel)
            if _pdf_bytes:
                st.download_button("⬇ PDF source", data=_pdf_bytes,
                                   file_name=f"Manifeste_{_safe_name(navire, voyage)}.pdf",
                                   mime="application/pdf", key=f"pdf_{tid}")
        xls_rel = str(row.get("export_path") or "").strip()
        if xls_rel:
            _xls_bytes = tracking.get_archive_file(xls_rel)
            if _xls_bytes:
                st.download_button("⬇ Excel archivé", data=_xls_bytes,
                                   file_name=f"Premaske_{_safe_name(navire, voyage)}.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                   key=f"xls_{tid}")

        _vkey = f"arch_verifie_{tid}"

        def _on_v(tid=tid, key=_vkey):
            tracking.set_verifie(tid, st.session_state[key])
            _cached_read_log.clear()
        st.checkbox("Marqué comme vérifié", value=verifie, key=_vkey, on_change=_on_v)

        _confirm_delete("m", tid, tracking.delete_traitement, _cached_read_log.clear)


def _render_lr(row):
    ts_fr = _fmt_ts(row.get("horodatage"))
    navire = row.get("navire") or "—"
    voyage = row.get("voyage") or "—"
    agent = row.get("agent") or "—"
    escale = row.get("compte_escale") or "—"
    nb_cont = int(row.get("nb_conteneurs") or 0)
    rid = int(row.get("id") or 0)

    with st.expander(f"📋 **{navire}** / {voyage} — {ts_fr} — {agent}", expanded=False):
        st.caption(T_LR)
        c1, c2, c3 = st.columns(3)
        c1.metric("Conteneurs", nb_cont)
        c2.metric("Compte escale", escale)
        c3.metric("Agent", agent)

        masque_rel = str(row.get("masque_path") or "").strip()
        iso_rel = str(row.get("iso_path") or "").strip()
        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            if masque_rel:
                _b = tracking.get_archive_file(masque_rel)
                if _b:
                    st.download_button("⬇ MASQUE TCS EXPORT", data=_b,
                                       file_name=f"MASQUE_TCS_{_safe_name(navire, voyage)}.csv",
                                       mime="text/csv", key=f"masque_{rid}", use_container_width=True)
        with col_dl2:
            if iso_rel:
                _b = tracking.get_archive_file(iso_rel)
                if _b:
                    st.download_button("⬇ TYPE ISO", data=_b,
                                       file_name=f"TYPE_ISO_{_safe_name(navire, voyage)}.csv",
                                       mime="text/csv", key=f"iso_{rid}", use_container_width=True)

        _confirm_delete("lr", rid, tracking.delete_loading_report, _cached_read_lr.clear)


def _render_sf(s):
    ts_fr = _fmt_ts(s["ts"])
    with st.expander(f"📊 **{s['genre']}** — {_mois_label(s['mois'])} — chargé le {ts_fr}", expanded=False):
        st.caption(f"{T_SF} · {s['nom']}")
        data = _cached_file(s["path"])
        if data:
            mime = ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    if s["nom"].lower().endswith("xlsx") else "application/vnd.ms-excel")
            st.download_button("⬇ Télécharger le fichier source", data=data, file_name=s["nom"],
                               mime=mime, key=f"sf_{s['path']}")
        else:
            st.caption("Fichier introuvable dans le stockage.")


# ---------------------------------------------------------------------------
# Construction de la liste unifiée
# ---------------------------------------------------------------------------
items = []
if not type_filtre or T_MAN in type_filtre:
    for _, row in _apply_filters(df_manifestes.copy(), ["navire", "voyage", "fichier", "agent"]).iterrows():
        ts = pd.to_datetime(row.get("horodatage"), utc=True, errors="coerce")
        items.append({"kind": "man", "type": T_MAN, "ts": ts, "mois": _mois_key(ts), "row": row,
                      "navire": row.get("navire") or "—", "voyage": row.get("voyage") or "—",
                      "agent": row.get("agent") or "—",
                      "detail": f"{int(row.get('nb_bl') or 0)} B/L · {int(row.get('nb_vehicules') or 0)} véh. · "
                                f"{int(row.get('nb_conteneurs') or 0)} cont."})
if not type_filtre or T_LR in type_filtre:
    for _, row in _apply_filters(df_lr.copy(), ["navire", "voyage", "agent", "compte_escale", "source_file"]).iterrows():
        ts = pd.to_datetime(row.get("horodatage"), utc=True, errors="coerce")
        items.append({"kind": "lr", "type": T_LR, "ts": ts, "mois": _mois_key(ts), "row": row,
                      "navire": row.get("navire") or "—", "voyage": row.get("voyage") or "—",
                      "agent": row.get("agent") or "—",
                      "detail": f"{int(row.get('nb_conteneurs') or 0)} cont. · escale {row.get('compte_escale') or '—'}"})
if _is_analyste and (not type_filtre or T_SF in type_filtre) and not agent_filtre and not navire_filtre:
    for s in _sf:
        if query and query.lower() not in f"{s['nom']} {s['genre']} {_mois_label(s['mois'])}".lower():
            continue
        if date_debut and s["ts"] < pd.Timestamp(date_debut, tz=timezone.utc):
            continue
        if date_fin and s["ts"] >= pd.Timestamp(date_fin, tz=timezone.utc) + pd.Timedelta(days=1):
            continue
        items.append({"kind": "sf", "type": T_SF, "ts": pd.Timestamp(s["ts"]), "mois": s["mois"], "row": s,
                      "navire": T_SF, "voyage": "—", "agent": "—", "detail": f"{s['genre']} · {s['nom']}"})

if mois_filtre != "Tous les mois":
    items = [i for i in items if i["mois"] == mois_filtre]

if "Navire" in tri_label:
    items.sort(key=lambda i: str(i["navire"]).lower())
elif "Agent" in tri_label:
    items.sort(key=lambda i: str(i["agent"]).lower())
else:
    items.sort(key=lambda i: i["ts"] if pd.notna(i["ts"]) else pd.Timestamp.min.tz_localize("UTC"),
               reverse="ancien" not in tri_label)

_RENDER = {"man": _render_man, "lr": _render_lr, "sf": _render_sf}

# ---------------------------------------------------------------------------
# Affichage
# ---------------------------------------------------------------------------
if not items:
    if not (len(df_manifestes) or len(df_lr) or len(_sf)):
        st.info("Aucune archive pour le moment. Cette page se remplit automatiquement à chaque traitement "
                "(Pré-Masque, MASQUE / TYPE ISO) et à chaque chargement Stats Flash.")
    else:
        st.warning("Aucun résultat pour ces filtres.", icon="🔍")
else:
    if vue == "Liste":
        total = len(items)
        shown = items
        if _filters_active():
            st.caption(f"{total} résultat(s) pour ces filtres")
        elif total <= DEFAULT_LIMIT:
            st.caption(f"{total} entrée(s)")
        elif st.session_state.get("arch_all", False):
            st.caption(f"{total} entrée(s) — toutes affichées")
            if st.button("⬆ Réduire aux 10 dernières", key="arch_all_less"):
                st.session_state["arch_all"] = False
                st.rerun()
        else:
            st.caption(f"{DEFAULT_LIMIT} dernières entrées sur {total}")
            shown = items[:DEFAULT_LIMIT]
        for it in shown:
            _RENDER[it["kind"]](it["row"])
        if (not _filters_active() and total > DEFAULT_LIMIT and not st.session_state.get("arch_all", False)):
            if st.button(f"⬇ Afficher les {total - DEFAULT_LIMIT} autres entrées",
                         key="arch_all_more", use_container_width=True):
                st.session_state["arch_all"] = True
                st.rerun()
    else:
        par_mois = vue == "Grouper par mois"
        groupes: dict = {}
        for it in items:
            g = _mois_label(it["mois"]) if par_mois else it["navire"]
            groupes.setdefault(g, []).append(it)
        st.caption(f"{len(items)} entrée(s) · {len(groupes)} groupe(s)")
        for g, lst in groupes.items():
            st.markdown(f"#### {g} · {len(lst)} fichier(s)")
            for it in lst:
                _RENDER[it["kind"]](it["row"])

    # Export CSV de la sélection complète
    st.divider()
    df_exp = pd.DataFrame([{
        "Date": _fmt_ts(i["ts"]), "Type": i["type"], "Navire": i["navire"], "Voyage": i["voyage"],
        "Agent": i["agent"], "Détail": i["detail"],
    } for i in items])
    st.download_button(
        "⬇ Exporter cette sélection (.csv)",
        data=df_exp.to_csv(index=False, sep=";").encode("utf-8-sig"),
        file_name="archive_selection.csv",
        mime="text/csv",
    )
