"""Page Stats Flash & Reporting RORO / TEU — bloc mensuel (MVP).

Calcule le bloc « REPORTING RORO & TEUS » à partir des fichiers sources du
mois (classeur volumes + extrait PAA), montre d'où vient chaque chiffre,
contrôle la cohérence, accepte des corrections manuelles tracées et exporte
le rapport au format Excel habituel (formules vivantes).

Accès : analystes (complet) ; direction et agents (lecture). Voir
claude/ANALYSE_CLASSEUR_FLASH_AOUT_SEPT_2026.md (projet Claude) pour les
règles validées.
"""
import html
import pathlib
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import stats_flash_builder as sfb
import fiche_paa_parser as fpp
import flash_hebdo as fh
import navires_prevus as npv
import note_mensuelle as nm
import stats_flash_parser as sfp
import tracking
import hinterland_tranches as htr
import stats_store as store
import donnees_dispo as ddispo
from ui_helpers import (PLOT_TEMPLATE, TERRA, current_access_role, current_identity, empty_state, help_expander,
                        hover_lines, kpi_card, kpi_row, section_header, vue_switch, etat_donnees_html,
                        rappel_donnees, icon, periode_selector, mois_jusqua)
from security_utils import checked_upload, filter_uploads, filter_uploads_zip, safe_error

MOIS = [m.capitalize() for m in sfp.MOIS_FR]
SRC_ICON = {
    sfb.SRC_VOLUMES: "Classeur volumes",
    sfb.SRC_PAA: "Extrait PAA",
    "Saisie manuelle": "Saisie manuelle",
    store.SRC_RAPPORT: "Rapport existant",
    sfb.SRC_ABSENT: "À compléter",
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
@st.cache_data(show_spinner="Lecture des fiches PAA…", max_entries=8)
def _lire_fiches(fichiers: tuple):
    return fpp.lire_fiches(list(fichiers))


@st.cache_data(ttl=60, show_spinner=False)
def _read_log():
    """Journal des traitements, lu une fois par minute au lieu de trois fois par clic."""
    return tracking.read_log()


@st.cache_data(ttl=60, show_spinner=False)
def _list_suivi():
    """ETA saisies ; cache vidé dès qu'une ETA est enregistrée."""
    return tracking.list_suivi_escales()


def _hint_ref():
    """Hinterland par tranche issu des manifestes traités (vide si indisponible)."""
    try:
        suivi = _list_suivi()
    except Exception:
        suivi = None
    return htr.reference(htr.load(), suivi)


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

with help_expander(":material/info: Comment lire cette page et d'où viennent les chiffres"):
    st.markdown(
        "- **Charger un mois** : déposez le(s) classeur(s) des volumes et le(s) extrait(s) PAA — un ou plusieurs mois "
        "d'un coup, chaque fichier est rattaché à son mois. Les contrôles s'affichent avant l'enregistrement.\n"
        "- **Reporting mensuel** : le bloc du rapport, avec cumul, comparaison N-1 et budget. "
        "La colonne Source indique l'origine de chaque valeur : classeur, PAA, saisie manuelle ou rapport existant.\n"
        "- **Contrôles** : points à vérifier (écarts entre le classeur et le PAA).\n"
        "- **Corrections** : toute valeur peut être corrigée, avec motif ; la correction est conservée "
        "aux rechargements.\n\n"
        "**Règles de calcul**\n\n"
        + "\n".join(f"- **{' · '.join(sfb.IND_LABEL[k])}** : {sfb.regle(k)}" for k in sfb.IND_KEYS
                    if k in ("escales", "teu", "roro", "neufs", "usages", "t_lt15", "h_lt15", "l_lt15")))

vals, esc = load_all()
etat_d = ddispo.etat(vals, esc)
rappel_donnees(etat_d, "l'onglet « Charger un mois »" if not lecture_seule else "un analyste")

tabs_names = [":material/bar_chart: Reporting mensuel", ":material/check_circle: Contrôles", ":material/directions_boat: Navires prévus", ":material/calendar_month: Flash hebdo"]
if not lecture_seule:
    tabs_names = [":material/download: Charger un mois"] + tabs_names + [":material/edit: Corrections", ":material/menu_book: Référentiel"]
tabs = dict(zip(tabs_names, st.tabs(tabs_names)))


# =============================================================================
# 1. Charger un mois
# =============================================================================
if ":material/download: Charger un mois" in tabs:
    with tabs[":material/download: Charger un mois"]:
        # ── État des données : disponible / à compléter ──
        _r0 = vals[(vals["nature"] == "realise") & (vals["mois"] > 0)] if not vals.empty else vals
        _avec = sorted({(int(a), int(m)) for a, m in _r0[["annee", "mois"]].itertuples(index=False)}, reverse=True) if not vals.empty else []
        _tous = mois_jusqua(_avec)
        _sel = periode_selector(_tous, "sf_p_chg", manquantes=[x for x in _tous if x not in set(_avec)])
        an_sel = _sel[0] if _sel else etat_d["annee"]
        if an_sel != etat_d["annee"]:
            etat_d = ddispo.etat(vals, esc, annee=an_sel)
        _ouvert = bool(etat_d["manquants"])
        with st.expander(f"État des données {etat_d['annee']} · {etat_d['resume']}", icon=":material/grid_view:", expanded=_ouvert):
            st.markdown(etat_donnees_html(etat_d, ddispo.DONNEES), unsafe_allow_html=True)
            if etat_d["manquants"]:
                st.markdown(
                    "<div class='t-list' style='border-color:#F6CB95'>"
                    f"<div class='t-li'><b style='color:#6B3A00'>À compléter ({len(etat_d['manquants'])})</b></div>"
                    + "".join(f"<div class='t-li'><div class='t-li-main'><b>{html.escape(m['quoi'])}</b>"
                              f"<span style='white-space:normal'>{html.escape(m['effet'])}</span></div>"
                              f"<span class='t-li-right' style='color:#8A4B00;font-weight:600'>{html.escape(m['ou'])}</span></div>"
                              for m in etat_d["manquants"]) + "</div>", unsafe_allow_html=True)

        # ── Dépôt unique : le type et le mois de chaque fichier sont reconnus ──
        section_header("Déposer les fichiers", "classeurs des volumes et extraits PAA, un ou plusieurs mois en une fois")
        MAX_FICHIERS = 12   # garde-fou mémoire (Streamlit Cloud gratuit)
        f_all = st.file_uploader(
            "Déposez tous les fichiers du mois en une fois", type=["xls", "xlsx", "zip"], key="sf_files",
            accept_multiple_files=True, label_visibility="collapsed",
            help="Le type de chaque fichier (classeur des volumes ou extrait PAA) et son mois sont reconnus "
                 "automatiquement. Plusieurs mois possibles. Un .zip est accepté (20 fichiers .xls/.xlsx "
                 "au plus, 25 Mo par fichier, 100 Mo au total).")
        with st.expander(":material/folder_open: Où trouver les fichiers dans SharePoint", expanded=False):
            st.markdown(
                "| Fichier | Dossier SharePoint | Ce qu'il apporte |\n|---|---|---|\n"
                "| **1. Classeur des volumes** (nom : *VOLUMES D'ACTIVITES … ELVIS*) | "
                f"`PAA - KOUAI EDEN SUPER U` › `Dossiers PAA <Mois> {an_sel}`<br>ou, pour le classeur « STATS FLASH », "
                "`PLANIFICATION & REPORTING` › `DOSSIERS REPORTING` › `REPORTING` › "
                f"`STATS FLASH VOLUMES TCS BOLS MAFIS ET VEHICULES OPN` › `{an_sel}` › `<MOIS>` | "
                "Escales, TEU, véhicules, neufs / usagés, Hinterland |\n"
                "| **2. Extrait PAA** (nom : *STATISTIQUES TERRA <MOIS>*) | "
                f"`PLANIFICATION & REPORTING` › `DOSSIERS REPORTING` › `REPORTING` › `STATISTIQUES TERRA {an_sel}` | "
                "Tranches de volume (< 15, 15-50, > 50 m³) et trafic Lo/Lo |\n\n"
                "Vous pouvez déposer **plusieurs mois à la fois** : l'app lit le mois dans chaque fichier et rapproche le classeur "
                "de l'extrait PAA du même mois. "
                "Si le dossier du mois paraît vide, la synchronisation SharePoint n'est probablement pas faite "
                "(clic droit › « Toujours conserver sur cet appareil »).",
                unsafe_allow_html=True)
        f_all = filter_uploads_zip(f_all)
        if len(f_all) > MAX_FICHIERS:
            st.warning(f"{len(f_all)} fichiers déposés : seuls les {MAX_FICHIERS} premiers sont traités. "
                       "Chargez le reste ensuite.")
            del f_all[MAX_FICHIERS:]

        # --- Reconnaissance de chaque fichier, regroupés par mois -----------------
        vols, paas = {}, {}      # (annee, mois) -> (fichier, résultat)
        reconnus = []            # (nom, type, mois ou message, statut)

        def _reconnaitre(f):
            """Essaie le lecteur le plus probable d'après le nom, puis l'autre."""
            ordre = [("paa", _parse_paa), ("vol", _parse_vol)]
            if "STATISTIQUES" not in f.name.upper():
                ordre.reverse()
            erreurs = []
            for kind, fn in ordre:
                try:
                    return kind, fn(f.getvalue(), f.name), None
                except sfp.SourceError as exc:
                    erreurs.append(str(exc))
            return None, None, erreurs[0] if erreurs else "format inconnu"

        for f in f_all:
            kind, r, err = _reconnaitre(f)
            if kind is None:
                reconnus.append((f.name, "Fichier non reconnu", f"ni classeur des volumes, ni extrait PAA : ignoré ({err})", "ko"))
                continue
            if kind == "paa" and r.mois is None:
                reconnus.append((f.name, "Extrait PAA", "mois introuvable (dates de début absentes) : ignoré", "ko"))
                continue
            cible, lib = (vols, "Classeur des volumes") if kind == "vol" else (paas, "Extrait PAA")
            per = (r.annee, r.mois)
            if per in cible:
                reconnus.append((f.name, lib, f"{MOIS[r.mois - 1]} {r.annee} déjà déposé (« {cible[per][0].name} ») : ignoré", "ko"))
                continue
            cible[per] = (f, r)
            _ch = st.session_state.get("sf_sel")
            _diff = f" · différent du mois choisi ({MOIS[_ch[1] - 1]} {_ch[0]})" if _ch and _ch != per else ""
            reconnus.append((f.name, lib, f"{MOIS[r.mois - 1]} {r.annee}{_diff}", "ok"))
        if reconnus:
            st.markdown("<div class='t-list'>" + "".join(
                f"<div class='t-li'>{icon('check' if s == 'ok' else 'alert', 16, '#0B7A2E' if s == 'ok' else '#A85600')}"
                f"<div class='t-li-main'><b>{html.escape(lib)}</b><span>{html.escape(nom)}</span></div>"
                f"<span class='t-li-right'>{html.escape(info)}</span></div>"
                for nom, lib, info, s in reconnus) + "</div>", unsafe_allow_html=True)

        mois_charges = sorted(set(vols) | set(paas), reverse=True)

        def _save_month(per):
            """Enregistre un mois (classeur + PAA éventuel) ou, sans classeur, les tranches PAA seules."""
            a_, m_ = per
            if per in vols:
                f_v, vol = vols[per]
                f_p, paa = paas.get(per, (None, None))
                calc, det = sfb.compute_month(vol, paa, _hint_ref())
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
            with st.expander(f":material/calendar_month: {titre}", expanded=len(mois_charges) == 1):
                if per in vols:
                    f_v, vol = vols[per]
                    f_p, paa = paas.get(per, (None, None))
                    calc, det = sfb.compute_month(vol, paa, _hint_ref())
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
                    if st.button(f":material/save: Enregistrer {titre}", type="primary", key=f"sf_save_{a_}_{m_}"):
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
                    if st.button(f":material/save: Enregistrer les tranches de {titre}", type="primary",
                                 key=f"sf_save_paa_seul_{a_}_{m_}"):
                        _save_month(per)
                        st.session_state["sf_sel"] = per
                        st.session_state["sf_flash"] = f"Tranches de {titre} enregistrées. Ouvrez l'onglet « Reporting mensuel »."
                        st.rerun()

        if len(mois_charges) > 1:
            if st.button(f":material/save: Enregistrer les {len(mois_charges)} mois", type="primary", key="sf_save_all"):
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
    return periode_selector(periodes, key)


# =============================================================================
# Correction par escale (« correction à l'escale d'abord, total en secours »)
# =============================================================================
CORRIGEABLE_ESCALE = {k for k in DETAIL_COL}          # pas les escales ni l'hinterland par tranche
MOTIFS_ESCALE = ["Erreur de saisie agent", "Fichier source incomplet", "Escale manquante ou en double", "Autre (préciser)"]
MOTIF_TOTAL_ESCALES = "Recalculé depuis les corrections par escale"
corr_esc = store.load_corr_escales()


def correction_escale(annee, n, ind, contrib_all, total_actuel, row):
    """Formulaire de correction d'une escale ; recalcule le total du mois."""
    lab = " · ".join(sfb.IND_LABEL[ind])
    with st.expander("Corriger une escale", icon=":material/edit:"):
        nav = st.selectbox("Escale", contrib_all["navire"].tolist(), key=f"sf_ce_nav_{annee}_{n}_{ind}",
                           format_func=lambda x: x + (" (corrigée)" if bool(contrib_all.loc[contrib_all["navire"] == x, "corrige"].iloc[0]) else ""))
        r = contrib_all[contrib_all["navire"] == nav].iloc[0]
        with st.form(f"sf_ce_form_{annee}_{n}_{ind}", border=False):
            c1, c2 = st.columns(2)
            c1.number_input("Valeur calculée", value=float(r["calc"]), disabled=True, format="%.0f")
            nv = c2.number_input("Valeur retenue", value=float(r["c"]), min_value=0.0, step=1.0, format="%.0f")
            motif = st.selectbox("Motif (obligatoire)", MOTIFS_ESCALE, index=None, placeholder="Choisir un motif")
            prec = st.text_input("Précision (facultatif)", placeholder="Ex. B/L compté deux fois")
            b1, b2 = st.columns(2)
            ok = b1.form_submit_button("Enregistrer la correction", type="primary", width="stretch")
            annule = b2.form_submit_button("Revenir au calcul", width="stretch", disabled=not bool(r["corrige"]))
        st.caption(f"Tracée dans Corrections (auteur, date, motif) et conservée aux rechargements. Indicateur : {lab}.")
    if not (ok or annule):
        return
    if ok and not motif:
        st.error("Motif obligatoire.")
        return
    if ok and motif == MOTIFS_ESCALE[-1] and not prec.strip():
        st.error("Précisez le motif « Autre ».")
        return
    nouvelle = None if annule else float(nv)
    enregistrer_corr_escale(annee, n, ind, contrib_all, nav, nouvelle, motif or "Annulation", prec.strip(),
                            total_actuel, row)


def enregistrer_corr_escale(annee, n, ind, contrib_all, nav, nouvelle, motif, prec, total_actuel, row):
    """Enregistre (ou annule si nouvelle=None) la correction d'une escale, puis
    recalcule le total du mois = somme des escales, corrections comprises."""
    r = contrib_all[contrib_all["navire"] == nav].iloc[0]
    store.save_corr_escale(annee, n, nav, ind, float(r["calc"]), nouvelle, motif, prec, agent, float(r["c"]))
    contrib_all = contrib_all.copy()
    contrib_all.loc[contrib_all["navire"] == nav, ["c", "corrige"]] = [r["calc"] if nouvelle is None else nouvelle,
                                                                        nouvelle is not None]
    reste_corr = bool(contrib_all["corrige"].any())
    deja = row is not None and pd.notna(row.get("valeur_saisie"))
    if reste_corr:
        store.save_saisie(annee, n, ind, "realise", float(contrib_all["c"].sum()), MOTIF_TOTAL_ESCALES, agent,
                          None if row is None else row.get("valeur_calculee"), total_actuel)
    elif deja and row.get("motif") == MOTIF_TOTAL_ESCALES:
        store.save_saisie(annee, n, ind, "realise", None, "Annulation des corrections par escale", agent,
                          row.get("valeur_calculee"), total_actuel)
    st.toast("Correction enregistrée, total recalculé.", icon=":material/check:")
    st.rerun()


def contributions(annee, n, ind):
    """Contribution de chaque escale du mois à un indicateur corrigeable,
    corrections par escale appliquées (colonnes navire, calc, c, corrige)."""
    em_ = esc[(esc["annee"] == annee) & (esc["mois"] == n)] if not esc.empty else esc
    if em_.empty or ind not in DETAIL_COL:
        return None
    d_ = sfb.detail_from_store(em_)
    col = DETAIL_COL[ind]
    if ind.startswith("l_"):
        d_ = d_[d_["type_navire"] == "Lo/Lo"]
    c = d_[["navire"]].assign(calc=pd.to_numeric(d_[col], errors="coerce").fillna(0).values)
    c = c.assign(c=c["calc"], corrige=False)
    ce = corr_esc[(corr_esc["annee"] == annee) & (corr_esc["mois"] == n) & (corr_esc["indicateur"] == ind)] \
        if not corr_esc.empty else corr_esc
    if not ce.empty:
        ce = ce.set_index("navire")
        hit = c["navire"].isin(ce.index)
        c.loc[hit, "c"] = c.loc[hit, "navire"].map(ce["valeur_retenue"]).astype(float)
        c.loc[hit, "corrige"] = True
    return c


def detail_corrige(d_, annee, n):
    """Détail par navire avec les corrections par escale appliquées (pour les contrôles)."""
    if corr_esc.empty:
        return d_
    d_ = d_.copy()
    ce = corr_esc[(corr_esc["annee"] == annee) & (corr_esc["mois"] == n)]
    for r in ce.itertuples():
        col = DETAIL_COL.get(r.indicateur)
        if col and col in d_:
            d_.loc[d_["navire"] == r.navire, col] = float(r.valeur_retenue)
    if "roro_paa" in d_:
        d_["ecart_roro"] = pd.to_numeric(d_["roro"], errors="coerce") - pd.to_numeric(d_["roro_paa"], errors="coerce")
    return d_


# =============================================================================
# 2. Reporting mensuel
# =============================================================================
with tabs[":material/bar_chart: Reporting mensuel"]:
    c_per, c_x, c_pdf = st.columns([2, 1, 1], vertical_alignment="bottom")
    with c_per:
        p = pick_period("sf_p_rep")
    if p is None:
        st.info("Aucun mois disponible. " + ("Chargez un mois ou amorcez le référentiel depuis le rapport existant."
                                             if not lecture_seule else "Un analyste doit d'abord charger les fichiers."))
    else:
        annee, n = p
        y1 = annee - 1
        r26, r25, a25, bud = dicts_for_year(vals, annee)
        mrows = month_rows(vals, annee, n)
        tab = sfb.monthly_table(r26, r25, a25, bud, annee, n)

        src = {k: (mrows.loc[k, "source"] if k in mrows.index else sfb.SRC_ABSENT) for k in sfb.IND_KEYS}
        if not mrows.empty:
            for k in mrows.index:
                if pd.notna(mrows.loc[k, "valeur_saisie"]):
                    src[k] = "Saisie manuelle"
        em = esc[(esc["annee"] == annee) & (esc["mois"] == n)] if not esc.empty else esc

        # ── Exports (en-tête, à droite de la période) ──
        corr_m = vals[(vals["annee"] == annee) & vals["valeur_saisie"].notna()][
            ["annee", "mois", "indicateur", "nature", "valeur_calculee", "valeur_saisie", "motif", "agent"]] if not vals.empty else None
        det_x = sfb.detail_from_store(em) if not em.empty else None
        ctrl_x = sfb.controles(det_x, {k: r26.get((n, k)) for k in sfb.IND_KEYS}) if det_x is not None else None
        data = sfb.build_export(r26, r25, a25, bud, annee, n, {k: src[k] for k in sfb.IND_KEYS},
                                det_x, ctrl_x, corr_m)
        with c_x:
            st.download_button(
                "Exporter Excel", data, icon=":material/download:", type="primary", width="stretch",
                file_name=f"REPORTING_RORO_TEUS_{annee}_{n:02d}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                help="Onglets : reporting (formules vivantes), détail par navire, contrôles, corrections, sources & règles.")
        try:
            pv = npv.build_prevus(_read_log(), _list_suivi(), esc)
            pv = pv[pv["statut"] != "Réalisé"]
            prevus_note = ({"navires": len(pv), "vehicules": pv["vehicules"].sum(), "hinterland": pv["hinterland"].sum(),
                            "sans_eta": int((pv["statut"] == "Prévu (sans ETA)").sum())} if not pv.empty else None)
        except Exception:
            prevus_note = None
        with c_pdf:
            try:
                note_pdf = nm.build_note(annee, n, tab, r26, r25, bud, src, corr_m, ctrl_x, prevus_note, agent)
                st.download_button(
                    "Note direction (PDF)", note_pdf, icon=":material/description:", width="stretch",
                    file_name=f"NOTE_RORO_TEUS_{annee}_{n:02d}.pdf", mime="application/pdf",
                    help="Mêmes lignes que le rapport, plus lecture rapide, graphiques et écarts. Sections sans donnée omises.")
            except Exception as exc:
                safe_error("note mensuelle PDF", exc, "La note PDF n'a pas pu être générée.")

        # ── Chiffres clés ──
        hint = lambda d, a, b, c: None if any(d.get(x) is None for x in (a, b, c)) else d[a] + d[b] + d[c]
        r26h = {**r26, (n, "hinterland"): hint({k: r26.get((n, k)) for k in ("h_lt15", "h_15_50", "h_gt50")},
                                               "h_lt15", "h_15_50", "h_gt50")}
        r25h = {**r25, (n, "hinterland"): hint({k: r25.get((n, k)) for k in ("h_lt15", "h_15_50", "h_gt50")},
                                               "h_lt15", "h_15_50", "h_gt50")}
        budh = {**bud, "hinterland": hint(bud, "h_lt15", "h_15_50", "h_gt50")}
        kpi_row([kpi_card(lab, r26h.get((n, k)), r25h.get((n, k)), budh.get(k), ic, i)
                 for i, (k, lab, ic) in enumerate([("escales", "Escales", "anchor"), ("roro", "RORO", "car"),
                                                   ("teu", "TEU", "container"), ("neufs", "Véhicules neufs", "tag"),
                                                   ("hinterland", "Hinterland", "globe")])])

        # ── Lignes du rapport (vides masquées par défaut) ──
        lignes = []
        for k in sfb.IND_KEYS:
            g, lib = sfb.IND_LABEL[k]
            v, v1, b = r26.get((n, k)), r25.get((n, k)), bud.get(k)
            lignes.append({"k": k, "groupe": g, "lib": lib.capitalize() if lib.isupper() else lib, "v": v, "v1": v1, "b": b,
                           "vide": v in (None, 0) and v1 in (None, 0)})
        nb_vides = sum(l["vide"] for l in lignes)

        g_col, d_col = st.columns([3, 2], gap="large")
        with g_col.container(border=True):
            h1, h2, h3 = st.columns([2.2, 1.4, 1.8], vertical_alignment="center")
            with h1:
                section_header(f"Reporting RORO & TEU · {MOIS[n - 1].lower()} {annee}",
                               "survolez pour le détail, cliquez pour la provenance",
                               f"Stats Flash · {MOIS[n - 1].lower()} {annee}")
            with h2:
                tout = st.toggle("Afficher les vides", value=False, key="sf_show_all") if nb_vides else True
            with h3:
                graphique = vue_switch("sf_rep_vue")
            visibles = [l for l in lignes if tout or not l["vide"]]

            if graphique:
                # Barre « bullet » par indicateur, chaque ligne à sa propre échelle
                # (RORO en milliers, escales en dizaines) : la largeur dit l'atteinte
                # du budget, les valeurs exactes sont dans l'info-bulle et à droite.
                ys = [[l["groupe"] for l in visibles], [l["lib"] for l in visibles]]
                def scale(l):
                    return max([x for x in (l["v"], l["v1"], l["b"]) if x is not None] or [1]) or 1
                def pc(x, l):
                    return None if x is None else x / scale(l) * 100
                dans = [pc(min(l["v"], l["b"]) if l["v"] is not None and l["b"] is not None else l["v"], l) for l in visibles]
                audela = [pc(l["v"] - l["b"], l) if l["v"] is not None and l["b"] is not None and l["v"] > l["b"] else 0 for l in visibles]
                reste = [pc(l["b"] - l["v"], l) if l["v"] is not None and l["b"] is not None and l["v"] < l["b"] else 0 for l in visibles]
                cd = [[l["k"], fnum(l["v"]), fnum(l["v1"]), fnum(l["b"]),
                       fpct(sfb._pct(l["v"], l["v1"])) + " vs N-1",
                       ("Budget atteint" if l["v"] is not None and l["b"] and l["v"] >= l["b"]
                        else f"Reste {fnum(l['b'] - l['v'])} pour le budget" if l["v"] is not None and l["b"] else "Pas de budget")]
                      for l in visibles]
                ht = hover_lines("%{y}", [(f"{MOIS[n - 1][:4]}. {annee}", "%{customdata[1]}"),
                                          (f"{MOIS[n - 1][:4]}. {y1}", "%{customdata[2]}"),
                                          ("Budget", "%{customdata[3]}"), ("Écart", "%{customdata[4]}")],
                                 "%{customdata[5]}")
                fig = go.Figure()
                fig.add_bar(y=ys, x=dans, orientation="h", name="Réalisé", marker_color=TERRA["green"],
                            customdata=cd, hovertemplate=ht)
                fig.add_bar(y=ys, x=audela, orientation="h", name="Au-delà du budget", marker_color=TERRA["orange"],
                            customdata=cd, hovertemplate=ht)
                fig.add_bar(y=ys, x=reste, orientation="h", name="Reste pour le budget", marker_color="#E3EAE4",
                            customdata=cd, hovertemplate=ht)
                fig.add_scatter(y=ys, x=[pc(l["b"], l) for l in visibles], mode="markers", name="Budget",
                                marker=dict(symbol="line-ns", size=22, line=dict(width=3, color=TERRA["ink"])),
                                customdata=cd, hovertemplate=ht)
                fig.add_scatter(y=ys, x=[pc(l["v1"], l) for l in visibles], mode="markers", name=f"{MOIS[n - 1][:4]}. {y1}",
                                marker=dict(symbol="diamond", size=10, color="#7C877F", line=dict(color="white", width=1.5)),
                                customdata=cd, hovertemplate=ht)
                fig.add_scatter(y=ys, x=[105] * len(visibles), mode="text", text=[fnum(l["v"]) for l in visibles],
                                textposition="middle right", textfont=dict(size=13, color=TERRA["text"]),
                                hoverinfo="skip", showlegend=False)
                fig.update_layout(template=PLOT_TEMPLATE, barmode="stack", height=46 * len(visibles) + 90,
                                  margin=dict(t=10, l=10, r=10, b=10), bargap=0.45,
                                  xaxis=dict(visible=False, range=[0, 125]),
                                  yaxis=dict(autorange="reversed", tickfont=dict(size=12)),
                                  legend=dict(orientation="h", y=-0.04, x=0))
                ev = st.plotly_chart(fig, width="stretch", config={"displayModeBar": False},
                                     on_select="rerun", selection_mode="points", key="sf_bullet")
                pts = (ev or {}).get("selection", {}).get("points", []) if ev else []
                if pts:
                    clic = (pts[0].get("customdata") or [None])[0]
                    if clic and clic != st.session_state.get("_sf_last_clic"):
                        st.session_state["_sf_last_clic"] = clic
                        st.session_state["sf_why"] = clic
            else:
                view = pd.DataFrame({
                    "Groupe": tab["Groupe"], "Indicateur": tab["Indicateur"],
                    f"{MOIS[n - 1]} {annee}": [r26.get((n, k)) for k in tab["_ind"]],
                    f"{MOIS[n - 1]} {y1}": tab[f"{MOIS[n - 1]} {y1}"],
                    "Écart %": tab[f"% mois {annee}/{y1}"].map(lambda x: None if x is None or pd.isna(x) else x * 100),
                    "Budget / mois": tab["Budget / mois"],
                    "Atteinte %": tab["% mois R/B"].map(lambda x: None if x is None or pd.isna(x) else (1 + x) * 100),
                    f"Cumul {annee}": tab[f"Total {annee} ({n} mois)"],
                    f"Cumul {y1}": tab[f"Total {y1} ({n} mois)"],
                    "Source": [SRC_ICON.get(src[k], src[k]) for k in tab["_ind"]],
                })
                if not tout:
                    view = view[[not l["vide"] for l in lignes]]
                vides = [c for c in view.columns if c not in ("Groupe", "Indicateur", "Source") and view[c].isna().all()]
                if not tout:
                    view = view.drop(columns=vides)
                view = view.copy()
                view.loc[view["Groupe"].duplicated(), "Groupe"] = ""
                num = st.column_config.NumberColumn(format="localized")
                st.dataframe(view, hide_index=True, width="stretch", height=(len(view) + 1) * 35 + 3,
                             column_config={**{c: num for c in view.columns if c not in ("Groupe", "Indicateur", "Source",
                                                                                         "Écart %", "Atteinte %")},
                                            "Écart %": st.column_config.NumberColumn(format="%+.1f %%"),
                                            "Atteinte %": st.column_config.NumberColumn(format="%.0f %%")})
                if vides and not tout:
                    st.caption("Colonnes vides masquées : " + ", ".join(vides))
            if nb_vides and not tout:
                st.caption(f"{nb_vides} ligne(s) sans donnée masquée(s). Activez « Afficher les vides » pour les voir.")
            part = tab[tab["_mois_cumules"] < n]
            if not part.empty:
                st.warning(f"Cumul calculé sur les mois disponibles uniquement (ex. {part['Indicateur'].iloc[0]} : "
                           f"{int(part['_mois_cumules'].iloc[0])} mois sur {n}). N-1 et budget sont comparés sur les mêmes mois.")
            if (tab["_base25"] == "proratisé").any():
                st.caption(f"Cumul {y1} : total annuel {y1} ramené à {n} mois (historique mensuel {y1} non disponible).")

        # ── D'où vient ce chiffre ? ──
        with d_col.container(border=True):
            if st.session_state.get("sf_why") not in sfb.IND_KEYS:
                st.session_state["sf_why"] = "roro"
            ind = st.selectbox("D'où vient ce chiffre ?", sfb.IND_KEYS, key="sf_why",
                               format_func=lambda k: " · ".join(sfb.IND_LABEL[k]))
            row = mrows.loc[ind] if ind in mrows.index else None
            fichier = row.get("fichier") if row is not None and pd.notna(row.get("fichier")) else None
            section_header(" · ".join(sfb.IND_LABEL[ind]), None,
                           f"{SRC_ICON.get(src[ind], src[ind])}" + (f" · {fichier}" if fichier else ""))
            st.markdown(f"<div style='font-size:2rem;font-weight:600;line-height:1.1'>{fnum(r26.get((n, ind)))}</div>"
                        f"<div style='color:{TERRA['muted']}'>{MOIS[n - 1].lower()} {annee}"
                        + (f" · {len(em)} escales" if not em.empty else "") + "</div>", unsafe_allow_html=True)
            st.caption(f"Règle : {sfb.regle(ind)}")

            contrib = None
            if not em.empty:
                d = sfb.detail_from_store(em)
                if ind == "escales":
                    contrib = d.assign(c=1)[["navire", "c"]]
                elif ind.startswith("h_"):
                    contrib = d.loc[d["transit"] > 0, ["navire", "transit"]].rename(columns={"transit": "c"})
                    st.caption(f"Hinterland total du classeur : {fnum(d['transit'].sum())}. "
                               "La répartition par tranche n'existe dans aucun fichier source.")
                elif ind in DETAIL_COL:
                    col = DETAIL_COL[ind]
                    if ind.startswith("t_gt50") and src[ind] == sfb.SRC_VOLUMES:
                        col = "sup50_classeur"
                    dd = d if not ind.startswith("l_") else d[d["type_navire"] == "Lo/Lo"]
                    contrib = dd[["navire", col]].rename(columns={col: "c"})
                if contrib is not None:
                    contrib = contrib.assign(c=pd.to_numeric(contrib["c"], errors="coerce").fillna(0),
                                             calc=lambda x: pd.to_numeric(x["c"], errors="coerce").fillna(0),
                                             corrige=False)
                    if ind in CORRIGEABLE_ESCALE and not corr_esc.empty:
                        ce = corr_esc[(corr_esc["annee"] == annee) & (corr_esc["mois"] == n)
                                      & (corr_esc["indicateur"] == ind)].set_index("navire")
                        hit = contrib["navire"].isin(ce.index)
                        contrib.loc[hit, "c"] = contrib.loc[hit, "navire"].map(ce["valeur_retenue"]).astype(float)
                        contrib.loc[hit, "corrige"] = True
                    contrib_all = contrib.copy()
                    contrib = contrib[(contrib["c"] != 0) | contrib["corrige"]].sort_values("c", ascending=False)
            if contrib is not None and not contrib.empty and ind != "escales":
                top = float(contrib["c"].max()) or 1
                items = "".join(
                    f'<div class="t-li"><div class="t-li-main"><b>{html.escape(str(r.navire))}</b>'
                    + (f' <span style="font-size:11px;font-weight:600;color:#8A4B00;background:#FDEBD3;border-radius:6px;'
                       f'padding:1px 6px">corrigé · calculé {fnum(r.calc)}</span>' if r.corrige else "")
                    + f'<div style="height:6px;border-radius:3px;background:#EEF2EE;margin-top:4px">'
                    f'<div style="height:6px;border-radius:3px;width:{r.c / top * 100:.0f}%;background:{TERRA["green"]}"></div></div>'
                    f'</div><span class="t-li-right"><b style="color:{TERRA["text"]}">{fnum(r.c)}</b></span></div>'
                    for r in contrib.itertuples())
                st.markdown(f'<div class="t-list" style="max-height:420px;overflow-y:auto">{items}</div>',
                            unsafe_allow_html=True)
                st.caption(f"Somme des escales : {fnum(contrib['c'].sum())}")
                if not lecture_seule and ind in CORRIGEABLE_ESCALE:
                    correction_escale(annee, n, ind, contrib_all, r26.get((n, ind)), row)
            elif contrib is not None and ind == "escales":
                st.dataframe(d[["navire", "type_navire", "debut", "fin"]].rename(columns={
                    "navire": "Navire", "type_navire": "Type", "debut": "Début", "fin": "Fin"}),
                    hide_index=True, width="stretch")
            elif src[ind] == store.SRC_RAPPORT:
                empty_state("Pas de détail par escale", "Valeur reprise du rapport existant. "
                            "Chargez les fichiers du mois pour la recalculer.", "database")

            if row is not None and pd.notna(row.get("valeur_saisie")):
                st.info(f"Corrigé à la main : calculé {fnum(row['valeur_calculee'])}, retenu {fnum(row['valeur_saisie'])}. "
                        f"Motif : {row.get('motif') or '—'} ({row.get('agent') or '—'}).", icon=":material/edit:")
            if not lecture_seule:
                st.caption("Une escale fausse ? Corrigez-la ci-dessus : le total se recalcule. En dernier recours, "
                           "corrigez le total dans l'onglet **Corrections** (cela masque l'erreur d'origine).")


# =============================================================================
# 3. Contrôles
# =============================================================================
with tabs[":material/check_circle: Contrôles"]:
    p = pick_period("sf_p_ctl")
    if p is None:
        st.info("Aucun mois disponible.")
    else:
        annee, n = p
        r26, *_ = dicts_for_year(vals, annee)
        mrows_c = month_rows(vals, annee, n)
        em = esc[(esc["annee"] == annee) & (esc["mois"] == n)] if not esc.empty else esc
        if em.empty:
            empty_state("Contrôles indisponibles", "Pas de détail par navire pour ce mois (valeurs reprises du rapport "
                        "existant). Chargez les fichiers du mois pour activer les contrôles.", "check")
        else:
            d = detail_corrige(sfb.detail_from_store(em), annee, n)
            ctrl = sfb.controles(d, {k: r26.get((n, k)) for k in sfb.IND_KEYS})
            lg = store.load_log()
            acceptes = set()
            if not lg.empty:
                la = lg[(lg["annee"] == annee) & (lg["mois"] == n) & (lg["indicateur"] == store.IND_CONTROLE)]
                acceptes = {str(m).removeprefix(store.MOTIF_ACCEPTE) for m in la["motif"].dropna()}
            # ETA manquantes : comptées dans aucune semaine du flash hebdo
            try:
                pv = npv.build_prevus(_read_log(), _list_suivi(), esc)
                sans_eta = pv[pv["statut"] == "Prévu (sans ETA)"]
            except Exception:
                sans_eta = pd.DataFrame()

            def etat(r):
                if r["Statut"] == "OK":
                    return "Conforme"
                if r["Statut"] == "À compléter":
                    return "À compléter"
                return "Accepté" if r["Contrôle"] in acceptes else "À traiter"
            ctrl["Etat"] = ctrl.apply(etat, axis=1)
            a_traiter = int((ctrl["Etat"] == "À traiter").sum()) + (1 if not sans_eta.empty else 0)
            faits = int(ctrl["Etat"].isin(["Conforme", "Accepté"]).sum())
            st.markdown(
                f"<div style='display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:4px 0 10px'>"
                f"<span style='background:#FDEBD3;color:#8A4B00;font-weight:600;border-radius:15px;padding:4px 12px'>"
                f"{a_traiter} à traiter</span>"
                f"<span style='background:#E4F3E7;color:#1E6B3A;font-weight:600;border-radius:15px;padding:4px 12px'>"
                f"{faits} conforme(s) ou accepté(s)</span>"
                f"<span style='color:{TERRA['muted']}'>Chaque choix est tracé dans l'onglet Corrections.</span></div>",
                unsafe_allow_html=True)

            ordre = {"À traiter": 0, "À compléter": 1, "Accepté": 2, "Conforme": 3}
            ctrl = ctrl.sort_values("Etat", key=lambda s: s.map(ordre), kind="stable").reset_index(drop=True)
            ICONE = {"À traiter": ":material/warning:", "À compléter": ":material/pending:",
                     "Accepté": ":material/task_alt:", "Conforme": ":material/check_circle:"}

            for i, r in ctrl.iterrows():
                ecart = "" if pd.isna(r["Écart"]) or r["Écart"] is None else f" · écart {r['Écart']:+,.0f}".replace(",", " ")
                with st.expander(f"{r['Contrôle']}{ecart}  —  {r['Etat']}", icon=ICONE[r["Etat"]],
                                 expanded=(r["Etat"] == "À traiter" and i < 3)):
                    navire_ecart = None
                    if r["Contrôle"].startswith("Navire ") and r["Contrôle"].endswith(": RORO classeur vs PAA"):
                        navire_ecart = r["Contrôle"].removeprefix("Navire ").removesuffix(" : RORO classeur vs PAA")
                    if pd.notna(r["Valeur rapport"]) or pd.notna(r["Valeur de contrôle"]):
                        lab_a, lab_b = ("Classeur (saisie)", "Extrait PAA") if navire_ecart else ("Valeur du rapport", "Valeur de contrôle")
                        c1, c2, c3 = st.columns(3)
                        c1.metric(lab_a, fnum(r["Valeur rapport"]))
                        c2.metric(lab_b, fnum(r["Valeur de contrôle"]))
                        c3.metric("Écart", "—" if pd.isna(r["Écart"]) else f"{r['Écart']:+,.0f}".replace(",", " "))
                    st.markdown(f"**Cause probable :** {r['Explication']}")
                    if lecture_seule or r["Etat"] in ("Conforme", "À compléter"):
                        if r["Etat"] == "À compléter":
                            st.caption("Une des deux valeurs manque : chargez le fichier correspondant.")
                        continue
                    if r["Etat"] == "Accepté":
                        st.caption("Écart accepté tel quel (tracé dans Corrections).")
                        continue
                    b1, b2, b3 = st.columns([1.3, 1.3, 2])
                    if navire_ecart:
                        paa, cls = r["Valeur de contrôle"], r["Valeur rapport"]
                        if b1.button(f"Retenir {fnum(paa)} (PAA)", key=f"ctl_paa_{i}", type="primary",
                                     help="Conseillé : la saisie du classeur est la source la plus probable de l'erreur."):
                            contrib = contributions(annee, n, "roro")
                            if contrib is not None and navire_ecart in set(contrib["navire"]):
                                enregistrer_corr_escale(annee, n, "roro", contrib, navire_ecart, float(paa),
                                                        "Contrôle : écart classeur / PAA", "",
                                                        r26.get((n, "roro")),
                                                        mrows_c.loc["roro"] if "roro" in mrows_c.index else None)
                        if b2.button(f"Garder {fnum(cls)} (classeur)", key=f"ctl_cls_{i}"):
                            store.log_acceptation(annee, n, r["Contrôle"], agent)
                            st.rerun()
                    else:
                        if b1.button("Accepter l'écart", key=f"ctl_ok_{i}",
                                     help="L'écart est connu et justifié : le contrôle passe en « Accepté »."):
                            store.log_acceptation(annee, n, r["Contrôle"], agent)
                            st.rerun()
                        b3.caption("Pour corriger plutôt : Reporting mensuel › « D'où vient ce chiffre ? » "
                                   "(par escale), ou l'onglet Corrections (total).")

            if not sans_eta.empty:
                with st.expander(f"{len(sans_eta)} navire(s) prévu(s) sans date d'arrivée (ETA)  —  À traiter",
                                 icon=":material/warning:", expanded=True):
                    st.markdown("Sans ETA, ces navires ne sont comptés dans aucune semaine du flash hebdo : "
                                "leurs volumes prévus manquent aux prévisions.")
                    st.markdown("**Cause probable :** ETA absente de la fiche PAA au moment de l'archivage.")
                    if lecture_seule:
                        st.caption("Un analyste peut saisir les ETA ici ou dans l'onglet Navires prévus.")
                    else:
                        saisies = {}
                        for j, s in enumerate(sans_eta.itertuples()):
                            c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
                            c1.markdown(f"**{s.navire} {s.voyage}**  \n"
                                        f"<span style='color:{TERRA['muted']};font-size:0.85rem'>Manifeste archivé le "
                                        f"{s.archive.strftime('%d/%m')} · {fnum(s.vehicules)} véhicules prévus</span>",
                                        unsafe_allow_html=True)
                            saisies[(s.navire, s.voyage)] = c2.date_input("ETA", value=None, format="DD/MM/YYYY",
                                                                          key=f"ctl_eta_{j}")
                        if st.button("Enregistrer les ETA", type="primary", key="ctl_eta_save",
                                     disabled=not any(saisies.values())):
                            try:
                                for (nav, voy), d_eta in saisies.items():
                                    if d_eta:
                                        tracking.save_suivi_escale(nav, voy, tracking.SENS_ESCALE[0], d_eta, agent)
                                _list_suivi.clear()
                                st.toast("ETA enregistrées.", icon=":material/check:")
                                st.rerun()
                            except Exception as exc:
                                safe_error("contrôles : enregistrement ETA", exc, "Enregistrement des ETA impossible.")

            with st.expander("Détail par navire (corrections par escale comprises)", icon=":material/table_rows:"):
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
# 3 bis. Navires prévus
# =============================================================================
with tabs[":material/directions_boat: Navires prévus"]:
    st.caption("Manifestes archivés dont le navire n'a pas encore d'escale réalisée dans Stats Flash. "
               "Tous les navires prévus comptent dans les totaux, ETA saisie ou non.")
    try:
        prevus = npv.build_prevus(_read_log(), _list_suivi(), esc)
    except Exception as exc:   # base indisponible : ne pas bloquer le reste de la page
        prevus = None
        safe_error("navires prévus : lecture", exc, "Données des navires prévus indisponibles pour le moment.")
    if prevus is not None:
        a_venir = prevus[prevus["statut"] != "Réalisé"]
        if prevus.empty:
            st.info("Aucun manifeste archivé.")
        else:
            with st.container(border=True):
                k1, k2, k3 = st.columns(3)
                k1.metric("Navires prévus", len(a_venir))
                k2.metric("Véhicules prévus", fnum(a_venir["vehicules"].sum()))
                k3.metric("dont Hinterland", fnum(a_venir["hinterland"].sum()))
                tout_p = st.toggle("Afficher aussi les navires déjà réalisés", value=False, key="sf_prevus_tout")
                v = (prevus if tout_p else a_venir).rename(columns={
                    "navire": "Navire", "voyage": "Voyage", "eta": "ETA", "vehicules": "Véhicules",
                    "hinterland": "Hinterland", "statut": "Statut", "archive": "Archivé le"})
                v["ETA"] = v["ETA"].map(lambda d: d.strftime("%d/%m/%Y") if pd.notna(d) else "ETA à saisir")
                st.dataframe(v, hide_index=True, width="stretch")
                st.caption("Plusieurs traitements du même navire / voyage : seul le dernier est retenu. "
                           "« Réalisé » : une escale réelle débute au plus 10 jours avant l'ETA (ou, sans ETA, avant la date d'archivage).")
            if not lecture_seule and not a_venir.empty:
                with st.container(border=True):
                    st.markdown("#### Saisir ou corriger une ETA")
                    lab = {i: f"{r.navire} · {r.voyage}" for i, r in a_venir.iterrows()}
                    c1, c2, c3 = st.columns([2, 1, 1])
                    choix = c1.selectbox("Navire / voyage", list(lab), format_func=lab.get, key="sf_prevus_nav")
                    sens = c2.selectbox("Sens", list(tracking.SENS_ESCALE), key="sf_prevus_sens")
                    d_eta = c3.date_input("ETA", format="DD/MM/YYYY", key="sf_prevus_eta")
                    if st.button(":material/save: Enregistrer l'ETA", type="primary", key="sf_prevus_save"):
                        row = a_venir.loc[choix]
                        try:
                            tracking.save_suivi_escale(row["navire"], row["voyage"], sens, d_eta, agent)
                            _list_suivi.clear()
                            st.success(f"ETA de {row['navire']} · {row['voyage']} enregistrée.")
                            st.rerun()
                        except Exception as exc:
                            safe_error("navires prévus : enregistrement ETA", exc, "Enregistrement de l'ETA impossible.")


# =============================================================================
# 3 ter. Flash hebdomadaire
# =============================================================================
with tabs[":material/calendar_month: Flash hebdo"]:
    import datetime as _dt
    st.caption("Mêmes indicateurs que le reporting mensuel, sur une semaine (lundi → dimanche), à partir des escales "
               "déjà enregistrées. La colonne N-1 se saisit ici ; rien n'est inventé : « — » = pas de donnée.")
    c1, c2 = st.columns([1, 3])
    jour = c1.date_input("Un jour de la semaine", value=_dt.date.today(), format="DD/MM/YYYY", key="sf_hebdo_jour")
    lun = fh.lundi(jour)
    d0, d1 = fh.bornes(lun)
    c2.markdown(f"**Semaine {fh.n_semaine(lun)}** · du {d0:%d/%m/%Y} au {d1:%d/%m/%Y}")
    try:
        prevus_h = npv.build_prevus(_read_log(), _list_suivi(), esc)
    except Exception as exc:
        prevus_h = None
        safe_error("flash hebdo : navires prévus", exc, "Navires prévus indisponibles pour le moment.")
    esc_p = fh.escales_periode(esc, d0, d1)
    cur, notes_h = fh.indicateurs(esc_p, _hint_ref())
    nav_h = fh.navires_semaine(esc_p, prevus_h, d0, d1)
    suiv_h, sans_eta = fh.navires_suivants(prevus_h, d0, d1)

    with st.container(border=True):
        st.markdown(f"#### Navires de la semaine {fh.n_semaine(lun)}")
        if nav_h.empty:
            st.info("Aucun navire enregistré ou prévu sur cette semaine.")
        else:
            st.dataframe(nav_h, hide_index=True, width="stretch")
            k1, k2, k3 = st.columns(3)
            k1.metric("Navires", len(nav_h))
            k2.metric("TEU", fnum(pd.to_numeric(nav_h["TEU"], errors="coerce").sum(min_count=1)))
            k3.metric("Véhicules", fnum(pd.to_numeric(nav_h["Véhicules"], errors="coerce").sum(min_count=1)))
            if (nav_h["Statut"] == "Prévu").any():
                st.caption("Les navires « Prévu » viennent des manifestes archivés : leurs TEU ne sont pas connus "
                           "(l'archive ne garde pas le détail 20' / 40').")
        if not suiv_h.empty:
            st.markdown(f"#### Prévus la semaine {fh.n_semaine(lun) + 1}")
            v2 = suiv_h.assign(ETA=suiv_h["ETA"].map(lambda d: d.strftime("%d/%m/%Y")))
            st.dataframe(v2, hide_index=True, width="stretch")
        if sans_eta:
            st.caption(f"{sans_eta} navire(s) prévu(s) sans ETA ne sont rattachés à aucune semaine : "
                       "saisir leur ETA dans l'onglet « Navires prévus ».")

    st.markdown("#### Indicateurs de la période")
    sk = f"sf_hebdo_n1_{d0.isoformat()}"
    n1_start, n1_end = d0 - pd.DateOffset(years=1), d1 - pd.DateOffset(years=1)
    with st.expander(f":material/attach_file: N-1 : fiches PAA du {n1_start:%d/%m/%Y} au {n1_end:%d/%m/%Y}"):
        st.caption("Déposez les fiches PAA de l'an dernier (le dossier du mois suffit). Elles donnent, par escale, "
                   "la date d'accostage, les TEU et le nombre de véhicules : l'app en tire Nb d'escales, TEUS et RORO "
                   "de la même période. Neufs, usagés et tranches ne figurent pas dans les fiches : à saisir.")
        fich_up = filter_uploads(st.file_uploader("Fiches PAA N-1 (.xls / .xlsx)", type=["xls", "xlsx"],
                                                  accept_multiple_files=True, key="sf_hebdo_fiches"))
        n1_f = {}
        if fich_up:
            fiches, err_f = _lire_fiches(tuple((f.name, f.getvalue()) for f in fich_up))
            for e in err_f:
                st.warning(e)
            dans = fiches[(fiches["accostage"] >= n1_start) & (fiches["accostage"] < n1_end + pd.Timedelta(days=1))] if not fiches.empty else fiches
            n1_f = fpp.n1_periode(fiches, n1_start, n1_end)
            if dans.empty:
                st.info(f"{len(fiches)} fiche(s) lue(s), aucune avec une date d'accostage sur cette période.")
            else:
                st.dataframe(dans.assign(accostage=dans["accostage"].dt.strftime("%d/%m/%Y"))[
                    ["navire", "voyage", "accostage", "teu", "vehicules"]].rename(columns={
                        "navire": "Navire", "voyage": "Voyage", "accostage": "Accostage", "teu": "TEU", "vehicules": "Véhicules"}),
                    hide_index=True, width="stretch")
                st.caption("Vérifiez ces lignes avant de les reprendre. Véhicules = import + export ; "
                           "véhicules en transbordement non inclus.")
                if st.button(":material/download: Reprendre dans la colonne N-1", key="sf_hebdo_apply"):
                    st.session_state[sk] = {**st.session_state.get(sk, {}), **n1_f}
                    st.session_state["sf_hebdo_ver"] = st.session_state.get("sf_hebdo_ver", 0) + 1
                    st.rerun()
    r26_h, r25_h, a25_h, bud_h = dicts_for_year(vals, d0.year)
    bud7 = fh.budget_periode(bud_h, d0, d1)
    base_t = fh.tableau(cur, {}, bud7)
    base_t = base_t[base_t[["Période", "Budget"]].notna().any(axis=1)]
    if base_t.empty:
        st.info("Aucun indicateur disponible pour cette semaine.")
    else:
        saisie_n1 = st.session_state.get(sk, {})
        ed_in = base_t[["Groupe", "Indicateur", "ind", "Période", "Budget"]].copy()
        ed_in["N-1 (à saisir)"] = ed_in["ind"].map(saisie_n1)
        ed = st.data_editor(
            ed_in.drop(columns=["ind"]), hide_index=True, width="stretch", key=f"{sk}_ed_{st.session_state.get('sf_hebdo_ver', 0)}",
            disabled=["Groupe", "Indicateur", "Période", "Budget"],
            column_config={"N-1 (à saisir)": st.column_config.NumberColumn(min_value=0, step=1),
                           "Période": st.column_config.NumberColumn(format="%.0f"),
                           "Budget": st.column_config.NumberColumn("Budget (7 j)", format="%.1f")})
        n1 = {k: float(v) for k, v in zip(ed_in["ind"], ed["N-1 (à saisir)"]) if pd.notna(v)}
        st.session_state[sk] = n1
        final_t = fh.tableau(cur, n1, bud7)
        final_t = final_t[final_t[["Période", "N-1", "Budget"]].notna().any(axis=1)]
        aff = final_t.drop(columns=["ind"]).copy()
        for c in ("% vs N-1", "% vs budget"):
            aff[c] = aff[c].map(fpct)
        st.dataframe(aff, hide_index=True, width="stretch")
        st.caption(f"Budget de la période = budget mensuel × {(d1 - d0).days + 1} / {fh.JOURS_BUDGET}. "
                   "Pourcentage = (période − référence) / référence.")
        for n in notes_h:
            st.warning(n)
        titre = f"STATS FLASH — SEMAINE {fh.n_semaine(lun)}"
        st.download_button(":material/download: Excel du flash hebdo",
                           fh.build_xlsx(titre, d0, d1, nav_h, suiv_h, final_t, notes_h),
                           file_name=f"FLASH_HEBDO_S{fh.n_semaine(lun)}_{d0:%Y%m%d}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key="sf_hebdo_xlsx")


# =============================================================================
# 4. Corrections
# =============================================================================
if ":material/edit: Corrections" in tabs:
    with tabs[":material/edit: Corrections"]:
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
            if st.button(":material/save: Enregistrer les corrections", type="primary"):
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
                lg["indicateur"] = lg["indicateur"].map(lambda k: "Contrôle" if k == store.IND_CONTROLE
                                                        else " · ".join(sfb.IND_LABEL.get(k, ("", k))))
                st.dataframe(lg, hide_index=True, width="stretch")


# =============================================================================
# 5. Référentiel
# =============================================================================
if ":material/menu_book: Référentiel" in tabs:
    with tabs[":material/menu_book: Référentiel"]:
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
                rows += [(a - 1, 0, k, "realise", v) for k, v in ref["annuel_prec"].items()]
                if ref["mois_ref_prec"]:
                    rows += [(a - 1, ref["mois_ref_prec"], k, "realise", v) for k, v in ref["meme_mois_prec"].items()]
                rows += [(a, 0, k, "budget", v) for k, v in ref["budget"].items()]
                mois_lus = sorted({m for m, _ in ref["realise"]})
                st.info(f"Lu : {len(mois_lus)} mois {a} ({', '.join(MOIS[m - 1] for m in mois_lus)}), "
                        f"total {a - 1}, {MOIS[ref['mois_ref_prec'] - 1].lower() if ref['mois_ref_prec'] else '—'} {a - 1}, budget.")
                if st.button(":material/download: Reprendre ces valeurs", type="primary"):
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
        if st.button(":material/save: Enregistrer le référentiel"):
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
