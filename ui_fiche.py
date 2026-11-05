"""Composant UI : fiche de dépouillement (comptage USED / NEW / 20' / 40' / >50m3
/ BOLSTER / DIVERS) calculée depuis les unités extraites de tout type de manifeste."""
import hashlib

import pandas as pd
import streamlit as st

import fiche_depouillement as fd


def render_fiche_depouillement(units, prefix="fiche"):
    st.subheader("Fiche de dépouillement")
    st.caption("Règles dans « Décompte et passage USED vers NEW » et l'onglet Méthode de "
               "l'Excel. À vérifier et ajuster avant usage.")
    if not units:
        st.info("Aucune unité à compter.")
        return
    df = pd.DataFrame(units)
    pairs = df[["Navire", "Voyage"]].drop_duplicates().values.tolist()
    navire, voyage = pairs[0]
    if len(pairs) > 1:
        labels = [f"{n} / {v}" for n, v in pairs]
        idx = labels.index(st.radio("Navire / voyage", labels, horizontal=True,
                                    key=f"{prefix}_nav"))
        navire, voyage = pairs[idx]
    sel = [u for u in units if u["Navire"] == navire and u["Voyage"] == voyage]

    compteurs = st.container()      # au-dessus des cases, calculés après elles
    sel = _passage_agent(sel, f"{prefix}_{navire}_{voyage}")

    with compteurs:
        _compteurs(sel)
    _detail(sel, navire, voyage, prefix)


def _passage_agent(sel, cle):
    """Propose le passage USED vers NEW ; -> unités avec les passages cochés."""
    propos = fd.propositions_passage(sel)
    if not propos:
        return sel
    st.markdown("**Proposition de passage USED vers NEW**")
    st.caption("Véhicules sans état écrit au manifeste. Cochez ceux à passer en NEW : "
               "rien ne bascule sans votre choix.")
    df = pd.DataFrame(propos).drop(columns="cle")
    df.insert(0, "Passer en NEW", False)
    # La clé suit le contenu : un autre manifeste ne reprend pas les cases cochées.
    empreinte = hashlib.sha256(repr(propos).encode()).hexdigest()[:12]
    edite = st.data_editor(df, hide_index=True, width="stretch", key=f"{cle}_{empreinte}",
                           disabled=[c for c in df.columns if c != "Passer en NEW"])
    return fd.appliquer_passage(sel, [propos[i]["cle"] for i in edite.index[edite["Passer en NEW"]]])


def _compteurs(sel):
    counts = fd.count_by_category(sel)
    base = [c for c in fd.CATS if c not in (fd.CAT_PKG_VEH, fd.CAT_PKG_COLIS)]
    cols = st.columns(len(base) + 1)
    for col, cat in zip(cols, base):
        col.metric(cat, counts[cat])
    cols[-1].metric("TOTAL unités", sum(counts.values()))
    cols = st.columns(len(base) + 1)
    pkg = fd.resume_packages(sel)
    cols[0].metric(fd.CAT_PKG_VEH, pkg["veh"], f"{pkg['vehicules']} véhicules",
                   delta_color="off", delta_arrow="off")
    cols[1].metric(fd.CAT_PKG_COLIS, pkg["colis"])
    cols[2].metric("Packages", pkg["total"])

    low = sum(1 for u in sel if u["Fiabilité"] == "LOW")
    if low:
        st.warning(f"{low} unité(s) de fiabilité LOW — libellé non reconnu ou statut Used/New "
                   "non écrit : à vérifier ci-dessous.")


def _detail(sel, navire, voyage, prefix):
    sub = pd.DataFrame(
        [{"Catégorie": c, "Sous-type": s, "Nombre": n}
         for (c, s), n in sorted(fd.count_by_subtype(sel).items(),
                                 key=lambda kv: (fd.CATS.index(kv[0][0]), kv[0][1]))])
    st.dataframe(sub, hide_index=True, width="stretch")

    lignes = fd.detail_packages(sel)
    if lignes:
        with st.expander(f"Châssis des packages véhicules ({len(lignes)})"):
            st.dataframe(pd.DataFrame(lignes), hide_index=True, width="stretch")

    with st.expander("Détail des unités"):
        cat_f = st.multiselect("Filtrer par catégorie", fd.CATS, key=f"{prefix}_cat")
        d = pd.DataFrame(sel)
        if cat_f:
            d = d[d["Catégorie"].isin(cat_f)]
        st.dataframe(d.drop(columns=["Navire", "Voyage", "Groupe package", "Packages du groupe"], errors="ignore"), hide_index=True,
                     width="stretch")

    buf = fd.build_fiche_excel(sel, navire, voyage)
    st.download_button(
        f":material/download: Télécharger la fiche {navire}_{voyage}.xlsx", data=buf,
        file_name=f"Fiche_depouillement_{navire}_{voyage}".replace(" ", "_") + ".xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"{prefix}_dl")
