"""
Tableau de bord — suivi de performance de la structuration des manifestes.
Vue globale et vue par intervenant, avec granularité hebdomadaire ou mensuelle.
"""
import pathlib
import sys

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import tracking
from ui_helpers import CATEGORICAL_SEQUENCE, PALETTE, help_expander, format_duree

st.title("📊 Tableau de bord — Suivi de performance")
st.caption(
    "Volumes traités et temps de structuration, au global et par intervenant, "
    "avec vue hebdomadaire ou mensuelle."
)

with help_expander("ℹ️ Comment lire ce tableau de bord ?"):
    st.markdown(
        """
- **Période** filtre les traitements pris en compte (semaine en cours, mois en
  cours, année en cours, tout l'historique, ou une plage personnalisée).
- **Intervenant(s)** limite l'analyse à une ou plusieurs personnes — laissez le
  champ vide pour tout le monde. Tapez pour rechercher dans la liste.
- **Granularité** choisit le pas des courbes de tendance : semaine ou mois.
- **Manifestes traités** : nombre de fichiers PDF passés dans l'application sur
  la période sélectionnée.
- **Temps de traitement** : temps mis par l'outil pour extraire un manifeste,
  du clic sur *Lancer le traitement* jusqu'au résultat.
- **Taux de vérification** : part des manifestes relus et validés par un agent
  (case « Vérifié » cochée).
- **Taux de transit** : part des B/L marqués comme transbordement (Pays_Transit).
- Le **Δ** à côté d'un indicateur compare la période sélectionnée à la période
  équivalente précédente (ex : cette semaine vs semaine dernière).
        """
    )

# Nettoyage silencieux d'éventuelles lignes issues d'anciens tests internes —
# n'affecte pas les traitements réels.
tracking.clear_demo_data()

df = tracking.read_log()

if df.empty:
    st.info(
        "Ce tableau de bord est vide pour le moment. Il se remplit "
        "automatiquement à chaque manifeste traité depuis la page "
        "**📦 Structuration des manifestes** — commencez par y déposer un PDF."
    )
    st.stop()

st.divider()

# ---------------------------------------------------------------------------
# Filtres
# ---------------------------------------------------------------------------
col_period, col_gran, col_agent = st.columns([1.3, 1, 1.7])
with col_period:
    period_choice = st.selectbox(
        "Période",
        ["Semaine en cours", "Mois en cours", "Année en cours", "Tout l'historique", "Personnalisée"],
        help="Filtre les données affichées dans les indicateurs, graphiques et tableaux ci-dessous.",
    )
with col_gran:
    granularite = st.segmented_control(
        "Granularité", ["Semaine", "Mois"], default="Semaine", required=True,
        help="Pas de temps utilisé pour les courbes de tendance.",
    )
with col_agent:
    agents_dispo = sorted(a for a in df["agent"].dropna().unique() if a)
    agents_filtre = st.multiselect(
        "Intervenant(s)", agents_dispo, placeholder="Tout le monde",
        help="Tapez pour rechercher. Laissez vide pour inclure tout le monde.",
    )

now = pd.Timestamp.now(tz="UTC")
prev_start = prev_end = None

if period_choice == "Semaine en cours":
    start = (now - pd.Timedelta(days=now.dayofweek)).normalize()
    end = now
    prev_start, prev_end = start - pd.Timedelta(days=7), start
elif period_choice == "Mois en cours":
    start = now.replace(day=1).normalize()
    end = now
    prev_start = (start - pd.Timedelta(days=1)).replace(day=1)
    prev_end = start
elif period_choice == "Année en cours":
    start = now.replace(month=1, day=1).normalize()
    end = now
    prev_start = start.replace(year=start.year - 1)
    prev_end = start
elif period_choice == "Tout l'historique":
    start = df["horodatage"].min()
    end = now
else:  # Personnalisée
    c1, c2 = st.columns(2)
    d1 = c1.date_input("Du", value=df["horodatage"].min().date())
    d2 = c2.date_input("Au", value=now.date())
    start = pd.Timestamp(d1, tz="UTC")
    end = pd.Timestamp(d2, tz="UTC") + pd.Timedelta(days=1)

mask = (df["horodatage"] >= start) & (df["horodatage"] <= end)
if agents_filtre:
    mask &= df["agent"].isin(agents_filtre)
dff = df[mask]

dprev = pd.DataFrame()
if prev_start is not None:
    mprev = (df["horodatage"] >= prev_start) & (df["horodatage"] < prev_end)
    if agents_filtre:
        mprev &= df["agent"].isin(agents_filtre)
    dprev = df[mprev]


def delta_str(curr, prev):
    """Variation courte (ex: '+12%') pour tenir dans la carte KPI — le détail
    'vs période précédente' est donné dans le tooltip d'aide du KPI."""
    if dprev.empty or not prev:
        return None
    return f"{(curr - prev) / prev * 100:+.0f}%"


st.divider()

# ---------------------------------------------------------------------------
# Indicateurs clés — ligne 1 : volumes
# ---------------------------------------------------------------------------
if dff.empty:
    st.warning("Aucune donnée pour cette période / ces intervenants.")
    st.stop()

k1, k2, k3, k4, k5 = st.columns(5)

n_manifestes = len(dff)
k1.metric(
    "Manifestes", n_manifestes,
    delta=delta_str(n_manifestes, len(dprev)),
    help="Nombre de fichiers PDF traités sur la période sélectionnée (Δ = variation vs période équivalente précédente).",
)

n_bl = int(dff["nb_bl"].sum())
k2.metric(
    "B/L structurés", n_bl,
    delta=delta_str(n_bl, int(dprev["nb_bl"].sum()) if not dprev.empty else 0),
    help="Nombre total de connaissements (Bill of Lading) structurés (Δ = variation vs période équivalente précédente).",
)

volume = int(dff["volume_total"].sum())
k3.metric(
    "Volume (unités)", volume,
    delta=delta_str(volume, int(dprev["volume_total"].sum()) if not dprev.empty else 0),
    help="Somme des véhicules, conteneurs et colis structurés (Δ = variation vs période équivalente précédente).",
)

temps_moyen = dff["duree_traitement_sec"].mean()
k4.metric(
    "Temps moyen", format_duree(temps_moyen),
    help="Durée moyenne entre le lancement et la fin de l'extraction, par manifeste.",
)

n_agents = dff["agent"].nunique()
k5.metric(
    "Intervenants actifs", n_agents,
    help="Nombre de personnes distinctes ayant traité au moins un manifeste sur la période.",
)

# ---------------------------------------------------------------------------
# Indicateurs clés — ligne 2 : qualité & métier
# ---------------------------------------------------------------------------
k6, k7, k8, k9, k10 = st.columns(5)

# Taux de vérification
n_verifie = int(dff["verifie"].sum())
taux_verif = n_verifie / n_manifestes * 100 if n_manifestes else 0
n_verifie_prev = int(dprev["verifie"].sum()) if not dprev.empty else 0
n_prev_total = len(dprev) if not dprev.empty else 0
taux_verif_prev = n_verifie_prev / n_prev_total * 100 if n_prev_total else 0
k6.metric(
    "Vérifiés", f"{taux_verif:.0f}%",
    delta=f"{taux_verif - taux_verif_prev:+.0f}pp" if n_prev_total else None,
    help=f"{n_verifie} manifeste(s) relu(s) et validé(s) sur {n_manifestes}. "
         "Δ en points de pourcentage vs période précédente.",
)

# Taux de transit
n_transit = int(dff["nb_transit"].fillna(0).sum())
n_bl_total = int(dff["nb_bl"].sum())
taux_transit = n_transit / n_bl_total * 100 if n_bl_total else 0
n_transit_prev = int(dprev["nb_transit"].fillna(0).sum()) if not dprev.empty else 0
n_bl_prev = int(dprev["nb_bl"].sum()) if not dprev.empty else 0
taux_transit_prev = n_transit_prev / n_bl_prev * 100 if n_bl_prev else 0
k7.metric(
    "B/L transit", f"{taux_transit:.0f}%",
    delta=f"{taux_transit - taux_transit_prev:+.0f}pp" if n_bl_prev else None,
    help=f"{n_transit} B/L en transbordement sur {n_bl_total}. "
         "Δ en points de pourcentage vs période précédente.",
)

# Navires distincts
n_navires = dff["navire"].dropna().nunique()
k8.metric(
    "Navires", n_navires,
    help="Nombre de navires distincts traités sur la période.",
)

# Véhicules
n_veh = int(dff["nb_vehicules"].fillna(0).sum())
k9.metric(
    "Véhicules", n_veh,
    delta=delta_str(n_veh, int(dprev["nb_vehicules"].fillna(0).sum()) if not dprev.empty else 0),
    help="Nombre total de véhicules structurés.",
)

# Conteneurs
n_cnt = int(dff["nb_conteneurs"].fillna(0).sum())
k10.metric(
    "Conteneurs", n_cnt,
    delta=delta_str(n_cnt, int(dprev["nb_conteneurs"].fillna(0).sum()) if not dprev.empty else 0),
    help="Nombre total de conteneurs structurés.",
)

st.divider()

# ---------------------------------------------------------------------------
# Vues
# ---------------------------------------------------------------------------
tab_global, tab_navires, tab_service, tab_agent = st.tabs([
    "🌍 Vue globale", "🚢 Top navires", "🏢 Par service", "👤 Par intervenant"
])

freq = "W" if granularite == "Semaine" else "ME"
freq_label = "semaine" if freq == "W" else "mois"

PLOT_LAYOUT = dict(template="plotly_white", font_family="Segoe UI, sans-serif", margin=dict(t=48, l=10, r=10, b=10))
DATE_TICK = dict(
    dtick=7 * 24 * 60 * 60 * 1000 if freq == "W" else "M1",
    tickformat="%d %b" if freq == "W" else "%b %Y",
)


def apply_date_axis(fig):
    """Force un axe temporel lisible (jour/mois) même sur une période étroite,
    où Plotly aurait sinon affiché des graduations en fractions de seconde."""
    fig.update_xaxes(**DATE_TICK)
    return fig


# ---------------------------------------------------------------------------
# Onglet — Vue globale
# ---------------------------------------------------------------------------
with tab_global:
    trend = (
        dff.set_index("horodatage")
           .resample(freq)
           .agg(manifestes=("id", "count"), volume=("volume_total", "sum"))
           .reset_index()
    )

    fig = px.line(
        trend, x="horodatage", y="manifestes", markers=True,
        title=f"Manifestes traités par {freq_label}",
        color_discrete_sequence=[PALETTE["blue"]],
    )
    fig.update_layout(**PLOT_LAYOUT, yaxis_title="Manifestes", xaxis_title="")
    apply_date_axis(fig)
    st.plotly_chart(fig, width='stretch')

    c1, c2 = st.columns(2)
    with c1:
        repartition = dff[["nb_vehicules", "nb_conteneurs", "nb_colis"]].sum()
        repartition.index = ["Véhicules", "Conteneurs", "Colis"]
        repartition = repartition.reset_index()
        repartition.columns = ["Type", "Unités"]
        repartition = repartition.sort_values("Unités", ascending=True)
        fig2 = px.bar(
            repartition, x="Unités", y="Type", orientation="h",
            title="Répartition du volume par type", text="Unités",
            color="Type", color_discrete_sequence=[PALETTE["aqua"], PALETTE["orange"], PALETTE["blue"]],
        )
        fig2.update_traces(textposition="outside", cliponaxis=False)
        fig2.update_layout(
            font_family="Segoe UI, sans-serif", margin=dict(t=48, l=10, r=10, b=10),
            showlegend=False, yaxis_title="", xaxis_title="Unités",
        )
        st.plotly_chart(fig2, width='stretch')
    with c2:
        fig3 = px.bar(
            trend, x="horodatage", y="volume",
            title=f"Volume traité par {freq_label}",
            color_discrete_sequence=[PALETTE["blue"]],
        )
        fig3.update_layout(**PLOT_LAYOUT, yaxis_title="Unités", xaxis_title="")
        apply_date_axis(fig3)
        st.plotly_chart(fig3, width='stretch')

    # Taux de vérification dans le temps
    if n_manifestes >= 3:
        trend_verif = (
            dff.set_index("horodatage")
               .resample(freq)
               .agg(manifestes=("id", "count"), verifies=("verifie", "sum"))
               .reset_index()
        )
        trend_verif["taux"] = (trend_verif["verifies"] / trend_verif["manifestes"] * 100).fillna(0)
        fig_verif = px.line(
            trend_verif, x="horodatage", y="taux", markers=True,
            title=f"Taux de vérification par {freq_label} (%)",
            color_discrete_sequence=[PALETTE["aqua"]],
        )
        fig_verif.update_layout(**PLOT_LAYOUT, yaxis_title="%", xaxis_title="", yaxis_range=[0, 105])
        apply_date_axis(fig_verif)
        st.plotly_chart(fig_verif, width='stretch')

    st.subheader("Activité récente")
    recherche_activite = st.text_input(
        "🔍 Rechercher dans l'activité", placeholder="Navire, voyage, intervenant…",
        key="recherche_activite",
        help="Filtre le tableau ci-dessous. Pour l'historique complet avec PDF/Excel "
        "téléchargeables, voir la page **🗂️ Archives**.",
    )
    activite = (
        dff[["horodatage", "agent", "navire", "voyage", "type_cargo", "nb_bl", "volume_total", "duree_traitement_sec", "verifie"]]
        .rename(columns={
            "horodatage": "Date", "agent": "Traité par", "navire": "Navire", "voyage": "Voyage",
            "type_cargo": "Type", "nb_bl": "B/L", "volume_total": "Volume",
        })
        .sort_values("Date", ascending=False)
    )
    activite["Durée"] = activite["duree_traitement_sec"].apply(format_duree)
    activite["✅"] = activite["verifie"].apply(lambda v: "✅" if v else "")
    activite = activite.drop(columns=["duree_traitement_sec", "verifie"])
    if recherche_activite:
        q = recherche_activite.strip().lower()
        mask = (
            activite["Navire"].fillna("").str.lower().str.contains(q)
            | activite["Voyage"].fillna("").str.lower().str.contains(q)
            | activite["Traité par"].fillna("").str.lower().str.contains(q)
        )
        activite = activite[mask]
    st.dataframe(activite, width='stretch', hide_index=True)

# ---------------------------------------------------------------------------
# Onglet — Top navires
# ---------------------------------------------------------------------------
with tab_navires:
    st.subheader("Navires les plus traités")

    nav_df = dff[dff["navire"].notna() & (dff["navire"] != "")].copy()
    if nav_df.empty:
        st.info("Aucun navire identifié sur cette période.")
    else:
        par_navire = (
            nav_df.groupby("navire")
                  .agg(
                      manifestes=("id", "count"),
                      bl=("nb_bl", "sum"),
                      volume=("volume_total", "sum"),
                      nb_transit=("nb_transit", "sum"),
                      verifie=("verifie", "sum"),
                  )
                  .reset_index()
                  .sort_values("volume", ascending=False)
        )
        par_navire["taux_verif"] = (par_navire["verifie"] / par_navire["manifestes"] * 100).round(0).astype(int)

        top_n = min(10, len(par_navire))
        top_navires = par_navire.head(top_n)

        fig_nav = px.bar(
            top_navires.sort_values("volume", ascending=True),
            x="volume", y="navire", orientation="h",
            title=f"Top {top_n} navires par volume traité",
            text="volume",
            color_discrete_sequence=[PALETTE["blue"]],
        )
        fig_nav.update_traces(textposition="outside", cliponaxis=False)
        fig_nav.update_layout(**PLOT_LAYOUT, yaxis_title="", xaxis_title="Unités")
        st.plotly_chart(fig_nav, width='stretch')

        c1, c2 = st.columns(2)
        with c1:
            fig_nav2 = px.bar(
                top_navires.sort_values("manifestes", ascending=True),
                x="manifestes", y="navire", orientation="h",
                title="Par nombre de manifestes",
                text="manifestes",
                color_discrete_sequence=[PALETTE["orange"]],
            )
            fig_nav2.update_traces(textposition="outside", cliponaxis=False)
            fig_nav2.update_layout(**PLOT_LAYOUT, yaxis_title="", xaxis_title="Manifestes")
            st.plotly_chart(fig_nav2, width='stretch')
        with c2:
            fig_nav3 = px.bar(
                top_navires.sort_values("bl", ascending=True),
                x="bl", y="navire", orientation="h",
                title="Par nombre de B/L",
                text="bl",
                color_discrete_sequence=[PALETTE["aqua"]],
            )
            fig_nav3.update_traces(textposition="outside", cliponaxis=False)
            fig_nav3.update_layout(**PLOT_LAYOUT, yaxis_title="", xaxis_title="B/L")
            st.plotly_chart(fig_nav3, width='stretch')

        st.subheader("Détail par navire")
        affiche_nav = par_navire.rename(columns={
            "navire": "Navire", "manifestes": "Manifestes", "bl": "B/L",
            "volume": "Volume", "nb_transit": "B/L Transit", "taux_verif": "Vérifiés (%)",
        })
        affiche_nav = affiche_nav.drop(columns=["verifie"])
        st.dataframe(affiche_nav, width='stretch', hide_index=True)

# ---------------------------------------------------------------------------
# Onglet — Par service
# ---------------------------------------------------------------------------
with tab_service:
    st.subheader("Performance par service")

    svc_df = dff[dff["service"].notna() & (dff["service"] != "")].copy()
    if svc_df.empty:
        st.info(
            "Les données de service ne sont pas encore disponibles — "
            "elles se renseignent automatiquement à partir de la prochaine connexion identifiée."
        )
    else:
        par_svc = (
            svc_df.groupby("service")
                  .agg(
                      manifestes=("id", "count"),
                      bl=("nb_bl", "sum"),
                      volume=("volume_total", "sum"),
                      verifie=("verifie", "sum"),
                      intervenants=("agent", "nunique"),
                  )
                  .reset_index()
                  .sort_values("manifestes", ascending=False)
        )
        par_svc["taux_verif"] = (par_svc["verifie"] / par_svc["manifestes"] * 100).round(0).astype(int)

        fig_svc = px.bar(
            par_svc, x="service", y="manifestes",
            title="Manifestes traités par service",
            text="manifestes",
            color="service",
            color_discrete_sequence=CATEGORICAL_SEQUENCE,
        )
        fig_svc.update_traces(textposition="outside", cliponaxis=False)
        fig_svc.update_layout(**PLOT_LAYOUT, yaxis_title="Manifestes", xaxis_title="", showlegend=False)
        st.plotly_chart(fig_svc, width='stretch')

        c1, c2 = st.columns(2)
        with c1:
            fig_svc2 = px.bar(
                par_svc, x="service", y="volume",
                title="Volume traité par service",
                text="volume",
                color="service",
                color_discrete_sequence=CATEGORICAL_SEQUENCE,
            )
            fig_svc2.update_traces(textposition="outside", cliponaxis=False)
            fig_svc2.update_layout(**PLOT_LAYOUT, yaxis_title="Unités", xaxis_title="", showlegend=False)
            st.plotly_chart(fig_svc2, width='stretch')
        with c2:
            fig_svc3 = px.bar(
                par_svc, x="service", y="taux_verif",
                title="Taux de vérification par service (%)",
                text="taux_verif",
                color="service",
                color_discrete_sequence=CATEGORICAL_SEQUENCE,
            )
            fig_svc3.update_traces(texttemplate="%{text}%", textposition="outside", cliponaxis=False)
            fig_svc3.update_layout(**PLOT_LAYOUT, yaxis_title="%", xaxis_title="",
                                    showlegend=False, yaxis_range=[0, 110])
            st.plotly_chart(fig_svc3, width='stretch')

        st.subheader("Détail par service")
        affiche_svc = par_svc.rename(columns={
            "service": "Service", "manifestes": "Manifestes", "bl": "B/L",
            "volume": "Volume", "intervenants": "Intervenants",
            "taux_verif": "Vérifiés (%)",
        })
        affiche_svc = affiche_svc.drop(columns=["verifie"])
        st.dataframe(affiche_svc, width='stretch', hide_index=True)

        # Tendance par service dans le temps
        if svc_df["service"].nunique() > 1 and len(svc_df) >= 3:
            trend_svc = (
                svc_df.set_index("horodatage")
                      .groupby("service")
                      .resample(freq)
                      .agg(manifestes=("id", "count"))
                      .reset_index()
            )
            fig_svc_trend = px.line(
                trend_svc, x="horodatage", y="manifestes", color="service",
                markers=True,
                title=f"Manifestes par service et par {freq_label}",
                color_discrete_sequence=CATEGORICAL_SEQUENCE,
            )
            fig_svc_trend.update_layout(**PLOT_LAYOUT, yaxis_title="Manifestes", xaxis_title="")
            apply_date_axis(fig_svc_trend)
            st.plotly_chart(fig_svc_trend, width='stretch')

# ---------------------------------------------------------------------------
# Onglet — Par intervenant
# ---------------------------------------------------------------------------
with tab_agent:
    par_agent = (
        dff.groupby("agent")
           .agg(manifestes=("id", "count"), bl=("nb_bl", "sum"), volume=("volume_total", "sum"),
                temps_moyen=("duree_traitement_sec", "mean"), verifie=("verifie", "sum"))
           .reset_index()
           .sort_values("manifestes", ascending=False)
    )
    par_agent["taux_verif"] = (par_agent["verifie"] / par_agent["manifestes"] * 100).round(0).astype(int)

    fig4 = px.bar(
        par_agent, x="manifestes", y="agent", orientation="h",
        title="Manifestes traités par intervenant",
        color_discrete_sequence=[PALETTE["blue"]],
    )
    fig4.update_layout(
        **PLOT_LAYOUT, yaxis_title="", xaxis_title="Manifestes",
        yaxis=dict(categoryorder="total ascending"),
    )
    st.plotly_chart(fig4, width='stretch')

    c1, c2 = st.columns(2)
    with c1:
        fig_ag2 = px.bar(
            par_agent.sort_values("volume", ascending=True),
            x="volume", y="agent", orientation="h",
            title="Volume par intervenant",
            text="volume",
            color_discrete_sequence=[PALETTE["orange"]],
        )
        fig_ag2.update_traces(textposition="outside", cliponaxis=False)
        fig_ag2.update_layout(**PLOT_LAYOUT, yaxis_title="", xaxis_title="Unités",
                               yaxis=dict(categoryorder="total ascending"))
        st.plotly_chart(fig_ag2, width='stretch')
    with c2:
        fig_ag3 = px.bar(
            par_agent.sort_values("taux_verif", ascending=True),
            x="taux_verif", y="agent", orientation="h",
            title="Taux de vérification (%)",
            text="taux_verif",
            color_discrete_sequence=[PALETTE["aqua"]],
        )
        fig_ag3.update_traces(texttemplate="%{text}%", textposition="outside", cliponaxis=False)
        fig_ag3.update_layout(**PLOT_LAYOUT, yaxis_title="", xaxis_title="%",
                               yaxis=dict(categoryorder="total ascending"), xaxis_range=[0, 110])
        st.plotly_chart(fig_ag3, width='stretch')

    st.subheader("Détail par intervenant")
    par_agent_affiche = par_agent.rename(columns={
        "agent": "Intervenant", "manifestes": "Manifestes", "bl": "B/L", "volume": "Volume",
        "taux_verif": "Vérifiés (%)",
    })
    par_agent_affiche["Temps moyen"] = par_agent["temps_moyen"].apply(format_duree)
    st.dataframe(
        par_agent_affiche.drop(columns=["temps_moyen", "verifie"]),
        width='stretch', hide_index=True,
    )

    st.subheader("Tendance d'un intervenant")
    agent_select = st.selectbox("Choisir un intervenant", par_agent["agent"], help="Affiche l'évolution de cette personne sur la période et la granularité sélectionnées ci-dessus.")
    d_agent = dff[dff["agent"] == agent_select]
    trend_agent = (
        d_agent.set_index("horodatage").resample(freq)
               .agg(manifestes=("id", "count"), volume=("volume_total", "sum")).reset_index()
    )
    ca1, ca2 = st.columns(2)
    with ca1:
        fig5 = px.line(
            trend_agent, x="horodatage", y="manifestes", markers=True,
            title=f"{agent_select} — manifestes par {freq_label}",
            color_discrete_sequence=[PALETTE["orange"]],
        )
        fig5.update_layout(**PLOT_LAYOUT, yaxis_title="Manifestes", xaxis_title="")
        apply_date_axis(fig5)
        st.plotly_chart(fig5, width='stretch')
    with ca2:
        fig6 = px.bar(
            trend_agent, x="horodatage", y="volume",
            title=f"{agent_select} — volume par {freq_label}",
            color_discrete_sequence=[PALETTE["blue"]],
        )
        fig6.update_layout(**PLOT_LAYOUT, yaxis_title="Unités", xaxis_title="")
        apply_date_axis(fig6)
        st.plotly_chart(fig6, width='stretch')
