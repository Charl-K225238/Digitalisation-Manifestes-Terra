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

@st.cache_data(ttl=60, show_spinner=False)
def _cached_read_log(): return tracking.read_log()
from ui_helpers import CATEGORICAL_SEQUENCE, PALETTE, PLOT_TEMPLATE, help_expander, format_duree

st.title("Tableau de bord — Suivi de performance")
st.caption(
    "Volumes traités et temps de structuration, au global et par intervenant, "
    "avec vue hebdomadaire ou mensuelle."
)

with help_expander(":material/info: Comment lire ce tableau de bord ?"):
    st.markdown(
        """
- **Période** filtre les traitements pris en compte (semaine en cours, mois en
  cours, année en cours, tout l'historique, ou une plage personnalisée).
- **Intervenant(s)** limite l'analyse à une ou plusieurs personnes — laissez le
  champ vide pour tout le monde. Tapez pour rechercher dans la liste.
- **Granularité** choisit le pas des courbes de tendance : semaine ou mois.
- **Manifestes traités** : nombre de fichiers PDF passés dans l'application sur
  la période sélectionnée.
- **Temps moyen** : temps mis par l'outil pour extraire un manifeste,
  du clic sur *Lancer le traitement* jusqu'au résultat.
- **Relus et validés** : part des manifestes relus par un agent
  (case « Vérifié » cochée).
- Le **Δ** à côté d'un indicateur compare la période sélectionnée à la période
  équivalente précédente (ex : cette semaine vs semaine dernière).
        """
    )

# Nettoyage silencieux d'éventuelles lignes issues d'anciens tests internes —
# n'affecte pas les traitements réels.
tracking.clear_demo_data()

df = _cached_read_log()

if df.empty:
    st.info(
        "Ce tableau de bord est vide pour le moment. Il se remplit "
        "automatiquement à chaque manifeste traité depuis la page "
        "**:material/inventory_2: Structuration des manifestes** — commencez par y déposer un PDF."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Visibilité selon le rôle — un Agent ne voit que sa propre activité
# ---------------------------------------------------------------------------
_identity = st.session_state.get("identity")
_user_role = (_identity or {}).get("role", "")
_user_name = (_identity or {}).get("name", "")

# Rôles superviseurs : voient tout le monde
_SUPERVISOR_ROLES = {"Chef de service", "Chef de la planification", "Analyste Data"}
_is_supervisor = _user_role in _SUPERVISOR_ROLES or not _user_name

if not _is_supervisor:
    # Agent : filtrer silencieusement sur son propre nom
    df = df[df["agent"] == _user_name].copy()
    if df.empty:
        st.info(
            f"Aucune activité enregistrée pour **{_user_name}** pour le moment. "
            "Traitez un premier manifeste depuis **:material/inventory_2: Structuration**."
        )
        st.stop()
    st.info(f"Vue personnelle — activité de **{_user_name}** uniquement.", icon=":material/person:")

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
    if _is_supervisor:
        agents_dispo = sorted(a for a in df["agent"].dropna().unique() if a)
        agents_filtre = st.multiselect(
            "Intervenant(s)", agents_dispo, placeholder="Tout le monde",
            help="Tapez pour rechercher. Laissez vide pour inclure tout le monde.",
        )
    else:
        agents_filtre = []  # déjà filtré sur _user_name ci-dessus

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
# Indicateurs clés : cinq chiffres qui disent si l'outil rend service
# ---------------------------------------------------------------------------
if dff.empty:
    st.warning("Aucune donnée pour cette période / ces intervenants.")
    st.stop()

n_manifestes = len(dff)
n_verifie = int(dff["verifie"].sum())
taux_verif = n_verifie / n_manifestes * 100 if n_manifestes else 0
n_prev_total = len(dprev) if not dprev.empty else 0
taux_verif_prev = (int(dprev["verifie"].sum()) / n_prev_total * 100) if n_prev_total else 0
volume = int(dff["volume_total"].sum())

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Manifestes traités", n_manifestes, delta=delta_str(n_manifestes, n_prev_total),
          help="Fichiers PDF traités sur la période (Δ vs période équivalente précédente).")
k2.metric("Volume structuré (unités)", volume,
          delta=delta_str(volume, int(dprev["volume_total"].sum()) if not dprev.empty else 0),
          help="Véhicules, conteneurs et colis structurés.")
k3.metric("Temps moyen par manifeste", format_duree(dff["duree_traitement_sec"].mean()),
          help="Du lancement du traitement au résultat. À comparer à la saisie manuelle habituelle.")
k4.metric("Relus et validés", f"{taux_verif:.0f}%",
          delta=f"{taux_verif - taux_verif_prev:+.0f}pp" if n_prev_total else None,
          help=f"{n_verifie} manifeste(s) relu(s) sur {n_manifestes} (case « Vérifié »).")
if _is_supervisor:
    k5.metric("Intervenants actifs", dff["agent"].nunique(), help="Personnes ayant traité au moins un manifeste.")
else:
    k5.metric("Navires", dff["navire"].dropna().nunique(), help="Navires distincts traités.")

st.divider()

# ---------------------------------------------------------------------------
# Vues
# ---------------------------------------------------------------------------
tab_names = [":material/trending_up: Vue d'ensemble", ":material/directions_boat: Navires"] + ([":material/person: Intervenants"] if _is_supervisor else [])
tabs = dict(zip(tab_names, st.tabs(tab_names)))

freq = "W" if granularite == "Semaine" else "ME"
freq_label = "semaine" if freq == "W" else "mois"

PLOT_LAYOUT = dict(template=PLOT_TEMPLATE, margin=dict(t=48, l=10, r=10, b=10))
DATE_TICK = dict(
    dtick=7 * 24 * 60 * 60 * 1000 if freq == "W" else "M1",
    tickformat="%d %b" if freq == "W" else "%b %Y",
)


def apply_date_axis(fig):
    """Axe temporel lisible (jour/mois), même sur une période étroite."""
    fig.update_xaxes(**DATE_TICK)
    return fig


def hbar(df_, x, y, title, color, xtitle, pct=False):
    """Barres horizontales triées, valeur écrite au bout de chaque barre."""
    d_ = df_.sort_values(x, ascending=True)
    fig_ = px.bar(d_, x=x, y=y, orientation="h", title=title, text=x, color_discrete_sequence=[color])
    fig_.update_traces(texttemplate="%{text}%" if pct else "%{text}", textposition="outside", cliponaxis=False)
    fig_.update_layout(**PLOT_LAYOUT, yaxis_title="", xaxis_title=xtitle,
                       height=max(260, 34 * len(d_) + 100))
    return fig_


# ---------------------------------------------------------------------------
# Vue d'ensemble : une courbe, une répartition, l'activité récente
# ---------------------------------------------------------------------------
with tabs[":material/trending_up: Vue d'ensemble"]:
    trend = (dff.set_index("horodatage").resample(freq)
                .agg(manifestes=("id", "count"), volume=("volume_total", "sum")).reset_index())
    c1, c2 = st.columns([3, 2])
    with c1:
        fig = px.bar(trend, x="horodatage", y="manifestes", title=f"Manifestes traités par {freq_label}",
                     color_discrete_sequence=[PALETTE["blue"]])
        fig.update_layout(**PLOT_LAYOUT, yaxis_title="Manifestes", xaxis_title="", bargap=0.35)
        apply_date_axis(fig)
        st.plotly_chart(fig, width="stretch")
    with c2:
        rep = dff[["nb_vehicules", "nb_conteneurs", "nb_colis"]].sum()
        rep.index = ["Véhicules", "Conteneurs", "Colis"]
        rep = rep[rep > 0].reset_index()
        rep.columns = ["Type", "Unités"]
        if rep.empty:
            st.caption("Aucune unité à répartir sur la période.")
        else:
            st.plotly_chart(hbar(rep, "Unités", "Type", "Volume par type", PALETTE["aqua"], "Unités"),
                            width="stretch")

    st.subheader("Activité récente")
    recherche_activite = st.text_input(
        ":material/search: Rechercher", placeholder="Navire, voyage, intervenant…", key="recherche_activite",
        help="Pour l'historique complet avec PDF/Excel téléchargeables, voir la page **:material/folder_open: Archives**.")
    activite = (
        dff[["horodatage", "agent", "navire", "voyage", "type_cargo", "nb_bl", "volume_total",
             "duree_traitement_sec", "verifie"]]
        .rename(columns={"horodatage": "Date", "agent": "Traité par", "navire": "Navire", "voyage": "Voyage",
                         "type_cargo": "Type", "nb_bl": "B/L", "volume_total": "Volume"})
        .sort_values("Date", ascending=False)
    )
    activite["Durée"] = activite["duree_traitement_sec"].apply(format_duree)
    activite["Vérifié"] = activite["verifie"].apply(lambda v: "Oui" if v else "")
    activite = activite.drop(columns=["duree_traitement_sec", "verifie"])
    if recherche_activite:
        q = recherche_activite.strip().lower()
        activite = activite[activite["Navire"].fillna("").str.lower().str.contains(q)
                            | activite["Voyage"].fillna("").str.lower().str.contains(q)
                            | activite["Traité par"].fillna("").str.lower().str.contains(q)]
    st.dataframe(activite, width="stretch", hide_index=True)

# ---------------------------------------------------------------------------
# Navires : un graphique au choix + le tableau
# ---------------------------------------------------------------------------
with tabs[":material/directions_boat: Navires"]:
    nav_df = dff[dff["navire"].notna() & (dff["navire"] != "")]
    if nav_df.empty:
        st.info("Aucun navire identifié sur cette période.")
    else:
        par_navire = (nav_df.groupby("navire")
                      .agg(manifestes=("id", "count"), bl=("nb_bl", "sum"), volume=("volume_total", "sum"),
                           nb_transit=("nb_transit", "sum"), verifie=("verifie", "sum"))
                      .reset_index().sort_values("volume", ascending=False))
        par_navire["taux_verif"] = (par_navire["verifie"] / par_navire["manifestes"] * 100).round(0).astype(int)
        crit = st.segmented_control("Classer par", ["Volume", "Manifestes", "B/L"], default="Volume",
                                    required=True, key="dash_nav_crit")
        col = {"Volume": "volume", "Manifestes": "manifestes", "B/L": "bl"}[crit]
        top_n = min(10, len(par_navire))
        st.plotly_chart(hbar(par_navire.nlargest(top_n, col), col, "navire",
                             f"Top {top_n} navires : {crit.lower()}", PALETTE["blue"], crit),
                        width="stretch")
        st.dataframe(par_navire.rename(columns={
            "navire": "Navire", "manifestes": "Manifestes", "bl": "B/L", "volume": "Volume",
            "nb_transit": "B/L transit", "taux_verif": "Relus (%)"}).drop(columns=["verifie"]),
            width="stretch", hide_index=True)

# ---------------------------------------------------------------------------
# Intervenants (superviseurs) : qui traite quoi, et combien est relu
# ---------------------------------------------------------------------------
if ":material/person: Intervenants" in tabs:
    with tabs[":material/person: Intervenants"]:
        par_agent = (dff.groupby("agent")
                     .agg(manifestes=("id", "count"), bl=("nb_bl", "sum"), volume=("volume_total", "sum"),
                          temps_moyen=("duree_traitement_sec", "mean"), verifie=("verifie", "sum"))
                     .reset_index().sort_values("manifestes", ascending=False))
        par_agent["taux_verif"] = (par_agent["verifie"] / par_agent["manifestes"] * 100).round(0).astype(int)
        crit = st.segmented_control("Comparer", ["Manifestes", "Volume", "Relus (%)"], default="Manifestes",
                                    required=True, key="dash_ag_crit")
        col = {"Manifestes": "manifestes", "Volume": "volume", "Relus (%)": "taux_verif"}[crit]
        st.plotly_chart(hbar(par_agent, col, "agent", f"{crit} par intervenant", PALETTE["orange"], crit,
                             pct=(col == "taux_verif")), width="stretch")
        aff = par_agent.rename(columns={"agent": "Intervenant", "manifestes": "Manifestes", "bl": "B/L",
                                        "volume": "Volume", "taux_verif": "Relus (%)"})
        aff["Temps moyen"] = par_agent["temps_moyen"].apply(format_duree)
        st.dataframe(aff.drop(columns=["temps_moyen", "verifie"]), width="stretch", hide_index=True)
