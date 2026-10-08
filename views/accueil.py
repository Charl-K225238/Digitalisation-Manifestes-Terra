"""Page Accueil — vue d'ensemble adaptée au rôle (maquette validée le 08/10).

- Agent : accès rapide à la saisie, navires attendus, derniers traitements,
  traitements à vérifier.
- Analyste / Direction : chiffres clés du dernier mois chargé dans Stats Flash
  (vs N-1 et budget), évolution mensuelle (graphique ou tableau), contrôles à
  vérifier, navires attendus, derniers traitements.

Lecture seule : chaque bloc indique sa source (icône + info-bulle) et renvoie
vers la page où l'on corrige la donnée.
"""
import datetime as dt
import html
import pathlib
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import navires_prevus as npv
import stats_flash_builder as sfb
import stats_flash_parser as sfp
import stats_store as store
import tracking
from ui_helpers import (ACCESS_ROLE_LABELS, PALETTE, PLOT_TEMPLATE, current_access_role,
                        current_identity, empty_state, hover_lines, icon, kpi_card, kpi_row,
                        section_header, vue_switch)

MOIS = [m.capitalize() for m in sfp.MOIS_FR]
JOURS_ATTENDUS = 7


# ---------------------------------------------------------------------------
# Données (lectures mises en cache : l'accueil est la page la plus ouverte)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=60, show_spinner=False)
def _log():
    return tracking.read_log()


@st.cache_data(ttl=60, show_spinner=False)
def _suivi():
    return tracking.list_suivi_escales()


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _fr(n) -> str:
    return "—" if n is None or pd.isna(n) else f"{float(n):,.0f}".replace(",", " ")


def _rows(items: list[str]) -> None:
    st.markdown('<div class="t-list">' + "".join(items) + "</div>", unsafe_allow_html=True)


def _row(title: str, sub: str, right: str = "", icon_name: str = "ship") -> str:
    return (f'<div class="t-li">{icon(icon_name, 16, "#0B7A2E")}<div class="t-li-main">'
            f'<b>{html.escape(title)}</b><span>{html.escape(sub)}</span></div>'
            f'<span class="t-li-right">{html.escape(right)}</span></div>')


# ---------------------------------------------------------------------------
# En-tête
# ---------------------------------------------------------------------------
role = current_access_role()
identity = current_identity() or {}
nom = (identity.get("name") or "").strip()
prenom = nom.split()[0].capitalize() if nom else ""
aujourd_hui = dt.date.today()

st.markdown(
    f"<h2 style='margin-bottom:0'>{'Bonjour ' + html.escape(prenom) if prenom else 'Accueil'}</h2>"
    f"<p style='color:#5E5B57;margin-top:2px'>{ACCESS_ROLE_LABELS.get(role, 'Agent')} · "
    f"{aujourd_hui.day} {sfp.MOIS_FR[aujourd_hui.month - 1]} {aujourd_hui.year}</p>",
    unsafe_allow_html=True)
if not nom:
    st.caption("Identifiez-vous dans **Profil** pour retrouver vos traitements et vos accès.")

log = _safe(_log, pd.DataFrame())


# ---------------------------------------------------------------------------
# Blocs communs
# ---------------------------------------------------------------------------
def bloc_navires_attendus():
    section_header("Navires attendus", f"{JOURS_ATTENDUS} prochains jours",
                   "Manifestes archivés et ETA saisies dans Stats Flash › Navires prévus", "stats_flash")
    esc = _safe(store.load_escales, pd.DataFrame())
    prevus = _safe(lambda: npv.build_prevus(log, _suivi(), esc))
    if prevus is None:
        empty_state("Données indisponibles", "Lecture des navires prévus impossible pour le moment.", "ship")
        return
    a_venir = prevus[prevus["statut"] != "Réalisé"].copy()
    fin = aujourd_hui + dt.timedelta(days=JOURS_ATTENDUS)
    avec_eta = a_venir[a_venir["eta"].notna()]
    proches = avec_eta[(avec_eta["eta"] >= aujourd_hui) & (avec_eta["eta"] <= fin)].sort_values("eta")
    sans_eta = int(a_venir["eta"].isna().sum())
    if proches.empty:
        empty_state("Aucun navire attendu cette semaine",
                    f"{sans_eta} manifeste(s) archivé(s) sans ETA." if sans_eta else "", "ship")
    else:
        _rows([_row(f"{r.navire} {r.voyage}", f"{_fr(r.vehicules)} véhicules prévus"
                    + (f" · {_fr(r.hinterland)} hinterland" if r.hinterland else ""),
                    f"{r.eta.day:02d}/{r.eta.month:02d}") for r in proches.itertuples()])
        if sans_eta:
            st.caption(f"Et {sans_eta} manifeste(s) archivé(s) sans ETA (à saisir dans Stats Flash).")


def bloc_derniers_traitements(seulement_moi: bool):
    titre = "Mes derniers traitements" if seulement_moi else "Derniers traitements"
    section_header(titre, None, "Journal des traitements, page Archives", "archive")
    if log is None or log.empty:
        empty_state("Aucun traitement", "Les manifestes traités apparaîtront ici.", "archive")
        return
    d = log
    if seulement_moi and nom:
        d = d[d["agent"].fillna("").map(tracking.normalize_name) == tracking.normalize_name(nom)]
    d = d.head(5)
    if d.empty:
        empty_state("Aucun traitement à votre nom", "Commencez par le Pré-Masque.", "archive")
        return
    items = []
    for r in d.itertuples():
        quand = pd.Timestamp(r.horodatage).tz_convert(None) if pd.Timestamp(r.horodatage).tzinfo else pd.Timestamp(r.horodatage)
        qui = "" if seulement_moi else f" · {r.agent}"
        items.append(_row(f"{r.navire or '—'} {r.voyage or ''}".strip(),
                          f"{_fr(r.volume_total)} unités{qui}",
                          quand.strftime("%d/%m %H:%M"),
                          "check" if r.verifie else "file"))
    _rows(items)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
def accueil_agent():
    section_header("Que voulez-vous faire ?")
    c = st.columns(4)
    c[0].page_link("views/structuration.py", label="Préparer un Pré-Masque", icon=":material/note_add:")
    c[1].page_link("views/fiche_depouillement.py", label="Fiche de dépouillement", icon=":material/fact_check:")
    c[2].page_link("views/loading_report.py", label="MASQUE / Type ISO", icon=":material/grid_on:")
    c[3].page_link("views/bl_importer.py", label="BL Importer", icon=":material/layers:")

    if log is not None and not log.empty:
        d = log if not nom else log[log["agent"].fillna("").map(tracking.normalize_name)
                                     == tracking.normalize_name(nom)]
        a_verif = int((~d["verifie"]).sum())
        if a_verif:
            st.warning(f"{a_verif} traitement(s) à votre nom ne sont pas encore marqués « vérifié ». "
                       "Ouvrez **Archives** pour les contrôler.", icon=":material/rule:")

    g, dr = st.columns(2, gap="large")
    with g:
        bloc_navires_attendus()
    with dr:
        bloc_derniers_traitements(seulement_moi=bool(nom))


# ---------------------------------------------------------------------------
# Analyste / Direction
# ---------------------------------------------------------------------------
KPIS = [("escales", "Escales", "anchor"), ("roro", "RORO", "car"), ("teu", "TEU", "container"),
        ("neufs", "Véhicules neufs", "tag"), ("hinterland", "Hinterland", "globe")]
METRIQUES = {"RORO": "roro", "TEU": "teu", "Escales": "escales"}


def accueil_pilotage():
    vals = _safe(store.load_values, pd.DataFrame())
    real = vals[(vals["nature"] == "realise") & (vals["mois"] > 0)] if not vals.empty else vals
    if real is None or real.empty:
        empty_state("Aucune donnée Stats Flash",
                    "Chargez un mois dans Stats Flash & Reporting pour alimenter cet accueil.", "chart")
        st.page_link("views/stats_flash.py", label="Ouvrir Stats Flash", icon=":material/trending_up:")
        bloc_navires_attendus()
        return

    annee, mois = max((int(a), int(m)) for a, m in real[["annee", "mois"]].itertuples(index=False))

    def v(ind, an, m):
        if ind == "hinterland":
            parts = [v(k, an, m) for k in ("h_lt15", "h_15_50", "h_gt50")]
            return None if any(p is None for p in parts) else sum(parts)
        s = real[(real["annee"] == an) & (real["mois"] == m) & (real["indicateur"] == ind)]["valeur"]
        return float(s.iloc[0]) if len(s) and pd.notna(s.iloc[0]) else None

    def budget(ind):
        if ind == "hinterland":
            parts = [budget(k) for k in ("h_lt15", "h_15_50", "h_gt50")]
            return None if any(p is None for p in parts) else sum(parts)
        b = vals[(vals["nature"] == "budget") & (vals["annee"] == annee) & (vals["mois"] == 0)
                 & (vals["indicateur"] == ind)]["valeur"]
        return float(b.iloc[0]) if len(b) and pd.notna(b.iloc[0]) else None

    section_header(f"{MOIS[mois - 1]} {annee}", f"comparé à {sfp.MOIS_FR[mois - 1]} {annee - 1}",
                   f"Stats Flash · {sfp.MOIS_FR[mois - 1]} {annee}", "stats_flash")
    kpi_row([kpi_card(lab, v(ind, annee, mois), v(ind, annee - 1, mois), budget(ind), ic, i)
             for i, (ind, lab, ic) in enumerate(KPIS)])

    # Évolution mensuelle
    section_header("Évolution mensuelle", f"{annee} et {annee - 1}, même mois",
                   f"Stats Flash {annee} et historique {annee - 1} du Référentiel", "stats_flash")
    c1, c2 = st.columns([3, 1])
    with c1:
        choix = st.segmented_control("Indicateur", list(METRIQUES), default="RORO", key="acc_metric",
                                     label_visibility="collapsed") or "RORO"
    with c2:
        graphique = vue_switch("acc_vue")
    ind = METRIQUES[choix]
    s_n = [v(ind, annee, m) for m in range(1, 13)]
    s_p = [v(ind, annee - 1, m) for m in range(1, 13)]
    ecarts = [None if a is None or b in (None, 0) else (a - b) / b * 100 for a, b in zip(s_n, s_p)]
    if graphique:
        fig = go.Figure()
        cd = [[_fr(b), "—" if e is None else f"{e:+.1f} %".replace(".", ",")] for b, e in zip(s_p, ecarts)]
        fig.add_bar(x=sfb.MOIS_COURT, y=s_n, name=str(annee), marker_color=PALETTE["blue"], customdata=cd,
                    hovertemplate=hover_lines(f"%{{x}} {annee}", [(str(annee), "%{y:,.0f}"),
                                                                  (str(annee - 1), "%{customdata[0]}"),
                                                                  ("Écart", "%{customdata[1]}")]))
        fig.add_bar(x=sfb.MOIS_COURT, y=s_p, name=f"{annee - 1} (même mois)", marker_color=PALETTE["orange"],
                    opacity=0.55, hovertemplate=hover_lines(f"%{{x}} {annee - 1}", [(choix, "%{y:,.0f}")]))
        fig.update_layout(template=PLOT_TEMPLATE, barmode="group", height=340,
                          margin=dict(t=10, l=10, r=10, b=10))
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    else:
        tab = pd.DataFrame({"Mois": MOIS, str(annee): s_n, str(annee - 1): s_p,
                            "Écart": [None if a is None or b is None else a - b for a, b in zip(s_n, s_p)],
                            "Écart %": ecarts})
        tab = tab[tab[[str(annee), str(annee - 1)]].notna().any(axis=1)]
        st.dataframe(tab, hide_index=True, width="stretch", column_config={
            str(annee): st.column_config.NumberColumn(format="localized"),
            str(annee - 1): st.column_config.NumberColumn(format="localized"),
            "Écart": st.column_config.NumberColumn(format="localized"),
            "Écart %": st.column_config.NumberColumn(format="%+.1f %%")})

    g, dr = st.columns(2, gap="large")
    with g:
        bloc_controles(vals, annee, mois)
        bloc_navires_attendus()
    with dr:
        bloc_derniers_traitements(seulement_moi=False)


def bloc_controles(vals, annee, mois):
    section_header("À vérifier", f"contrôles de {sfp.MOIS_FR[mois - 1]} {annee}",
                   "Onglet Contrôles de Stats Flash", "stats_flash")
    esc = _safe(store.load_escales, pd.DataFrame())
    em = esc[(esc["annee"] == annee) & (esc["mois"] == mois)] if esc is not None and not esc.empty else None
    if em is None or em.empty:
        empty_state("Contrôles indisponibles", "Pas de détail par navire pour ce mois.", "check")
        return
    r = vals[(vals["nature"] == "realise") & (vals["annee"] == annee) & (vals["mois"] == mois)]
    retenu = {k: x for k, x in r[["indicateur", "valeur"]].itertuples(index=False) if pd.notna(x)}
    def _det():
        d = sfb.detail_from_store(em)
        ce = store.load_corr_escales()
        ce = ce[(ce["annee"] == annee) & (ce["mois"] == mois)] if not ce.empty else ce
        cols = {"teu": "teu", "roro": "roro", "neufs": "neufs", "usages": "usages"}
        for c in ce.itertuples():
            if c.indicateur in cols:
                d.loc[d["navire"] == c.navire, cols[c.indicateur]] = float(c.valeur_retenue)
        d["ecart_roro"] = pd.to_numeric(d["roro"], errors="coerce") - pd.to_numeric(d["roro_paa"], errors="coerce")
        return d
    ctrl = _safe(lambda: sfb.controles(_det(), retenu))
    if ctrl is None:
        empty_state("Contrôles indisponibles", "", "check")
        return
    lg = _safe(store.load_log, pd.DataFrame())
    acceptes = set()
    if lg is not None and not lg.empty:
        la = lg[(lg["annee"] == annee) & (lg["mois"] == mois) & (lg["indicateur"] == store.IND_CONTROLE)]
        acceptes = {str(m).removeprefix(store.MOTIF_ACCEPTE) for m in la["motif"].dropna()}
    ko = ctrl[(ctrl["Statut"] == "À vérifier") & ~ctrl["Contrôle"].isin(acceptes)]
    if ko.empty:
        empty_state("Tout est cohérent", "Aucun écart entre les sources ce mois-ci.", "check")
        return
    _rows([_row(c.Contrôle, c.Explication, "" if pd.isna(c.Écart) else f"écart {_fr(c.Écart)}", "alert")
           for c in ko.head(4).itertuples()])
    if len(ko) > 4:
        st.caption(f"Et {len(ko) - 4} autre(s) dans Stats Flash › Contrôles.")


if role in ("analyste", "direction"):
    accueil_pilotage()
else:
    accueil_agent()
