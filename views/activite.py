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
from ui_helpers import PALETTE, PLOT_TEMPLATE, SEQUENTIAL_BLUE, TERRA, help_expander

MOIS = [m.capitalize() for m in sfp.MOIS_FR]
INK, MUTED, GRID = TERRA["text"], TERRA["muted"], TERRA["grid"]
TYPE_COLOR = {"Ro/Ro": PALETTE["blue"], "Car carrier": PALETTE["orange"], "Lo/Lo": PALETTE["aqua"]}
LAYOUT = dict(template=PLOT_TEMPLATE, margin=dict(t=56, l=10, r=10, b=10),
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


st.title("Activité du terminal")
st.caption("RORO, TEU, véhicules et escales, à partir des mois chargés dans Stats Flash & Reporting. "
           "Lecture seule : pour corriger un chiffre, passez par Stats Flash & Reporting.")

with help_expander(":material/info: Comment lire cette page"):
    st.markdown(
        "- **Mois affiché** change les chiffres clés et la section « Escales ». **Tous les mois** : cumul de l'année "
        "et graphiques mois par mois ; **un mois précis** : les graphiques passent par semaine du mois.\n"
        "- **Barres** : valeur du mois. **Points** : même mois l'an dernier. **Pointillés** : budget mensuel.\n"
        "- **Tranches** : part de chaque tranche de volume (source : extrait PAA).\n"
        "- **Durée d'escale** : du début à la fin des opérations ; ce n'est pas l'attente avant accostage.\n"
        "- **Écarts classeur / PAA** : probable erreur de saisie dans l'un des deux fichiers.\n"
        "- Les chiffres sont ceux de Stats Flash, corrections manuelles comprises.")

vals = store.load_values()
esc = store.load_escales()
if vals.empty or vals[(vals["nature"] == "realise") & (vals["mois"] > 0)].empty:
    st.info("Aucune donnée pour le moment. Chargez un mois (ou amorcez le référentiel) dans "
            "**Stats Flash & Reporting**, puis revenez ici.")
    st.stop()

real = vals[(vals["nature"] == "realise") & (vals["mois"] > 0)]
periodes = sorted({(int(a), int(m)) for a, m in real[["annee", "mois"]].itertuples(index=False)}, reverse=True)

c1, c2 = st.columns([2, 3])
# Une entrée « Tous les mois » par année, suivie de ses mois (le plus récent par défaut).
OPTIONS = []
for _a in sorted({a for a, _ in periodes}, reverse=True):
    OPTIONS.append((_a, 0))
    OPTIONS += [p for p in periodes if p[0] == _a]
with c1:
    annee, mois = st.selectbox(
        "Mois affiché", OPTIONS, index=OPTIONS.index(periodes[0]),
        format_func=lambda p: f"Tous les mois · {p[0]}" if p[1] == 0 else f"{MOIS[p[1] - 1]} {p[0]}")
TOUS = mois == 0
MOIS_CHARGES = sorted(m for a, m in periodes if a == annee)   # mois renseignés de l'année affichée


def serie(ind, an):
    d = real[(real["annee"] == an) & (real["indicateur"] == ind)].set_index("mois")["valeur"]
    return [d.get(m) if m in d.index and pd.notna(d.get(m)) else None for m in range(1, 13)]


def budget(ind):
    b = vals[(vals["nature"] == "budget") & (vals["annee"] == annee) & (vals["mois"] == 0)
             & (vals["indicateur"] == ind)]["valeur"]
    return float(b.iloc[0]) if len(b) and pd.notna(b.iloc[0]) else None


def budget_periode(ind):
    """Budget du mois affiché ; en vue « Tous les mois », budget mensuel × nombre de mois chargés."""
    b = budget(ind)
    return b * len(MOIS_CHARGES) if (TOUS and b is not None) else b


def cur(ind, an=None, m=None):
    s = serie(ind, an or annee)
    if TOUS and m is None:      # cumul des mois chargés de l'année affichée
        vals_ = [s[k - 1] for k in MOIS_CHARGES if s[k - 1] is not None]
        return float(sum(vals_)) if vals_ else None
    return s[(m or mois) - 1]


# ---------------------------------------------------------------------------
# Chiffres clés
# ---------------------------------------------------------------------------
st.markdown(f"#### Cumul {annee} · {len(MOIS_CHARGES)} mois chargé(s)" if TOUS else f"#### {MOIS[mois - 1]} {annee}")
cols = st.columns(5)
for col, (ind, lab) in zip(cols, [("escales", "Escales"), ("teu", "TEU"), ("roro", "RORO"),
                                  ("neufs", "Véhicules neufs"), ("usages", "Véhicules usagés")]):
    v = cur(ind)
    p = (sum(x for x in (serie(ind, annee - 1)[k - 1] for k in MOIS_CHARGES) if x is not None) or None) if TOUS else cur(ind, annee - 1)
    d = None if v is None or p in (None, 0) else (v - p) / p
    col.metric(lab, fnum(v), fpct(d))
bt = []
for ind, lab in [("escales", "Escales"), ("teu", "TEU"), ("roro", "RORO"), ("neufs", "Véhicules neufs"),
                 ("usages", "Véhicules usagés")]:
    b, v = budget_periode(ind), cur(ind)
    bt.append({"Indicateur": lab, "Réalisé": fnum(v), "Budget cumulé" if TOUS else "Budget du mois": fnum(b),
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


if TOUS:
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

else:
    # ── Détail par semaine du mois choisi (semaines du lundi au dimanche, tronquées au mois) ──
    em_w = esc[(esc["annee"] == annee) & (esc["mois"] == mois)].copy() if not esc.empty else esc
    if em_w.empty:
        st.info("Pas de détail par navire pour ce mois : les graphiques par semaine ont besoin du classeur des "
                "volumes. Chargez-le dans Stats Flash & Reporting, ou choisissez « Tous les mois ».")
    else:
        for c in ["roro", "teu", "neufs", "usages", "paa_lt15", "paa_15_50", "paa_gt50"]:
            em_w[c] = pd.to_numeric(em_w[c], errors="coerce")
        em_w["date_ref"] = pd.to_datetime(em_w["debut"], errors="coerce").fillna(pd.to_datetime(em_w["fin"], errors="coerce"))
        sans_date = int(em_w["date_ref"].isna().sum())
        em_w = em_w.dropna(subset=["date_ref"])
        d1 = pd.Timestamp(year=annee, month=mois, day=1)
        dn = d1 + pd.offsets.MonthEnd(0)
        # bornes des semaines : du 1er du mois jusqu'au premier dimanche, puis lundi-dimanche
        bornes, deb = [], d1
        while deb <= dn:
            fin_s = min(deb + pd.Timedelta(days=6 - deb.weekday()), dn)
            bornes.append((deb, fin_s))
            deb = fin_s + pd.Timedelta(days=1)
        mois_c = MOIS[mois - 1][:4].lower() + "." if len(MOIS[mois - 1]) > 4 else MOIS[mois - 1].lower()
        sem_labels = [f"S{i + 1} · {a_.day}–{b_.day} {mois_c}" for i, (a_, b_) in enumerate(bornes)]

        def par_semaine(col):
            out = []
            for a_, b_ in bornes:
                m_ = (em_w["date_ref"].dt.normalize() >= a_) & (em_w["date_ref"].dt.normalize() <= b_)
                out.append(float(em_w.loc[m_, col].sum()))
            return out

        def barres_sem(col, titre):
            fig = go.Figure()
            fig.add_bar(x=sem_labels, y=par_semaine(col), marker=dict(color=PALETTE["blue"], cornerradius=4),
                        hovertemplate="%{x} : %{y:,.0f}<extra></extra>")
            fig.update_layout(bargap=0.35)
            return style(fig, titre)

        titre_m = f"{MOIS[mois - 1]} {annee}"
        g1, g2 = st.columns(2)
        with g1:
            st.plotly_chart(barres_sem("roro", f"RORO par semaine, {titre_m}"), width="stretch")
        with g2:
            st.plotly_chart(barres_sem("teu", f"TEU par semaine, {titre_m}"), width="stretch")
        g3, g4 = st.columns(2)
        with g3:
            fig = go.Figure()
            for ind, name, color in [("neufs", "Neufs", PALETTE["blue"]), ("usages", "Usagés", PALETTE["orange"])]:
                fig.add_bar(x=sem_labels, y=par_semaine(ind), name=name,
                            marker=dict(color=color, line=dict(color="white", width=2)),
                            hovertemplate="%{x} : %{y:,.0f}<extra>" + name + "</extra>")
            fig.update_layout(barmode="stack", bargap=0.35)
            st.plotly_chart(style(fig, f"Véhicules neufs et usagés par semaine, {titre_m}"), width="stretch")
        with g4:
            if em_w[["paa_lt15", "paa_15_50", "paa_gt50"]].notna().any().any():
                fig = go.Figure()
                for ind, name, color in [("paa_lt15", "Moins de 15 m³", SEQUENTIAL_BLUE[1]),
                                         ("paa_15_50", "15 à 50 m³", SEQUENTIAL_BLUE[3]),
                                         ("paa_gt50", "Plus de 50 m³", SEQUENTIAL_BLUE[5])]:
                    fig.add_bar(x=sem_labels, y=par_semaine(ind), name=name,
                                marker=dict(color=color, line=dict(color="white", width=2)),
                                hovertemplate="%{x} : %{y:,.0f}<extra>" + name + "</extra>")
                fig.update_layout(barmode="stack", bargap=0.35)
                st.plotly_chart(style(fig, f"Tranches de volume par semaine, {titre_m}"), width="stretch")
            else:
                st.info("Tranches de volume par semaine indisponibles : chargez l'extrait PAA du mois.")
        st.caption("Chaque escale est rattachée à la semaine de son début d'opérations. "
                   f"Total des semaines : {fnum(sum(par_semaine('roro')))} RORO · {fnum(sum(par_semaine('teu')))} TEU "
                   f"(rapport mensuel : {fnum(cur('roro'))} RORO · {fnum(cur('teu'))} TEU)."
                   + (f" {sans_date} escale(s) sans date ignorée(s)." if sans_date else ""))

# ---------------------------------------------------------------------------
# Escales du mois sélectionné
# ---------------------------------------------------------------------------
st.divider()
st.markdown(f"#### Escales de {annee} (mois chargés)" if TOUS else f"#### Escales de {MOIS[mois - 1].lower()} {annee}")
em = esc[(esc["annee"] == annee) & ((esc["mois"] == mois) | TOUS)] if not esc.empty else esc
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
        sc = top.dropna(subset=["duree_escale_h"])
        fig = go.Figure()
        fig.add_bar(y=sc["navire"], x=sc["duree_escale_h"], orientation="h", name="Durée d'escale",
                    marker=dict(color=PALETTE["blue"], cornerradius=4), showlegend=False,
                    hovertemplate="<b>%{y}</b><br>Durée : %{x:.1f} h<extra></extra>")
        if len(sc):
            fig.add_vline(x=float(sc["duree_escale_h"].mean()), line=dict(color=MUTED, width=2, dash="dash"),
                          annotation_text="moyenne", annotation_position="top")
        fig.update_layout(height=max(340, 26 * len(top) + 110), bargap=0.3)
        style(fig, "Durée d'escale par navire (heures)")
        fig.update_yaxes(tickformat=None, gridcolor="rgba(0,0,0,0)", categoryorder="array",
                         categoryarray=list(top["navire"]))
        st.plotly_chart(fig, width="stretch")

    ecart = d[(d["roro_paa"].notna()) & ((d["roro"] - d["roro_paa"]).abs() > 0)]
    if not ecart.empty:
        st.markdown("**À vérifier : écarts entre le classeur et le PAA**")
        st.dataframe(pd.DataFrame({"Navire": ecart["navire"], "RORO classeur": ecart["roro"].map(fnum),
                                   "RORO PAA": ecart["roro_paa"].map(fnum),
                                   "Écart": (ecart["roro"] - ecart["roro_paa"]).map(fnum)}),
                     hide_index=True, width="stretch")

# ---------------------------------------------------------------------------
# Données et export (secondaire, replié)
# ---------------------------------------------------------------------------
st.divider()
st.markdown("#### Données et export")
corr = real[real["valeur_saisie"].notna()]
log = store.load_log()

with st.expander("Chiffres du graphique (tableau)"):
    tab = pd.DataFrame({"Mois": labels})
    for ind, name in [("roro", "RORO"), ("teu", "TEU"), ("neufs", "Neufs"), ("usages", "Usagés"),
                      ("t_lt15", "< 15 m³"), ("t_15_50", "15-50 m³"), ("t_gt50", "> 50 m³")]:
        tab[name] = [fnum(v) for v in serie(ind, annee)]
    st.dataframe(tab, hide_index=True, width="stretch")

with st.expander(f"Fiabilité : {len(corr)} valeur(s) corrigée(s) à la main, "
                 f"{sum(1 for a, _ in periodes if a == annee)} mois renseigné(s) en {annee}"):
    if log.empty:
        st.caption("Aucune correction journalisée.")
    else:
        lg = log.head(10).copy()
        lg["indicateur"] = lg["indicateur"].map(lambda k: " · ".join(sfb.IND_LABEL.get(k, ("", k))))
        st.dataframe(lg[["horodatage", "annee", "mois", "indicateur", "valeur_calculee", "nouvelle_valeur",
                         "motif", "agent"]].rename(columns={
            "horodatage": "Date", "annee": "Année", "mois": "Mois", "indicateur": "Indicateur",
            "valeur_calculee": "Calculé", "nouvelle_valeur": "Retenu", "motif": "Motif", "agent": "Par"}),
            hide_index=True, width="stretch")

with st.expander("Exporter pour Power BI"):
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
        st.download_button(":material/download: Télécharger le classeur Power BI", st.session_state["_act_export"],
                           file_name="TERRA_activite_PowerBI.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           type="primary")
