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
from ui_helpers import PALETTE, help_expander, format_duree

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
# Indicateurs clés
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

st.divider()

# ---------------------------------------------------------------------------
# Vues
# ---------------------------------------------------------------------------
tab_global, tab_agent = st.tabs(["🌍 Vue globale", "👤 Vue par intervenant"])

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
        # Barres horizontales plutôt qu'un camembert/donut : avec seulement 3
        # catégories la différence de lisibilité est faible, mais la longueur
        # d'une barre se compare bien plus précisément que l'angle d'un secteur
        # (surtout quand deux catégories sont proches en valeur) — recommandation
        # dataviz standard pour un usage BI/décisionnel.
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

    st.subheader("Activité récente")
    recherche_activite = st.text_input(
        "🔍 Rechercher dans l'activité", placeholder="Navire, voyage, intervenant…",
        key="recherche_activite",
        help="Filtre le tableau ci-dessous. Pour l'historique complet avec PDF/Excel "
        "téléchargeables, voir la page **🗂️ Archives**.",
    )
    activite = (
        dff[["horodatage", "agent", "navire", "voyage", "type_cargo", "nb_bl", "volume_total", "duree_traitement_sec"]]
        .rename(columns={
            "horodatage": "Date", "agent": "Traité par", "navire": "Navire", "voyage": "Voyage",
            "type_cargo": "Type", "nb_bl": "B/L", "volume_total": "Volume",
        })
        .sort_values("Date", ascending=False)
    )
    activite["Durée"] = activite["duree_traitement_sec"].apply(format_duree)
    activite = activite.drop(columns=["duree_traitement_sec"])
    if recherche_activite:
        q = recherche_activite.strip().lower()
        mask = (
            activite["Navire"].fillna("").str.lower().str.contains(q)
            | activite["Voyage"].fillna("").str.lower().str.contains(q)
            | activite["Traité par"].fillna("").str.lower().str.contains(q)
        )
        activite = activite[mask]
    st.dataframe(activite, width='stretch', hide_index=True)

with tab_agent:
    par_agent = (
        dff.groupby("agent")
           .agg(manifestes=("id", "count"), bl=("nb_bl", "sum"), volume=("volume_total", "sum"),
                temps_moyen=("duree_traitement_sec", "mean"))
           .reset_index()
           .sort_values("manifestes", ascending=False)
    )

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

    st.subheader("Détail par intervenant")
    par_agent_affiche = par_agent.rename(columns={
        "agent": "Intervenant", "manifestes": "Manifestes", "bl": "B/L", "volume": "Volume",
    })
    par_agent_affiche["Temps moyen"] = par_agent["temps_moyen"].apply(format_duree)
    st.dataframe(
        par_agent_affiche.drop(columns=["temps_moyen"]),
        width='stretch', hide_index=True,
    )

    st.subheader("Tendance d'un intervenant")
    agent_select = st.selectbox("Choisir un intervenant", par_agent["agent"], help="Affiche l'évolution de cette personne sur la période et la granularité sélectionnées ci-dessus.")
    d_agent = dff[dff["agent"] == agent_select]
    trend_agent = (
        d_agent.set_index("horodatage").resample(freq)
               .agg(manifestes=("id", "count")).reset_index()
    )
    fig5 = px.line(
        trend_agent, x="horodatage", y="manifestes", markers=True,
        title=f"{agent_select} — manifestes par {freq_label}",
        color_discrete_sequence=[PALETTE["orange"]],
    )
    fig5.update_layout(**PLOT_LAYOUT, yaxis_title="Manifestes", xaxis_title="")
    apply_date_axis(fig5)
    st.plotly_chart(fig5, width='stretch')
