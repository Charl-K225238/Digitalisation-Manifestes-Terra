"""Page Activité — tableau de bord de l'activité du terminal (RORO, TEU,
véhicules, escales) construit depuis les données de la page Stats Flash.

Lecture seule : aucune saisie ici. Les chiffres viennent de ce qui a été
chargé et corrigé dans « Stats Flash & Reporting ». L'export Excel en bas de
page fournit des tables plates à importer dans Power BI si besoin.
"""
import pathlib
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import bi_export
import stats_flash_builder as sfb
import stats_flash_parser as sfp
import stats_store as store
import tracking
from ui_helpers import PALETTE, SEQUENTIAL_BLUE, help_expander

MOIS = [m.capitalize() for m in sfp.MOIS_FR]
INK, MUTED, GRID = "#1b2430", "#5b6675", "#e6e9ee"
TYPE_COLOR = {"Ro/Ro": PALETTE["blue"], "Car carrier": PALETTE["orange"], "Lo/Lo": PALETTE["aqua"]}
LAYOUT = dict(template="plotly_white", font=dict(family="Segoe UI, sans-serif", color=INK, size=13),
              margin=dict(t=56, l=10, r=10, b=10), hoverlabel=dict(font_size=13),
              legend=dict(orientation="h", y=-0.15, x=0, traceorder="normal"))


def fnum(v):
    return "—" if v is None or pd.isna(v) else f"{v:,.0f}".replace(",", " ")


def fpct(v):
    return None if v is None or pd.isna(v) else f"{v * 100:+.1f} % vs N-1".replace(".", ",")


def style(fig, title, ytitle=""):
    fig.update_layout(**LAYOUT, title=dict(text=title, x=0, font=dict(size=15)), yaxis_title=ytitle,
                      xaxis_title="")
    fig.update_xaxes(showgrid=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, tickformat=",.0f")
    return fig


st.title("📈 Activité du terminal")
st.caption("RORO, TEU, véhicules et escales, à partir des mois chargés dans Stats Flash & Reporting. "
           "Lecture seule : pour corriger un chiffre, passez par cette page-là.")

vals = store.load_values()
esc = store.load_escales()
if vals.empty or vals[(vals["nature"] == "realise") & (vals["mois"] > 0)].empty:
    st.info("Aucune donnée pour le moment. Chargez un mois (ou amorcez le référentiel) dans "
            "**Stats Flash & Reporting**, puis revenez ici.")
    st.stop()

real = vals[(vals["nature"] == "realise") & (vals["mois"] > 0)]
periodes = sorted({(int(a), int(m)) for a, m in real[["annee", "mois"]].itertuples(index=False)}, reverse=True)

c1, c2 = st.columns([2, 3])
with c1:
    annee, mois = st.selectbox("Mois affiché", periodes,
                               format_func=lambda p: f"{MOIS[p[1] - 1]} {p[0]}")


def serie(ind, an):
    d = real[(real["annee"] == an) & (real["indicateur"] == ind)].set_index("mois")["valeur"]
    return [d.get(m) if m in d.index and pd.notna(d.get(m)) else None for m in range(1, 13)]


def budget(ind):
    b = vals[(vals["nature"] == "budget") & (vals["annee"] == annee) & (vals["mois"] == 0)
             & (vals["indicateur"] == ind)]["valeur"]
    return float(b.iloc[0]) if len(b) and pd.notna(b.iloc[0]) else None


def cur(ind, an=None, m=None):
    s = serie(ind, an or annee)
    return s[(m or mois) - 1]


# ---------------------------------------------------------------------------
# Chiffres clés
# ---------------------------------------------------------------------------
st.markdown(f"#### {MOIS[mois - 1]} {annee}")
cols = st.columns(5)
for col, (ind, lab) in zip(cols, [("escales", "Escales"), ("teu", "TEU"), ("roro", "RORO"),
                                  ("neufs", "Véhicules neufs"), ("usages", "Véhicules usagés")]):
    v, p = cur(ind), cur(ind, annee - 1)
    d = None if v is None or p in (None, 0) else (v - p) / p
    col.metric(lab, fnum(v), fpct(d))
bt = []
for ind, lab in [("escales", "Escales"), ("teu", "TEU"), ("roro", "RORO"), ("neufs", "Véhicules neufs"),
                 ("usages", "Véhicules usagés")]:
    b, v = budget(ind), cur(ind)
    bt.append({"Indicateur": lab, "Réalisé": fnum(v), "Budget du mois": fnum(b),
               "Écart vs budget": "—" if b in (None, 0) or v is None else f"{(v - b) / b * 100:+.1f} %".replace(".", ",")})
st.dataframe(pd.DataFrame(bt), hide_index=True, width="stretch")
st.caption("« — » : budget ou année précédente absent. Les écarts vs N-1 comparent au même mois de l'année précédente.")

st.divider()

# ---------------------------------------------------------------------------
# Évolution mensuelle : RORO et TEU (deux graphiques, jamais deux axes)
# ---------------------------------------------------------------------------
labels = sfb.MOIS_COURT


def monthly_bars(ind, title):
    s26, s25, b = serie(ind, annee), serie(ind, annee - 1), budget(ind)
    fig = go.Figure()
    fig.add_bar(x=labels, y=s26, name=str(annee), marker=dict(color=PALETTE["blue"], cornerradius=4),
                hovertemplate="%{x} : %{y:,.0f}<extra>" + str(annee) + "</extra>")
    if any(v is not None for v in s25):
        fig.add_scatter(x=labels, y=s25, mode="markers", name=str(annee - 1),
                        marker=dict(color=PALETTE["orange"], size=10, line=dict(color="white", width=2)),
                        hovertemplate="%{x} : %{y:,.0f}<extra>" + str(annee - 1) + "</extra>")
    if b is not None:
        fig.add_scatter(x=labels, y=[b] * 12, mode="lines", name="Budget / mois",
                        line=dict(color=MUTED, width=2, dash="dash"),
                        hovertemplate="Budget : %{y:,.0f}<extra></extra>")
    fig.update_layout(bargap=0.35)
    return style(fig, title)


g1, g2 = st.columns(2)
with g1:
    st.plotly_chart(monthly_bars("roro", f"RORO par mois, {annee}"), width="stretch")
with g2:
    st.plotly_chart(monthly_bars("teu", f"TEU par mois, {annee}"), width="stretch")
st.caption("Barres : année affichée. Points : même mois de l'année précédente, quand il est connu. "
           "Pointillés : budget mensuel.")

g3, g4 = st.columns(2)
with g3:
    fig = go.Figure()
    for ind, name, color in [("neufs", "Neufs", PALETTE["blue"]), ("usages", "Usagés", PALETTE["orange"])]:
        fig.add_bar(x=labels, y=serie(ind, annee), name=name,
                    marker=dict(color=color, line=dict(color="white", width=2)),
                    hovertemplate="%{x} : %{y:,.0f}<extra>" + name + "</extra>")
    fig.update_layout(barmode="stack", bargap=0.35)
    st.plotly_chart(style(fig, f"Véhicules neufs et usagés, {annee}"), width="stretch")
with g4:
    fig = go.Figure()
    tr = [("t_lt15", "Moins de 15 m³", SEQUENTIAL_BLUE[1]), ("t_15_50", "15 à 50 m³", SEQUENTIAL_BLUE[3]),
          ("t_gt50", "Plus de 50 m³", SEQUENTIAL_BLUE[5])]
    for ind, name, color in tr:
        fig.add_bar(x=labels, y=serie(ind, annee), name=name,
                    marker=dict(color=color, line=dict(color="white", width=2)),
                    hovertemplate="%{x} : %{y:,.0f}<extra>" + name + "</extra>")
    fig.update_layout(barmode="stack", bargap=0.35)
    st.plotly_chart(style(fig, f"Tranches de volume, {annee}"), width="stretch")

# ---------------------------------------------------------------------------
# Escales du mois sélectionné
# ---------------------------------------------------------------------------
st.divider()
st.markdown(f"#### Escales de {MOIS[mois - 1].lower()} {annee}")
em = esc[(esc["annee"] == annee) & (esc["mois"] == mois)] if not esc.empty else esc
if em.empty:
    st.info("Pas de détail par navire pour ce mois : ses valeurs viennent du rapport existant. "
            "Chargez le classeur et l'extrait PAA du mois dans Stats Flash pour voir les navires.")
else:
    d = em.copy()
    for c in ["roro", "teu", "neufs", "usages", "transit", "duree_escale_h", "roro_paa"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["type_navire"] = d["type_navire"].fillna("").replace("", "Non rapproché")
    d["debut"] = pd.to_datetime(d["debut"])
    d["fin"] = pd.to_datetime(d["fin"])

    k = st.columns(4)
    k[0].metric("Navires", fnum(len(d)))
    k[1].metric("Véhicules par escale", fnum(d["roro"].sum() / len(d)))
    dm = d["duree_escale_h"].mean()
    k[2].metric("Durée moyenne d'escale", "—" if pd.isna(dm) else f"{dm:.1f} h".replace(".", ","))
    k[3].metric("Part de Hinterland", "—" if d["roro"].sum() == 0 else f"{d['transit'].sum() / d['roro'].sum() * 100:.0f} %")

    s1, s2 = st.columns(2)
    with s1:
        top = d.sort_values("roro")
        fig = go.Figure()
        for t in [t for t in list(TYPE_COLOR) + ["Non rapproché"] if (top["type_navire"] == t).any()]:
            sub = top[top["type_navire"] == t]
            fig.add_bar(y=sub["navire"], x=sub["roro"], orientation="h", name=t,
                        marker=dict(color=TYPE_COLOR.get(t, MUTED), cornerradius=4),
                        customdata=sub[["teu", "duree_escale_h"]].fillna(0).values,
                        hovertemplate="<b>%{y}</b><br>RORO : %{x:,.0f}<br>TEU : %{customdata[0]:,.0f}"
                                      "<br>Durée : %{customdata[1]:.1f} h<extra>" + t + "</extra>")
        fig.update_layout(height=max(340, 26 * len(top) + 110), bargap=0.3, barmode="overlay")
        style(fig, "Véhicules par navire")
        fig.update_yaxes(tickformat=None, gridcolor="rgba(0,0,0,0)", categoryorder="array",
                         categoryarray=list(top["navire"]))
        st.plotly_chart(fig, width="stretch")
    with s2:
        sc = d.dropna(subset=["duree_escale_h"])
        fig = go.Figure()
        for t in [t for t in TYPE_COLOR if t in set(sc["type_navire"])] + (
                ["Non rapproché"] if (sc["type_navire"] == "Non rapproché").any() else []):
            s = sc[sc["type_navire"] == t]
            fig.add_scatter(x=s["duree_escale_h"], y=s["roro"], mode="markers", name=t,
                            marker=dict(size=13, color=TYPE_COLOR.get(t, MUTED),
                                        line=dict(color="white", width=2)),
                            text=s["navire"],
                            hovertemplate="<b>%{text}</b><br>Durée : %{x:.1f} h<br>RORO : %{y:,.0f}<extra></extra>")
        style(fig, "Durée d'escale et véhicules")
        fig.update_xaxes(title="Durée d'escale (heures)", showgrid=True, gridcolor=GRID)
        fig.update_yaxes(title="Véhicules")
        st.plotly_chart(fig, width="stretch")

    ecart = d[(d["roro_paa"].notna()) & ((d["roro"] - d["roro_paa"]).abs() > 0)]
    if not ecart.empty:
        st.markdown("**À vérifier : écarts entre le classeur et le PAA**")
        st.dataframe(pd.DataFrame({"Navire": ecart["navire"], "RORO classeur": ecart["roro"].map(fnum),
                                   "RORO PAA": ecart["roro_paa"].map(fnum),
                                   "Écart": (ecart["roro"] - ecart["roro_paa"]).map(fnum)}),
                     hide_index=True, width="stretch")
    st.caption("La durée d'escale va du début à la fin des opérations (dates PAA ou classeur). "
               "Elle mesure le temps à quai travaillé, pas l'attente avant accostage.")

# ---------------------------------------------------------------------------
# Qualité des données
# ---------------------------------------------------------------------------
st.divider()
st.markdown("#### Qualité des données")
corr = real[real["valeur_saisie"].notna()]
log = store.load_log()
q = st.columns(3)
q[0].metric(f"Mois renseignés en {annee}", fnum(sum(1 for a, _ in periodes if a == annee)))
q[1].metric("Valeurs corrigées à la main", fnum(len(corr)))
q[2].metric("Corrections journalisées", fnum(len(log)))
if not log.empty:
    lg = log.head(10).copy()
    lg["indicateur"] = lg["indicateur"].map(lambda k: " · ".join(sfb.IND_LABEL.get(k, ("", k))))
    st.dataframe(lg[["horodatage", "annee", "mois", "indicateur", "valeur_calculee", "nouvelle_valeur",
                     "motif", "agent"]].rename(columns={
        "horodatage": "Date", "annee": "Année", "mois": "Mois", "indicateur": "Indicateur",
        "valeur_calculee": "Calculé", "nouvelle_valeur": "Retenu", "motif": "Motif", "agent": "Par"}),
        hide_index=True, width="stretch")

with st.expander("Voir les chiffres du graphique (tableau)"):
    tab = pd.DataFrame({"Mois": labels})
    for ind, name in [("roro", "RORO"), ("teu", "TEU"), ("neufs", "Neufs"), ("usages", "Usagés"),
                      ("t_lt15", "< 15 m³"), ("t_15_50", "15-50 m³"), ("t_gt50", "> 50 m³")]:
        tab[name] = [fnum(v) for v in serie(ind, annee)]
    st.dataframe(tab, hide_index=True, width="stretch")

# ---------------------------------------------------------------------------
# Export pour Power BI
# ---------------------------------------------------------------------------
st.divider()
st.markdown("#### Exporter pour Power BI")
st.caption("Un classeur Excel avec une feuille par table (indicateurs, mois, escales, corrections, "
           "traitements, calendrier). Dans Power BI : Obtenir des données › Excel › cochez les tables.")
if st.button("Préparer l'export Excel", key="act_prep_export"):
    try:
        trait = tracking.read_log()
    except Exception:
        trait = None
    tables = bi_export.prepare_tables(vals, esc, log, trait)
    st.session_state["_act_export"] = bi_export.build_powerbi_workbook(tables)
if "_act_export" in st.session_state:
    st.download_button("⬇️ Télécharger le classeur Power BI", st.session_state["_act_export"],
                       file_name="TERRA_activite_PowerBI.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       type="primary")

with help_expander("ℹ️ Comment lire cette page"):
    st.markdown(
        "- **Mois affiché** change les chiffres clés et la section « Escales ».\n"
        "- **Barres** : valeur du mois. **Points** : même mois l'an dernier. **Pointillés** : budget mensuel.\n"
        "- **Tranches** : part de chaque tranche de volume (source : extrait PAA).\n"
        "- **Écarts classeur / PAA** : probable erreur de saisie dans l'un des deux fichiers.\n"
        "- Les chiffres sont ceux de Stats Flash, corrections manuelles comprises."
    )
