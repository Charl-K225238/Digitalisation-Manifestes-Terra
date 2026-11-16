"""Onglet « Opérations navire » de la page Reporting navire (formulaire DC_GR-117).

3 étapes : Déposer → Compléter → Télécharger. Les fichiers restent en mémoire
de session ; seuls les opérateurs, les règles et les totaux vont dans Supabase.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

import operations_navire as on
import operations_navire_modele as mod
import operations_navire_ocr as ocrmod
import operations_navire_pdf as pdfmod
import operations_navire_store as store
from security_utils import filter_uploads
from ui_helpers import current_identity

K = "opn_"
ORDRE_FICHIERS = ["classification", "general_cargo", "shifting", "time_sheet"]
ETAPES = ["Déposer", "Compléter", "Télécharger"]
LIB_FR = {222: "Voitures moins de 15 m³", 223: "Camions 15 à 50 m³", 224: "Engins 50 m³ et plus",
          141: "Voitures moins de 15 m³ (transbo)", 142: "Camions 15 à 50 m³ (transbo)",
          143: "Engins 50 m³ et plus (transbo)", 263: "Cargo général",
          357: "Voitures moins de 15 m³", 358: "Camions 15 à 50 m³", 359: "Engins 50 m³ et plus",
          301: "Conteneurs 20' vides", 302: "Conteneurs 40' vides", 303: "Bolsters vides", 318: "MAFI vides",
          304: "Conteneurs 20' pleins", 306: "Conteneurs 40' pleins", 314: "Conteneurs 20' reefer",
          316: "Conteneurs 40' reefer", 0: "MAFI pleins",
          127: "Reste à bord · moins de 15 m³", 128: "Reste à bord · 15 à 50 m³", 130: "Reste à bord · 50 m³ et plus",
          134: "Débarqué puis rembarqué · moins de 15 m³", 135: "Débarqué puis rembarqué · 15 à 50 m³",
          136: "Débarqué puis rembarqué · 50 m³ et plus"}
POS_FR = {"S/S": "Reste à bord", "S/S/S": "Débarqué puis rembarqué"}


def _s(k, defaut=None):
    return st.session_state.get(K + k, defaut)


def _set(k, v):
    st.session_state[K + k] = v


def _auteur() -> str:
    i = current_identity() or {}
    return i.get("nom") or i.get("name") or "agent inconnu"


def _reinitialiser():
    for k in [k for k in st.session_state if k.startswith(K) and k != K + "vue"]:
        del st.session_state[k]


def render():
    vue = st.segmented_control("Vue", ["Nouveau formulaire", "Historique"], default="Nouveau formulaire",
                               key=K + "vue", label_visibility="collapsed")
    if vue == "Historique":
        _historique()
        return
    etape = _s("etape", 1)
    st.markdown("  ›  ".join(f"**{i}. {e}**" if i == etape else f"{i}. {e}" for i, e in enumerate(ETAPES, 1)))
    (_deposer, _completer, _telecharger)[etape - 1]()


# ---------------------------------------------------------------- étape 1
AIDE = {"shifting": "Recommandée : shifting complet avec poids",
        "time_sheet": "Conseillé : pré-remplit les heures"}
CONSEILLES = ("shifting", "time_sheet")


def _type_fichier(data: bytes, nom: str) -> str | None:
    if nom.lower().endswith(".pdf"):
        return "time_sheet"
    t = on.detecter_type(data, nom)
    if t == "classification":
        try:
            on.lire_classification(data, nom)
        except Exception:
            return None
        return "classification"
    return t if t in ("general_cargo", "shifting") else None


@st.cache_data(show_spinner=False, max_entries=5)
def _ocr(data: bytes) -> dict:
    return ocrmod.lire_time_sheet(data)


def _deposer():
    st.subheader("Nouveau formulaire")
    ups = st.file_uploader("Déposez les fichiers de l'escale", type=["xls", "xlsx", "ods", "pdf"],
                           accept_multiple_files=True, key=K + "up")
    fichiers, inconnus, doubles = {}, [], []
    for f in filter_uploads(ups):
        data = f.getvalue()
        t = _type_fichier(data, f.name)
        if t is None:
            inconnus.append(f.name)
        elif t in fichiers:
            doubles.append(on.LIBELLE_TYPE[t])
        else:
            fichiers[t] = (data, f.name)
    for n in inconnus:
        st.warning(f"Fichier non reconnu : {n}")
    for t in doubles:
        st.error(f"Deux fichiers « {t} » déposés : n'en gardez qu'un.")

    with st.container(border=True):
        for t in ORDRE_FICHIERS:
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"**{on.LIBELLE_TYPE[t]}**" + (f"  \n:gray[{AIDE[t]}]" if t in AIDE else ""))
            c2.markdown(":green[Reçu]" if t in fichiers else (":orange[Manquant]" if t in CONSEILLES else ":gray[Absent]"))
    meta = {}
    if "classification" in fichiers:
        try:
            nav, voy = on.titre_navire(on.lire_classification(*fichiers["classification"])[0]["titre"])
            meta = {"navire": nav, "voyage": voy}
        except Exception:
            pass
    st.download_button("Télécharger le modèle de fiche shifting",
                       mod.modele_shifting_xlsx(meta.get("navire", ""), meta.get("voyage", "")),
                       file_name="Fiche_shifting.xlsx", icon=":material/download:", on_click="ignore")
    pret = "classification" in fichiers and not doubles
    if not pret:
        st.caption("Il faut au moins un tableau de classification.")
    if st.button("Continuer", type="primary", disabled=not pret):
        _set("fichiers", fichiers)
        _set("meta", meta)
        if "shifting" in fichiers:
            _set("shifting_df", on.lire_fiche_shifting(*fichiers["shifting"]))
        if "time_sheet" in fichiers:
            with st.spinner("Lecture du time sheet…"):
                try:
                    _set("ocr", _ocr(fichiers["time_sheet"][0]))
                except Exception:
                    _set("ocr", {"erreur": True})
        _set("etape", 2)
        st.rerun()


# ---------------------------------------------------------------- étape 2
def _ops():
    ops = store.operateurs()
    return {o["code"]: o["libelle"] for o in ops}


def _calcul(fichiers, armateur, choix_bloc, ts_veh, ts_sh):
    regles = store.regles("bloc")
    regles.update({k: v for k, (_, v) in choix_bloc.items()})
    e = on.Entree(armateur=armateur, regles_bloc=regles, ts_total_vehicules=ts_veh, ts_total_shifting=ts_sh,
                  classifications=[fichiers["classification"]] if "classification" in fichiers else [],
                  general_cargo=fichiers.get("general_cargo"), shifting_df=_s("shifting_df"),
                  positions_shift=_s("positions", {}), source_shift=_s("source_shift", "tableau"))
    return on.calculer(e)


def _dt(label, defaut, jour, key):
    c1, c2 = st.columns([3, 2])
    d = c1.date_input(label, value=defaut.date() if defaut else jour, format="DD/MM/YYYY", key=K + key + "_d")
    h = c2.time_input("Heure", value=defaut.time() if defaut else None, step=60, key=K + key + "_h",
                      label_visibility="hidden")
    return datetime.combine(d, h) if d and h else None


def _blocs_shift(fichiers) -> list[str]:
    blocs = []
    if "classification" in fichiers:
        blocs += [b["bloc"] for f in on.lire_classification(*fichiers["classification"]) if f["page"] == "shifting"
                  for b in f["blocs"]]
    return blocs


def _completer():
    fichiers, meta, ocr = _s("fichiers"), _s("meta", {}), _s("ocr", {})
    noms = _ops()
    if not noms:
        st.error("Aucun opérateur disponible.")
        return
    codes = list(noms)

    # --- Escale
    st.markdown("#### Escale")
    c = st.columns(4)
    navire = c[0].text_input("Navire", value=meta.get("navire", ""), key=K + "navire")
    voyage = c[1].text_input("Voyage", value=meta.get("voyage", ""), key=K + "voyage")
    n_dossier = c[2].text_input("N° dossier", key=K + "dossier")
    type_nav = c[3].text_input("Type de navire", value="CARCAR", key=K + "type")
    armateur = st.selectbox("Armateur", codes, format_func=lambda x: f"{noms[x]} ({x})", key=K + "armateur")
    if ocr.get("erreur"):
        st.warning("Time sheet illisible : saisissez les heures.")
    elif ocr.get("debut"):
        st.caption(":orange[Début, fin des opérations et shifts lus sur le time sheet : à vérifier.]")
    jour = ocr["debut"].date() if ocr.get("debut") else None
    c = st.columns(5)
    vals = {}
    for col, (lab, key, defaut) in zip(c, [("ETA rade", "eta", None), ("Accostage", "acc", None),
                                           ("Début des opérations", "deb", ocr.get("debut")),
                                           ("Fin des opérations", "fin", ocr.get("fin")),
                                           ("Appareillage", "app", None)]):
        with col:
            vals[key] = _dt(lab, defaut, jour, key)
    c = st.columns(4)
    nb_eq = c[0].number_input("Nombre d'équipes", min_value=0, step=1, value=None, key=K + "nbeq")
    eq_att = c[1].number_input("Équipes ayant attendu", min_value=0, step=1, value=None, key=K + "eqatt")
    ps, ds = ocr.get("premier_shift"), ocr.get("dernier_shift")
    with c[2]:
        p_d = st.date_input("Premier shift", value=ps[0] if ps else jour, format="DD/MM/YYYY", key=K + "ps_d")
        p_s = st.selectbox("Premier shift", on.SHIFTS, index=on.SHIFTS.index(ps[1]) if ps else 0,
                           key=K + "ps_s", label_visibility="collapsed")
    with c[3]:
        d_d = st.date_input("Dernier shift", value=ds[0] if ds else jour, format="DD/MM/YYYY", key=K + "ds_d")
        d_s = st.selectbox("Dernier shift", on.SHIFTS, index=on.SHIFTS.index(ds[1]) if ds else 1,
                           key=K + "ds_s", label_visibility="collapsed")
    calc, ctr_ent = on.entete(vals["eta"], vals["acc"], vals["deb"], vals["fin"], vals["app"],
                              (p_d, p_s) if p_d else None, (d_d, d_s) if d_d else None)
    st.markdown(f"Attente accostage : **{calc.get('attente_accostage', '–')}** · "
                f"Shifts engagés : **{calc.get('shifts_engages', '–')}**")

    st.markdown("#### Totaux du time sheet :gray[(facultatif)]")
    c = st.columns(4)
    ts_veh = c[0].number_input("Véhicules", min_value=0, step=1, value=None, key=K + "tsveh")
    ts_sh = c[1].number_input("Shifting", min_value=0, step=1, value=None, key=K + "tssh")

    # --- Shifting : source et positions (avant le calcul)
    blocs_sh = _blocs_shift(fichiers)
    sh = _s("shifting_df")
    if blocs_sh and sh is not None and len(sh):
        choix = st.segmented_control("Source du shifting", ["Fiche shifting", "Feuille SHIFT du tableau"],
                                     default="Fiche shifting", key=K + "src_sh")
        _set("source_shift", "tableau" if choix == "Feuille SHIFT du tableau" else "fiche")
    else:
        _set("source_shift", "fiche" if sh is not None and len(sh) else "tableau")

    # --- calcul
    choix_bloc = _s("choix_bloc", {})
    try:
        res = _calcul(fichiers, armateur, choix_bloc, ts_veh, ts_sh)
    except Exception as ex:  # fichier illisible : message clair, pas de trace
        st.error(f"Lecture impossible : {ex}")
        return

    # --- Opérateurs (par bloc du tableau)
    st.markdown("#### Opérateurs")
    libs = [f"{noms[c_]} ({c_})" for c_ in codes]
    vers_code = dict(zip(libs, codes))
    nom_op = lambda c_: f"{noms[c_]} ({c_})" if c_ in noms else None
    det = res.detail
    blocs = det[det["page"].isin(["discharge", "loading"]) & det["code"].ne(263)] if len(det) else det
    if len(blocs):
        tab = blocs.groupby(["page", "bloc", "operateur"], sort=False)["vehicules"].sum().reset_index()
        tab["Bloc du tableau"] = tab["bloc"].where(tab["page"] == "discharge", "Chargement · " + tab["bloc"])
        tab["Opérateur"] = tab["operateur"].map(nom_op)
        tab = tab.rename(columns={"vehicules": "Véhicules"})
        vue = tab[["Bloc du tableau", "Véhicules", "Opérateur"]]
        ed = st.data_editor(vue, hide_index=True, width="stretch", key=K + "ed_ops",
                            disabled=["Bloc du tableau", "Véhicules"],
                            column_config={"Opérateur": st.column_config.SelectboxColumn(options=libs, required=True)})
        changes = {on.cle_client(tab["bloc"].iat[i]): (tab["bloc"].iat[i], vers_code[ed["Opérateur"].iat[i]])
                   for i in range(len(tab))
                   if ed["Opérateur"].iat[i] in vers_code and ed["Opérateur"].iat[i] != vue["Opérateur"].iat[i]}
        if changes:
            choix_bloc.update(changes)
            _set("choix_bloc", choix_bloc)
            st.session_state.pop(K + "ed_ops", None)   # évite de rejouer une modification sur une ligne déplacée
            st.rerun()
    with st.expander("Ajouter un opérateur"):
        c = st.columns([1, 2, 1])
        code_n = c[0].text_input("Code", key=K + "new_code")
        lib_n = c[1].text_input("Libellé", key=K + "new_lib")
        if c[2].button("Ajouter", key=K + "new_btn"):
            try:
                store.ajouter_operateur(code_n, lib_n, _auteur())
                st.rerun()
            except Exception as ex:
                st.error(f"Ajout impossible : {ex}")

    # --- Shifting : positions des blocs de la feuille SHIFT
    if blocs_sh and _s("source_shift") == "tableau":
        st.markdown("#### Shifting")
        positions = _s("positions", {})
        cpt = det[det["page"] == "shifting"].groupby("bloc")["vehicules"].sum() if len(det) else {}
        vue = pd.DataFrame({"Bloc de la feuille SHIFT": blocs_sh,
                            "Véhicules": [int(cpt.get(b_, 0)) if len(cpt) else 0 for b_ in blocs_sh],
                            "Position": [POS_FR.get(positions.get(b_) or on.position_par_defaut(b_)) for b_ in blocs_sh]})
        ed = st.data_editor(vue, hide_index=True, width="stretch", key=K + "ed_pos",
                            disabled=["Bloc de la feuille SHIFT", "Véhicules"],
                            column_config={"Position": st.column_config.SelectboxColumn(options=list(POS_FR.values()))})
        inv_pos = {v: k for k, v in POS_FR.items()}
        nouv = {blocs_sh[i]: inv_pos[ed["Position"].iat[i]] for i in range(len(vue))
                if ed["Position"].iat[i] in inv_pos and ed["Position"].iat[i] != vue["Position"].iat[i]}
        if nouv:
            positions.update(nouv)
            _set("positions", positions)
            st.session_state.pop(K + "ed_pos", None)
            st.rerun()

    # --- Fiche shifting (corrigeable à l'écran)
    if sh is not None and len(sh) and _s("source_shift") == "fiche":
        corr_sh = [c_ for c_ in res.controles if c_.cle.startswith("sh_") and c_.niveau == "corriger"]
        with st.expander("Fiche shifting", expanded=bool(corr_sh)):
            vue = sh.copy()
            vue["classe_saisie"] = vue["classe_saisie"].map(on.LIBELLE_CLASSE)
            vue["position"] = vue["position"].map(POS_FR)
            vue = vue.rename(columns={"chassis": "N° châssis", "marque": "Marque et modèle", "poids_t": "Poids (t)",
                                      "classe_saisie": "Classe", "position": "Position", "long": "Long (m)",
                                      "larg": "Larg (m)", "haut": "Haut (m)"})
            ed = st.data_editor(vue.drop(columns=["ligne"]), num_rows="dynamic", hide_index=True,
                                width="stretch", key=K + "ed_sh",
                                column_config={"Classe": st.column_config.SelectboxColumn(options=list(on.LIBELLE_CLASSE.values())),
                                               "Position": st.column_config.SelectboxColumn(options=list(POS_FR.values()))})
            if st.button("Appliquer les corrections", key=K + "sh_ok"):
                inv_cl = {v: k for k, v in on.LIBELLE_CLASSE.items()}
                inv_pos = {v: k for k, v in POS_FR.items()}
                nv = ed.rename(columns={"N° châssis": "chassis", "Marque et modèle": "marque", "Poids (t)": "poids_t",
                                        "Classe": "classe_saisie", "Position": "position", "Long (m)": "long",
                                        "Larg (m)": "larg", "Haut (m)": "haut"})
                nv["classe_saisie"] = nv["classe_saisie"].map(inv_cl)
                nv["position"] = nv["position"].map(inv_pos)
                nv.insert(0, "ligne", range(1, len(nv) + 1))
                _set("shifting_df", nv.reset_index(drop=True))
                st.rerun()

    # --- Contrôles
    ctr = ctr_ent + res.controles
    if not navire or not voyage:
        ctr.append(on.Controle("corriger", "Navire et voyage à renseigner", "", "navire"))
    corriger = [c_ for c_ in ctr if c_.niveau == "corriger"]
    verifier = [c_ for c_ in ctr if c_.niveau == "verifier"]
    ok = [c_ for c_ in ctr if c_.niveau == "ok"]
    if corriger:
        st.markdown(f"#### À corriger ({len(corriger)})")
        for c_ in corriger:
            st.error(f"**{c_.titre}**" + (f" — {c_.detail}" if c_.detail else ""), icon=":material/edit:")
    if verifier:
        st.markdown(f"#### À vérifier ({len(verifier)})")
        for c_ in verifier:
            st.warning(f"**{c_.titre}**" + (f" — {c_.detail}" if c_.detail else ""), icon=":material/visibility:")
    with st.expander(f"{len(ok)} contrôle(s) réussi(s)"):
        for c_ in ok:
            st.markdown(f"- {c_.titre}" + (f" : {c_.detail}" if c_.detail else ""))

    c = st.columns([1, 1, 4])
    if c[0].button("Retour"):
        _set("etape", 1)
        st.rerun()
    if c[1].button("Continuer", type="primary", disabled=bool(corriger)):
        try:
            if choix_bloc:
                store.enregistrer_regles("bloc", choix_bloc, _auteur())
        except Exception:
            st.warning("Les choix d'opérateurs n'ont pas pu être mémorisés (base indisponible).")
        _set("resultat", res)
        _set("armateur_code", armateur)
        _set("entete", {"Navire": navire, "Voyage": voyage, "Type": type_nav,
                        "Armateur": noms.get(armateur, armateur), "N° dossier": n_dossier,
                        "ETA rade": vals["eta"], "Accostage": vals["acc"], "Début des opérations": vals["deb"],
                        "Fin des opérations": vals["fin"], "Appareillage": vals["app"],
                        "Attente accostage": calc.get("attente_accostage"), "Nombre d'équipes": nb_eq,
                        "Équipes ayant attendu": eq_att, "Premier shift": f"{p_d:%d/%m/%Y} {p_s}",
                        "Dernier shift": f"{d_d:%d/%m/%Y} {d_s}", "Shifts engagés": calc.get("shifts_engages")})
        _set("nb_alertes", len(verifier))
        _set("etape", 3)
        st.rerun()


# ---------------------------------------------------------------- étape 3
def _fmt(x) -> str:
    if x is None:
        return ""
    if float(x).is_integer():
        return f"{int(x)}"
    return f"{x:.3f}".replace(".", ",")


def _tableau(res, page, noms) -> pd.DataFrame:
    arm = _s("armateur_code", "")
    ops = sorted({o for (p, _, o) in res.cases if p == page}, key=lambda o: (o != arm, noms.get(o, o)))
    codes = sorted({c for (p, c, _) in res.cases if p == page}, key=lambda c: (c == 263, c))
    lignes = []
    for c in codes:
        lig = {"Rubrique": LIB_FR.get(c, on.RUBRIQUES[(page, c)][0])}
        for o in ops:
            v = res.cases.get((page, c, o))
            n = noms.get(o, o)
            lig[f"{n} · unités"] = _fmt(v["unites"]) if v else ""   # cargo général : nombre de colis
            lig[f"{n} · tonnes"] = _fmt(v["tonnes"]) if v else ""
        lignes.append(lig)
    return pd.DataFrame(lignes)


def _sauver_historique():
    res, ent = _s("resultat"), _s("entete", {})
    try:
        store.enregistrer_historique(ent.get("Navire", ""), ent.get("Voyage", ""), ent.get("N° dossier", ""),
                                     on.totaux(res), _s("nb_alertes", 0), _auteur())
        _set("histo_ok", True)
    except Exception:
        _set("histo_ok", False)


def _telecharger():
    res, ent = _s("resultat"), _s("entete", {})
    noms = _ops()
    st.subheader("Vérifiez puis téléchargez")
    pages = [p for p in mod.PAGES if any(k[0] == p for k in res.cases)]
    if not pages:
        st.info("Aucune donnée à reporter.")
    else:
        page = st.segmented_control("Page", pages, format_func=mod.PAGES.get, default=pages[0], key=K + "page",
                                    label_visibility="collapsed") or pages[0]
        df = _tableau(res, page, noms)
        st.dataframe(df, hide_index=True, width="stretch")
        st.caption(f"Total : {res.total(page)} unités")
        with st.expander("Voir le détail d'une ligne"):
            choix = st.selectbox("Rubrique", df["Rubrique"].tolist(), key=K + "drill")
            code = next(c for c in {c for (p, c, _) in res.cases if p == page}
                        if LIB_FR.get(c, on.RUBRIQUES[(page, c)][0]) == choix)
            d = res.detail[(res.detail["page"] == page) & (res.detail["code"] == code)].dropna(axis=1, how="all")
            st.dataframe(d.drop(columns=["page", "code"]), hide_index=True, width="stretch")
    noms_op = {c: n for c, n in noms.items()}
    c = st.columns([2, 2, 3])
    nom = f"Operations_{ent.get('Navire', '')}_{ent.get('Voyage', '')}".replace(" ", "_")
    ops_pdf = sorted({o for (_, _, o) in res.cases}, key=lambda o: (o != _s("armateur_code", ""), noms.get(o, o)))
    try:
        c[0].download_button("Télécharger le PDF", pdfmod.pdf_dc_gr_117(ent, res.cases, ops_pdf, noms_op),
                             file_name=f"{nom}_DC_GR-117.pdf", type="primary", on_click=_sauver_historique,
                             icon=":material/picture_as_pdf:")
    except ValueError as ex:          # plus de 4 opérateurs : le gabarit n'a que 4 colonnes
        c[0].error(str(ex))
    c[1].download_button("Télécharger le détail Excel", mod.detail_xlsx(res, ent, noms_op),
                         file_name=f"{nom}_detail.xlsx", on_click=_sauver_historique, icon=":material/download:")
    if _s("histo_ok") is False:
        st.warning("Escale non enregistrée dans l'historique (base indisponible).")
    elif _s("histo_ok"):
        st.caption("Escale enregistrée dans l'historique.")
    c = st.columns([1, 2, 4])
    if c[0].button("Retour"):
        _set("etape", 2)
        st.rerun()
    if c[1].button("Nouveau formulaire"):
        _reinitialiser()
        st.rerun()


# ---------------------------------------------------------------- historique
def _historique():
    rows = store.historique()
    if not rows:
        st.info("Aucun formulaire enregistré.")
        return
    df = pd.DataFrame(rows)
    q = st.text_input("Navire", placeholder="Rechercher", key=K + "h_q")
    if q:
        df = df[df["navire"].str.contains(q, case=False, na=False)]
    df["horodatage"] = pd.to_datetime(df["horodatage"]).dt.tz_convert("Africa/Abidjan").dt.strftime("%d/%m/%Y %H:%M")
    df = df.rename(columns={"horodatage": "Date", "navire": "Navire", "voyage": "Voyage", "n_dossier": "Dossier",
                            "debarques": "Débarqués", "tonnes_debarques": "Tonnes", "gc_tonnes": "Cargo général (t)",
                            "charges": "Chargés", "shifting": "Shifting", "alertes": "Points vérifiés",
                            "auteur": "Agent"})
    st.dataframe(df[["Date", "Navire", "Voyage", "Dossier", "Débarqués", "Chargés", "Shifting", "Agent"]],
                 hide_index=True, width="stretch")
