"""Page Stats Flash & Reporting RORO / TEU — bloc mensuel (MVP).

Calcule le bloc « REPORTING RORO & TEUS » à partir des fichiers sources du
mois (classeur volumes + extrait PAA), montre d'où vient chaque chiffre,
contrôle la cohérence, accepte des corrections manuelles tracées et exporte
le rapport au format Excel habituel (formules vivantes).

Accès : analystes (complet) et direction (lecture). Voir
claude/ANALYSE_CLASSEUR_FLASH_AOUT_SEPT_2026.md (projet Claude) pour les
règles validées.
"""
import pathlib
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import stats_flash_builder as sfb
import stats_flash_parser as sfp
import stats_store as store
from ui_helpers import current_access_role, current_identity, help_expander
from security_utils import checked_upload, filter_uploads, safe_error

MOIS = [m.capitalize() for m in sfp.MOIS_FR]
SRC_ICON = {
    sfb.SRC_VOLUMES: "🟢 Classeur volumes",
    sfb.SRC_PAA: "🔵 Extrait PAA",
    "Saisie manuelle": "🟡 Saisie manuelle",
    store.SRC_RAPPORT: "⚪ Rapport existant",
    sfb.SRC_ABSENT: "🔴 À compléter",
}
DETAIL_COL = {"teu": "teu", "roro": "roro", "neufs": "neufs", "usages": "usages",
              "t_lt15": "paa_<15", "t_15_50": "paa_15-50", "t_gt50": "paa_>50",
              "l_lt15": "paa_<15", "l_15_50": "paa_15-50", "l_gt50": "paa_>50"}

role = current_access_role()
lecture_seule = role != "analyste"
identity = current_identity() or {}
agent = identity.get("name") or "Inconnu"


# ---------------------------------------------------------------------------
# Formatage lisible (séparateur de milliers, « — » si vide)
# ---------------------------------------------------------------------------
def fnum(v):
    if v is None or pd.isna(v):
        return "—"
    return f"{v:,.0f}".replace(",", " ")


def fpct(v):
    if v is None or pd.isna(v):
        return "—"
    return f"{v * 100:+.1f} %".replace(".", ",")


def _txt(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def color_pct(v):
    if not isinstance(v, str) or v == "—":
        return "color: #8a8f98"
    return "color: #0b7a3b" if v.startswith("+") else "color: #b3261e"


# ---------------------------------------------------------------------------
# Données
# ---------------------------------------------------------------------------
def load_all():
    vals = store.load_values()
    esc = store.load_escales()
    return vals, esc


def dicts_for_year(vals: pd.DataFrame, annee: int):
    r = vals[vals["nature"] == "realise"]
    r26 = {(int(m), k): v for m, k, v in r[(r["annee"] == annee) & (r["mois"] > 0)][["mois", "indicateur", "valeur"]].itertuples(index=False) if pd.notna(v)}
    r25 = {(int(m), k): v for m, k, v in r[(r["annee"] == annee - 1) & (r["mois"] > 0)][["mois", "indicateur", "valeur"]].itertuples(index=False) if pd.notna(v)}
    a25 = {k: v for k, v in r[(r["annee"] == annee - 1) & (r["mois"] == 0)][["indicateur", "valeur"]].itertuples(index=False) if pd.notna(v)}
    b = vals[(vals["nature"] == "budget") & (vals["annee"] == annee) & (vals["mois"] == 0)]
    bud = {k: v for k, v in b[["indicateur", "valeur"]].itertuples(index=False) if pd.notna(v)}
    return r26, r25, a25, bud


def month_rows(vals, annee, mois):
    v = vals[(vals["annee"] == annee) & (vals["mois"] == mois) & (vals["nature"] == "realise")]
    return v.set_index("indicateur")


@st.cache_data(show_spinner="Lecture du classeur…", max_entries=24)
def _parse_vol(data: bytes, name: str):
    return sfp.parse_volumes(data, name)


@st.cache_data(show_spinner="Lecture de l'extrait PAA…", max_entries=24)
def _parse_paa(data: bytes, name: str):
    return sfp.parse_paa(data, name)


# ---------------------------------------------------------------------------
# En-tête
# ---------------------------------------------------------------------------
st.title("Stats Flash & Reporting RORO / TEU")
st.caption("Bloc mensuel « Reporting RORO & TEUS » calculé depuis les fichiers sources du mois. "
           "Chaque chiffre indique sa source ; toute valeur reste corrigeable, avec trace.")
if not store.db_ok():
    st.warning("Base de données indisponible : les chiffres chargés restent en mémoire pendant cette "
               "session seulement. Exécutez le bloc « MISE À JOUR v8 » de supabase_schema.sql pour les conserver.")

with help_expander("ℹ️ Comment lire cette page et d'où viennent les chiffres"):
    st.markdown(
        "- **Charger un mois** : déposez le(s) classeur(s) des volumes et le(s) extrait(s) PAA — un ou plusieurs mois "
        "d'un coup, chaque fichier est rattaché à son mois. Les contrôles s'affichent avant l'enregistrement.\n"
        "- **Reporting mensuel** : le bloc du rapport, avec cumul, comparaison N-1 et budget. "
        "🟢 classeur · 🔵 PAA · 🟡 saisie manuelle · ⚪ rapport existant.\n"
        "- **Contrôles** : points à vérifier (écarts entre le classeur et le PAA).\n"
        "- **Corrections** : toute valeur peut être corrigée, avec motif ; la correction est conservée "
        "aux rechargements.\n\n"
        "**Règles de calcul**\n\n"
        + "\n".join(f"- **{' · '.join(sfb.IND_LABEL[k])}** : {sfb.regle(k)}" for k in sfb.IND_KEYS
                    if k in ("escales", "teu", "roro", "neufs", "usages", "t_lt15", "h_lt15", "l_lt15")))

vals, esc = load_all()

tabs_names = ["📊 Reporting mensuel", "✅ Contrôles"]
if not lecture_seule:
    tabs_names = ["📥 Charger un mois"] + tabs_names + ["✏️ Corrections", "📚 Référentiel"]
tabs = dict(zip(tabs_names, st.tabs(tabs_names)))


# =============================================================================
# 1. Charger un mois
# =============================================================================
if "📥 Charger un mois" in tabs:
    with tabs["📥 Charger un mois"]:
        st.subheader("Fichiers du mois")
        with st.expander("📂 Où trouver les deux fichiers dans SharePoint", expanded=True):
            st.markdown(
                "| Fichier | Dossier SharePoint | Ce qu'il apporte |\n|---|---|---|\n"
                "| **1. Classeur des volumes** (nom : *VOLUMES D'ACTIVITES … ELVIS*) | "
                "`PAA - KOUAI EDEN SUPER U` › `Dossiers PAA <Mois> <AAAA>`<br>ou, pour le classeur « STATS FLASH », "
                "`PLANIFICATION & REPORTING` › `DOSSIERS REPORTING` › `REPORTING` › "
                "`STATS FLASH VOLUMES TCS BOLS MAFIS ET VEHICULES OPN` › `2026` › `<MOIS>` | "
                "Escales, TEU, véhicules, neufs / usagés, Hinterland |\n"
                "| **2. Extrait PAA** (nom : *STATISTIQUES TERRA <MOIS>*) | "
                "`PLANIFICATION & REPORTING` › `DOSSIERS REPORTING` › `REPORTING` › `STATISTIQUES TERRA 2026` | "
                "Tranches de volume (< 15, 15-50, > 50 m³) et trafic Lo/Lo |\n\n"
                "Vous pouvez déposer **plusieurs mois à la fois** : l'app lit le mois dans chaque fichier et rapproche le classeur "
                "de l'extrait PAA du même mois. "
                "Si le dossier du mois paraît vide, la synchronisation SharePoint n'est probablement pas faite "
                "(clic droit › « Toujours conserver sur cet appareil »).",
                unsafe_allow_html=True)
        MAX_FICHIERS = 12   # garde-fou mémoire (Streamlit Cloud gratuit)
        st.markdown(
            "**Noms à chercher dans l'explorateur** (dans le nom, `<MOIS>` = JANVIER, FEVRIER… et `<AAAA>` = 2026) :\n"
            "- **Classeur des volumes** : `VOLUMES D'ACTIVITES <MOIS>_<AAAA>_ELVIS.xls` "
            "ou `STATS FLASH VOLUMES TCS BOLS MAFIS ET VEHICULES OPN <MOIS> <AAAA>.xls`\n"
            "- **Extrait PAA** : `STATISTIQUES TERRA <MOIS> <AAAA>.xls`\n\n"
            "Astuce : dans la fenêtre de sélection, tapez `VOLUMES` ou `STATISTIQUES TERRA` dans la barre de "
            "recherche. Chemins complets dans l'encadré ci-dessous.")
        c1, c2 = st.columns(2)
        with c1:
            f_vols = st.file_uploader(
                "1. Classeur(s) des volumes (recommandé)", type=["xls", "xlsx"], key="sf_vol",
                accept_multiple_files=True,
                help="Plusieurs mois possibles d'un coup : chaque classeur est rattaché à son mois "
                     "(détecté dans le fichier). « VOLUMES D'ACTIVITES <MOIS>_<AAAA>_ELVIS.xls » "
                     "ou « STATS FLASH VOLUMES … <MOIS> <AAAA>.xls ».")
        with c2:
            f_paas = st.file_uploader(
                "2. Extrait(s) PAA (recommandé)", type=["xls"], key="sf_paa",
                accept_multiple_files=True,
                help="Plusieurs mois possibles d'un coup : chaque extrait est rattaché à son mois. "
                     "« STATISTIQUES TERRA <MOIS> <AAAA>.xls » (dossier Reporting › STATISTIQUES TERRA <AAAA>).")
        f_vols = filter_uploads(f_vols)
        f_paas = filter_uploads(f_paas)
        for lst, lbl in ((f_vols, "classeurs"), (f_paas, "extraits PAA")):
            if len(lst) > MAX_FICHIERS:
                st.warning(f"{len(lst)} {lbl} déposés : seuls les {MAX_FICHIERS} premiers sont traités. "
                           "Chargez le reste ensuite.")
                del lst[MAX_FICHIERS:]

        # --- Lecture de chaque fichier, regroupés par mois -----------------------
        vols, paas = {}, {}      # (annee, mois) -> (fichier, résultat)
        for f in f_vols:
            try:
                r = _parse_vol(f.getvalue(), f.name)
            except sfp.SourceError as exc:
                st.error(f"« {f.name} » : {exc}")
                continue
            if (r.annee, r.mois) in vols:
                st.warning(f"« {f.name} » : un classeur de {MOIS[r.mois - 1]} {r.annee} est déjà déposé "
                           f"(« {vols[(r.annee, r.mois)][0].name} »). Ce fichier est ignoré.")
                continue
            vols[(r.annee, r.mois)] = (f, r)
        for f in f_paas:
            try:
                r = _parse_paa(f.getvalue(), f.name)
            except sfp.SourceError as exc:
                st.error(f"« {f.name} » : {exc}")
                continue
            if r.mois is None:
                st.error(f"« {f.name} » : mois de l'extrait PAA introuvable (dates de début absentes).")
                continue
            if (r.annee, r.mois) in paas:
                st.warning(f"« {f.name} » : un extrait PAA de {MOIS[r.mois - 1]} {r.annee} est déjà déposé "
                           f"(« {paas[(r.annee, r.mois)][0].name} »). Ce fichier est ignoré.")
                continue
            paas[(r.annee, r.mois)] = (f, r)

        mois_charges = sorted(set(vols) | set(paas), reverse=True)

        def _save_month(per):
            """Enregistre un mois (classeur + PAA éventuel) ou, sans classeur, les tranches PAA seules."""
            a_, m_ = per
            if per in vols:
                f_v, vol = vols[per]
                f_p, paa = paas.get(per, (None, None))
                calc, det = sfb.compute_month(vol, paa)
                valeurs = {k: v.valeur for k, v in calc.items()}
                fichier = f_v.name + (f" + {f_p.name}" if f_p else "")
                store.save_calcules(a_, m_, valeurs, {k: v.source for k, v in calc.items()}, fichier, agent)
                store.save_escales(a_, m_, det, f_v.name, f_p.name if f_p else "", agent)
                store.archive_source(a_, m_, f_v.name, f_v.getvalue())
                if f_p is not None:
                    store.archive_source(a_, m_, f_p.name, f_p.getvalue())
            else:
                f_p, paa = paas[per]
                calc_s = sfb.compute_paa_only(paa)
                store.save_calcules(a_, m_, {k: v.valeur for k, v in calc_s.items()},
                                    {k: v.source for k, v in calc_s.items()}, f_p.name, agent)
                store.archive_source(a_, m_, f_p.name, f_p.getvalue())

        if st.session_state.get("sf_flash"):
            st.success(st.session_state.pop("sf_flash"))

        if len(mois_charges) > 1:
            st.info(f"{len(mois_charges)} mois détectés : " +
                    ", ".join(f"{MOIS[m - 1]} {a}" for a, m in mois_charges) +
                    ". Chaque classeur est rapproché de l'extrait PAA du même mois.")

        for per in mois_charges:
            a_, m_ = per
            titre = f"{MOIS[m_ - 1]} {a_}"
            with st.expander(f"📅 {titre}", expanded=len(mois_charges) == 1):
                if per in vols:
                    f_v, vol = vols[per]
                    f_p, paa = paas.get(per, (None, None))
                    calc, det = sfb.compute_month(vol, paa)
                    valeurs = {k: v.valeur for k, v in calc.items()}
                    st.success(f"Mois : **{titre}** · {len(det)} escales lues dans la feuille « {vol.feuille} ».")
                    if paa is None:
                        st.info("Sans extrait PAA pour ce mois, les tranches de volume et le trafic Lo/Lo restent "
                                "à compléter (la tranche + 50 m³ est reprise de la colonne DT SUP 50 M3 saisie "
                                "par les agents).")
                    k = st.columns(6)
                    for col, (ind, lab) in zip(k, [("escales", "Escales"), ("teu", "TEU"), ("roro", "RORO"),
                                                   ("neufs", "Neufs"), ("usages", "Usagés")]):
                        col.metric(lab, fnum(valeurs[ind]))
                    k[5].metric("Hinterland", fnum(det["transit"].sum()))

                    ctrl = sfb.controles(det, valeurs, vol.alertes, (paa.annee, paa.mois) if paa else None,
                                         (vol.annee, vol.mois),
                                         (paa.alertes + sfb.paa_hors_classeur(vol, paa)) if paa else ())
                    n_ko = int((ctrl["Statut"] == "À vérifier").sum())
                    if n_ko:
                        st.warning(f"{n_ko} point(s) à vérifier avant d'enregistrer : probable erreur de saisie "
                                   "dans l'un des fichiers. Détail ci-dessous.")
                    st.dataframe(ctrl.assign(**{c: ctrl[c].map(fnum) for c in ["Valeur rapport", "Valeur de contrôle", "Écart"]}),
                                 hide_index=True, width="stretch")

                    deja = month_rows(vals, a_, m_)
                    if not deja.empty and deja["source"].isin([sfb.SRC_VOLUMES, sfb.SRC_PAA]).any():
                        st.caption(f"{titre} a déjà été chargé : l'enregistrement "
                                   "remplace les valeurs calculées. Les corrections manuelles sont conservées.")
                    if st.button(f"💾 Enregistrer {titre}", type="primary", key=f"sf_save_{a_}_{m_}"):
                        _save_month(per)
                        st.session_state["sf_sel"] = per
                        st.session_state["sf_flash"] = f"{titre} enregistré. Ouvrez l'onglet « Reporting mensuel »."
                        st.rerun()
                else:
                    # Mois sans classeur : tranches de volume et Lo/Lo seulement (ex. historique N-1)
                    f_p, paa_s = paas[per]
                    calc_s = sfb.compute_paa_only(paa_s)
                    vs = {k: v.valeur for k, v in calc_s.items()}
                    st.success(f"Extrait PAA seul : **{titre}** · "
                               f"{paa_s.lignes['escale_paa'].nunique()} escales au PAA.")
                    st.info("Sans classeur des volumes, seuls les **tranches de volume** et le **trafic Lo/Lo** sont "
                            "enregistrés. RORO, TEU, neufs / usagés et Hinterland restent inchangés ou à compléter.")
                    k = st.columns(4)
                    k[0].metric("Moins de 15 m³", fnum(vs["t_lt15"]))
                    k[1].metric("15 à 50 m³", fnum(vs["t_15_50"]))
                    k[2].metric("Plus de 50 m³", fnum(vs["t_gt50"]))
                    k[3].metric("dont Lo/Lo", fnum(vs["l_lt15"] + vs["l_15_50"] + vs["l_gt50"]))
                    for a_msg in paa_s.alertes:
                        st.warning(a_msg)
                    if st.button(f"💾 Enregistrer les tranches de {titre}", type="primary",
                                 key=f"sf_save_paa_seul_{a_}_{m_}"):
                        _save_month(per)
                        st.session_state["sf_sel"] = per
                        st.session_state["sf_flash"] = f"Tranches de {titre} enregistrées. Ouvrez l'onglet « Reporting mensuel »."
                        st.rerun()

        if len(mois_charges) > 1:
            if st.button(f"💾 Enregistrer les {len(mois_charges)} mois", type="primary", key="sf_save_all"):
                for per in mois_charges:
                    _save_month(per)
                st.session_state["sf_sel"] = mois_charges[0]
                st.session_state["sf_flash"] = (f"{len(mois_charges)} mois enregistrés : " +
                                                ", ".join(f"{MOIS[m - 1]} {a}" for a, m in reversed(mois_charges)) +
                                                ". Ouvrez l'onglet « Reporting mensuel ».")
                st.rerun()


# =============================================================================
# Sélection de la période (onglets suivants)
# =============================================================================
real = vals[(vals["nature"] == "realise") & (vals["mois"] > 0)] if not vals.empty else vals
periodes = sorted({(int(a), int(m)) for a, m in real[["annee", "mois"]].itertuples(index=False)}, reverse=True) if not real.empty else []


def pick_period(key):
    if not periodes:
        return None
    default = st.session_state.get("sf_sel")
    idx = periodes.index(default) if default in periodes else 0
    p = st.selectbox("Mois du rapport", periodes, index=idx, key=key,
                     format_func=lambda p: f"{MOIS[p[1] - 1]} {p[0]}")
    st.session_state["sf_sel"] = p
    return p


# =============================================================================
# 2. Reporting mensuel
# =============================================================================
with tabs["📊 Reporting mensuel"]:
    p = pick_period("sf_p_rep")
    if p is None:
        st.info("Aucun mois disponible. " + ("Chargez un mois ou amorcez le référentiel depuis le rapport existant."
                                             if not lecture_seule else "Un analyste doit d'abord charger les fichiers."))
    else:
        annee, n = p
        r26, r25, a25, bud = dicts_for_year(vals, annee)
        mrows = month_rows(vals, annee, n)
        tab = sfb.monthly_table(r26, r25, a25, bud, annee, n)

        src = {k: (mrows.loc[k, "source"] if k in mrows.index else sfb.SRC_ABSENT) for k in sfb.IND_KEYS}
        if not mrows.empty:
            for k in mrows.index:
                if pd.notna(mrows.loc[k, "valeur_saisie"]):
                    src[k] = "Saisie manuelle"
        em = esc[(esc["annee"] == annee) & (esc["mois"] == n)] if not esc.empty else esc

        # Export Excel en haut de page (formules vivantes)
        corr_m = vals[(vals["annee"] == annee) & vals["valeur_saisie"].notna()][
            ["annee", "mois", "indicateur", "nature", "valeur_calculee", "valeur_saisie", "motif", "agent"]] if not vals.empty else None
        det_x = sfb.detail_from_store(em) if not em.empty else None
        ctrl_x = sfb.controles(det_x, {k: r26.get((n, k)) for k in sfb.IND_KEYS}) if det_x is not None else None
        data = sfb.build_export(r26, r25, a25, bud, annee, n, {k: src[k] for k in sfb.IND_KEYS},
                                det_x, ctrl_x, corr_m)
        st.download_button(
            f"⬇️ Télécharger le reporting {MOIS[n - 1].lower()} {annee} (Excel)", data,
            file_name=f"REPORTING_RORO_TEUS_{annee}_{n:02d}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
        st.caption("Onglets : reporting (formules vivantes), détail par navire, contrôles, corrections, sources & règles.")

        # Chiffres clés du mois
        cols = st.columns(5)
        for c, (ind, lab) in zip(cols, [("escales", "Escales"), ("teu", "TEU"), ("roro", "RORO"),
                                        ("neufs", "Neufs"), ("usages", "Usagés")]):
            cur, prev = r26.get((n, ind)), r25.get((n, ind))
            delta = sfb._pct(cur, prev)
            c.metric(lab, fnum(cur), fpct(delta).replace(" %", " % vs N-1") if delta is not None else None)

        # Vue compacte du mois (un seul mois)
        y1 = annee - 1
        view = pd.DataFrame({
            "Groupe": tab["Groupe"],
            "Indicateur": tab["Indicateur"],
            f"{MOIS[n - 1]} {annee}": [fnum(r26.get((n, k))) for k in tab["_ind"]],
            "Budget / mois": tab["Budget / mois"].map(fnum),
            "% R/B": tab["% mois R/B"].map(fpct),
            f"{MOIS[n - 1]} {y1}": tab[f"{MOIS[n - 1]} {y1}"].map(fnum),
            f"% {annee}/{y1}": tab[f"% mois {annee}/{y1}"].map(fpct),
            f"Cumul {annee} ({n} mois)": tab[f"Total {annee} ({n} mois)"].map(fnum),
            f"Cumul {y1} ({n} mois)": tab[f"Total {y1} ({n} mois)"].map(fnum),
            "% cumul": tab[f"% cumul {annee}/{y1}"].map(fpct),
            "Source": [SRC_ICON.get(src[k], src[k]) for k in tab["_ind"]],
        })
        view.loc[view["Groupe"].duplicated(), "Groupe"] = ""
        st.markdown(f"#### {MOIS[n - 1]} {annee}")
        # Colonnes entièrement vides (« — ») masquées par défaut
        vides = [c for c in view.columns if c not in ("Groupe", "Indicateur", "Source")
                 and (view[c] == "—").all()]
        tout = st.toggle("Tout afficher", value=False, key="sf_show_all",
                         help="Affiche aussi les colonnes sans donnée (budget, N-1 ou cumul absents).") if vides else False
        if vides and not tout:
            view = view.drop(columns=vides)
            st.caption("Colonnes masquées (aucune donnée) : " + ", ".join(vides))
        pct_cols = [c for c in ("% R/B", f"% {annee}/{y1}", "% cumul") if c in view.columns]
        st.dataframe(view.style.map(color_pct, subset=pct_cols) if pct_cols else view,
                     hide_index=True, width="stretch", height=(len(view) + 1) * 35 + 3)
        part = tab[tab["_mois_cumules"] < n]
        if not part.empty:
            st.warning(f"Cumul calculé sur les mois disponibles uniquement (moins de {n} mois chargés pour "
                       f"{len(part)} indicateur(s), ex. {part['Indicateur'].iloc[0]} : {int(part['_mois_cumules'].iloc[0])} mois). "
                       "N-1 et budget sont comparés sur les mêmes mois. Chargez les mois manquants pour compléter.")
        if (tab["_base25"] == "proratisé").any():
            st.caption(f"Cumul {y1} : total annuel {y1} ramené à {n} mois (historique mensuel {y1} "
                       "non disponible). « — » : budget ou référence absent.")

        with st.expander(f"Évolution mensuelle {annee} (janvier → décembre)"):
            grid = tab[["Groupe", "Indicateur"] + sfb.MOIS_COURT].copy()
            for m in sfb.MOIS_COURT:
                grid[m] = grid[m].map(fnum)
            # Seuls les mois chargés sont affichés (sauf bascule « Tout afficher »)
            if not st.session_state.get("sf_show_all"):
                grid = grid.drop(columns=[m for m in sfb.MOIS_COURT if (grid[m] == "—").all()])
            grid.loc[grid["Groupe"].duplicated(), "Groupe"] = ""
            st.dataframe(grid, hide_index=True, width="stretch")

        # D'où vient ce chiffre ?
        st.markdown("#### 🔎 D'où vient ce chiffre ?")
        opts = sfb.IND_KEYS
        ind = st.selectbox("Indicateur", opts, key="sf_why",
                           format_func=lambda k: " · ".join(sfb.IND_LABEL[k]))
        row = mrows.loc[ind] if ind in mrows.index else None
        c1, c2 = st.columns([1, 2])
        with c1:
            st.metric(f"{MOIS[n - 1]} {annee}", fnum(r26.get((n, ind))))
            st.markdown(f"**Source** : {SRC_ICON.get(src[ind], src[ind])}")
            if row is not None:
                if pd.notna(row.get("fichier")):
                    st.markdown(f"**Fichier** : {row['fichier']}")
                if pd.notna(row.get("valeur_saisie")):
                    st.markdown(f"**Corrigé à la main** : calculé {fnum(row['valeur_calculee'])} → "
                                f"retenu {fnum(row['valeur_saisie'])}  \n**Motif** : {row.get('motif') or '—'} · "
                                f"**par** {row.get('agent') or '—'}")
                st.caption(f"Mis à jour le {pd.Timestamp(row['horodatage']).strftime('%d/%m/%Y %H:%M')} par {row.get('agent') or '—'}.")
        with c2:
            st.markdown(f"**Règle** : {sfb.regle(ind)}")
            em = esc[(esc["annee"] == annee) & (esc["mois"] == n)] if not esc.empty else esc
            if not em.empty:
                d = sfb.detail_from_store(em)
                if ind == "escales":
                    st.dataframe(d[["navire", "type_navire", "debut", "fin"]].rename(columns={
                        "navire": "Navire", "type_navire": "Type", "debut": "Début", "fin": "Fin"}),
                        hide_index=True, width="stretch")
                elif ind.startswith("h_"):
                    st.caption(f"Total Hinterland du classeur (DT VEH TRANSIT) : **{fnum(d['transit'].sum())}** — "
                               "la répartition par tranche n'existe dans aucun fichier source.")
                    st.dataframe(d.loc[d["transit"] > 0, ["navire", "transit"]].rename(
                        columns={"navire": "Navire", "transit": "Hinterland"}), hide_index=True, width="stretch")
                elif ind in DETAIL_COL:
                    col = DETAIL_COL[ind]
                    if ind.startswith("t_gt50") and src[ind] == sfb.SRC_VOLUMES:
                        col = "sup50_classeur"
                    dd = d if not ind.startswith("l_") else d[d["type_navire"] == "Lo/Lo"]
                    dd = dd.loc[pd.to_numeric(dd[col], errors="coerce").fillna(0) != 0, ["navire", "type_navire", col]]
                    dd = dd.rename(columns={"navire": "Navire", "type_navire": "Type", col: "Contribution"})
                    st.dataframe(dd, hide_index=True, width="stretch")
                    st.caption(f"Somme des navires : **{fnum(pd.to_numeric(dd['Contribution']).sum())}**")
            elif src[ind] == store.SRC_RAPPORT:
                st.caption("Valeur reprise du rapport existant (saisie par les agents) : pas de détail par navire. "
                           "Chargez les fichiers de ce mois pour la recalculer.")


# =============================================================================
# 3. Contrôles
# =============================================================================
with tabs["✅ Contrôles"]:
    p = pick_period("sf_p_ctl")
    if p is None:
        st.info("Aucun mois disponible.")
    else:
        annee, n = p
        r26, *_ = dicts_for_year(vals, annee)
        em = esc[(esc["annee"] == annee) & (esc["mois"] == n)] if not esc.empty else esc
        if em.empty:
            st.info("Pas de détail par navire pour ce mois (valeurs reprises du rapport existant). "
                    "Chargez les fichiers du mois pour activer les contrôles.")
        else:
            d = sfb.detail_from_store(em)
            ctrl = sfb.controles(d, {k: r26.get((n, k)) for k in sfb.IND_KEYS})
            ok, ko = int((ctrl["Statut"] == "OK").sum()), int((ctrl["Statut"] == "À vérifier").sum())
            c1, c2, c3 = st.columns(3)
            c1.metric("Contrôles OK", ok)
            c2.metric("À vérifier", ko)
            c3.metric("À compléter", int((ctrl["Statut"] == "À compléter").sum()))
            icon = {"OK": "🟢 OK", "À vérifier": "🟠 À vérifier", "À compléter": "🔴 À compléter"}
            st.dataframe(ctrl.assign(Statut=ctrl["Statut"].map(icon),
                                     **{c: ctrl[c].map(fnum) for c in ["Valeur rapport", "Valeur de contrôle", "Écart"]}),
                         hide_index=True, width="stretch")
            st.caption("Un écart avec la source est probablement une erreur de saisie dans l'un des fichiers. "
                       "Corrigez la valeur dans l'onglet « Corrections » si nécessaire, en indiquant le motif.")
            st.markdown("#### Détail par navire")
            show = d[["navire", "type_navire", "debut", "fin", "duree_escale_h", "teu", "roro", "neufs",
                      "usages", "transit", "paa_<15", "paa_15-50", "paa_>50", "roro_paa", "ecart_roro"]].rename(columns={
                "navire": "Navire", "type_navire": "Type", "debut": "Début", "fin": "Fin",
                "duree_escale_h": "Durée (h)", "teu": "TEU", "roro": "RORO", "neufs": "Neufs",
                "usages": "Usagés", "transit": "Hinterland", "paa_<15": "PAA <15", "paa_15-50": "PAA 15-50",
                "paa_>50": "PAA >50", "roro_paa": "RORO PAA", "ecart_roro": "Écart"})
            st.dataframe(show.style.map(lambda v: "background-color: #fdf0d5" if isinstance(v, (int, float)) and pd.notna(v) and v != 0 else "",
                                        subset=["Écart"]),
                         hide_index=True, width="stretch",
                         column_config={"Début": st.column_config.DatetimeColumn(format="DD/MM HH:mm"),
                                        "Fin": st.column_config.DatetimeColumn(format="DD/MM HH:mm"),
                                        **{c: st.column_config.NumberColumn(format="%.1f") for c in
                                           ["Durée (h)", "TEU", "RORO", "Neufs", "Usagés", "Hinterland",
                                            "PAA <15", "PAA 15-50", "PAA >50", "RORO PAA", "Écart"]}})


# =============================================================================
# 4. Corrections
# =============================================================================
if "✏️ Corrections" in tabs:
    with tabs["✏️ Corrections"]:
        p = pick_period("sf_p_cor")
        if p is None:
            st.info("Aucun mois disponible.")
        else:
            annee, n = p
            mrows = month_rows(vals, annee, n)
            base = pd.DataFrame({
                "_ind": sfb.IND_KEYS,
                "Indicateur": [" · ".join(sfb.IND_LABEL[k]) for k in sfb.IND_KEYS],
                "Valeur calculée": [mrows.loc[k, "valeur_calculee"] if k in mrows.index else None for k in sfb.IND_KEYS],
                "Source": [SRC_ICON.get(mrows.loc[k, "source"], mrows.loc[k, "source"]) if k in mrows.index else SRC_ICON[sfb.SRC_ABSENT] for k in sfb.IND_KEYS],
                "Valeur retenue": [mrows.loc[k, "valeur_saisie"] if k in mrows.index else None for k in sfb.IND_KEYS],
                "Motif": [mrows.loc[k, "motif"] if k in mrows.index and pd.notna(mrows.loc[k, "motif"]) else "" for k in sfb.IND_KEYS],
            })
            st.caption("Saisissez une valeur dans « Valeur retenue » pour remplacer le calcul, avec un motif. "
                       "Videz la cellule pour revenir à la valeur calculée. Toutes les modifications sont journalisées.")
            ed = st.data_editor(
                base, hide_index=True, width="stretch", key=f"sf_ed_{annee}_{n}",
                disabled=["Indicateur", "Valeur calculée", "Source"],
                column_order=["Indicateur", "Valeur calculée", "Source", "Valeur retenue", "Motif"],
                column_config={"Valeur calculée": st.column_config.NumberColumn(format="%d"),
                               "Valeur retenue": st.column_config.NumberColumn(format="%d", min_value=0),
                               "Motif": st.column_config.TextColumn(width="large")})
            if st.button("💾 Enregistrer les corrections", type="primary"):
                changes, missing = 0, []
                for (_, a), (_, b) in zip(base.iterrows(), ed.iterrows()):
                    va, vb = a["Valeur retenue"], b["Valeur retenue"]
                    same = (pd.isna(va) and pd.isna(vb)) or (pd.notna(va) and pd.notna(vb) and float(va) == float(vb))
                    ma, mb = _txt(a["Motif"]), _txt(b["Motif"])
                    if same and ma == mb:
                        continue
                    if pd.notna(vb) and not mb:
                        missing.append(b["Indicateur"])
                        continue
                    store.save_saisie(annee, n, b["_ind"], "realise", None if pd.isna(vb) else float(vb),
                                      mb, agent,
                                      None if pd.isna(b["Valeur calculée"]) else float(b["Valeur calculée"]),
                                      None if pd.isna(va) else float(va))
                    changes += 1
                if missing:
                    st.error("Motif obligatoire pour : " + ", ".join(missing))
                if changes:
                    st.success(f"{changes} correction(s) enregistrée(s).")
                    st.rerun()
            log = store.load_log()
            if not log.empty:
                st.markdown("#### Journal des corrections")
                lg = log.copy()
                lg["indicateur"] = lg["indicateur"].map(lambda k: " · ".join(sfb.IND_LABEL.get(k, ("", k))))
                st.dataframe(lg, hide_index=True, width="stretch")


# =============================================================================
# 5. Référentiel
# =============================================================================
if "📚 Référentiel" in tabs:
    with tabs["📚 Référentiel"]:
        st.subheader("Historique N-1 et budget")
        st.caption("À faire une fois : chargez le dernier rapport « STATISTIQUES FLASH ET REPORTING RORO ET TEU » "
                   "(.xlsx). L'app reprend les mois déjà publiés, le total N-1, le même mois N-1 et le budget. "
                   "Un mois recalculé depuis ses fichiers n'est jamais écrasé.")
        st.markdown("Nom à chercher : `STATISTIQUES FLASH ET REPORTING RORO ET TEU <MOIS> <AAAA>.xlsx` "
                    "(le dernier rapport publié).")
        f_rep = checked_upload(st.file_uploader("Rapport existant (.xlsx)", type=["xlsx"], key="sf_rep"))
        if f_rep is not None:
            try:
                ref = sfb.parse_rapport_existant(f_rep.getvalue())
            except Exception as exc:
                safe_error("stats_flash: rapport existant", exc, "Rapport non reconnu. Vérifiez qu'il s'agit bien du rapport « STATISTIQUES FLASH ET REPORTING RORO ET TEU ».")
                ref = None
            if ref:
                a = ref["annee"]
                rows = [(a, m, k, "realise", v) for (m, k), v in ref["realise"].items()]
                rows += [(a - 1, 0, k, "realise", v) for k, v in ref["annuel_2025"].items()]
                if ref["mois_ref_2025"]:
                    rows += [(a - 1, ref["mois_ref_2025"], k, "realise", v) for k, v in ref["meme_mois_2025"].items()]
                rows += [(a, 0, k, "budget", v) for k, v in ref["budget"].items()]
                mois_lus = sorted({m for m, _ in ref["realise"]})
                st.info(f"Lu : {len(mois_lus)} mois {a} ({', '.join(MOIS[m - 1] for m in mois_lus)}), "
                        f"total {a - 1}, {MOIS[ref['mois_ref_2025'] - 1].lower() if ref['mois_ref_2025'] else '—'} {a - 1}, budget.")
                if st.button("📥 Reprendre ces valeurs", type="primary"):
                    store.seed_reference(rows, f_rep.name, agent)
                    st.success("Référentiel amorcé.")
                    st.rerun()

        st.markdown("#### Valeurs de référence")
        annee_ref = max([a for a, _ in periodes], default=pd.Timestamp.now().year)
        r26, r25, a25, bud = dicts_for_year(vals, annee_ref)
        ref_df = pd.DataFrame({
            "_ind": sfb.IND_KEYS,
            "Indicateur": [" · ".join(sfb.IND_LABEL[k]) for k in sfb.IND_KEYS],
            f"Budget / mois {annee_ref}": [bud.get(k) for k in sfb.IND_KEYS],
            f"Total annuel {annee_ref - 1}": [a25.get(k) for k in sfb.IND_KEYS],
        })
        ed = st.data_editor(ref_df, hide_index=True, width="stretch", key="sf_ref_ed",
                            disabled=["Indicateur"], column_order=list(ref_df.columns[1:]),
                            column_config={c: st.column_config.NumberColumn(format="%.0f") for c in ref_df.columns[2:]})
        motif = st.text_input("Motif de la modification", key="sf_ref_motif", placeholder="Ex. budget révisé en juin")
        if st.button("💾 Enregistrer le référentiel"):
            if not motif.strip():
                st.error("Indiquez un motif.")
            else:
                n_ch = 0
                for (_, a), (_, b) in zip(ref_df.iterrows(), ed.iterrows()):
                    for col, (yy, mm, nat) in {ref_df.columns[2]: (annee_ref, 0, "budget"),
                                               ref_df.columns[3]: (annee_ref - 1, 0, "realise")}.items():
                        va, vb = a[col], b[col]
                        if (pd.isna(va) and pd.isna(vb)) or (pd.notna(va) and pd.notna(vb) and float(va) == float(vb)):
                            continue
                        store.save_saisie(yy, mm, b["_ind"], nat, None if pd.isna(vb) else float(vb),
                                          motif.strip(), agent, None, None if pd.isna(va) else float(va))
                        n_ch += 1
                st.success(f"{n_ch} valeur(s) enregistrée(s).")
                st.rerun()
