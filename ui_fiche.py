"""Composant UI : fiche de dépouillement (comptage USED / NEW / 20' / 40' / >50m3
/ BOLSTER / DIVERS) calculée depuis les B/L déjà extraits de l'onglet Grimaldi."""
import pandas as pd
import streamlit as st

import fiche_depouillement as fd


def render_fiche_depouillement(records, prefix="fiche"):
    st.subheader("Fiche de dépouillement")
    st.caption("Comptage par catégorie Grimaldi (libellé du manifeste, pas le volume). "
               "À vérifier et ajuster avant usage.")
    units = fd.build_units(records)
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

    counts = fd.count_by_category(sel)
    cols = st.columns(len(fd.CATS) + 1)
    for col, cat in zip(cols, fd.CATS):
        col.metric(cat, counts[cat])
    cols[-1].metric("TOTAL", sum(counts.values()))

    low = sum(1 for u in sel if u["Fiabilité"] == "LOW")
    if low:
        st.warning(f"{low} unité(s) de fiabilité LOW — libellé non reconnu ou statut Used/New "
                   "introuvable : à vérifier dans le détail.")

    sub = pd.DataFrame(
        [{"Catégorie": c, "Sous-type": s, "Nombre": n}
         for (c, s), n in sorted(fd.count_by_subtype(sel).items(),
                                 key=lambda kv: (fd.CATS.index(kv[0][0]), kv[0][1]))])
    st.dataframe(sub, hide_index=True, use_container_width=True)

    with st.expander("Détail des unités"):
        cat_f = st.multiselect("Filtrer par catégorie", fd.CATS, key=f"{prefix}_cat")
        d = pd.DataFrame(sel)
        if cat_f:
            d = d[d["Catégorie"].isin(cat_f)]
        st.dataframe(d.drop(columns=["Navire", "Voyage"]), hide_index=True,
                     use_container_width=True)

    buf = fd.build_fiche_excel(sel, navire, voyage)
    st.download_button(
        f"⬇ Télécharger la fiche {navire}_{voyage}.xlsx", data=buf,
        file_name=f"Fiche_depouillement_{navire}_{voyage}".replace(" ", "_") + ".xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"{prefix}_dl")
