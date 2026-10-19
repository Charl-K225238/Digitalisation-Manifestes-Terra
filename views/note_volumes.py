"""
Page Note volumes mensuels — « volumes des N escales traitées sur M navires
prévus » (véhicules et conteneurs), générée à partir du fichier situation
navires et des manifestes. Maquette validée le 19/10/2026 (mode hybride).
Règles métier : voir note_volumes.py.
"""
import pathlib
import sys
from urllib.parse import quote

import pandas as pd
import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import note_volumes as nv
import note_volumes_store as store
import situation_parser as sp
from security_utils import filter_uploads, safe_error
from ui_helpers import (help_expander, kpi_card, kpi_row, reset_page_button, section_header, upl_key)


from ui_helpers import current_access_role as _car
if _car() not in ("analyste", "direction"):
    st.error("Page réservée aux analystes et à la direction.")
    st.stop()

st.title("Note volumes mensuels")
st.caption("Fichier situation navires + manifestes → volumes des escales traitées → note prête à envoyer.")

with help_expander(":material/info: Comment utiliser cette page ?"):
    st.markdown(
        """
1. **Déposez le fichier situation navires** du jour (.xlsm). Déposez-le à chaque mise à jour :
   l'app garde le détail de chaque navire terminé (export, Observation), qui disparaît ensuite du fichier.
2. **Les manifestes sont lus automatiquement dans les Archives** (manifestes déjà traités dans Pré-Masque).
   Le dépôt manuel ne sert qu'en complément, pour un manifeste jamais traité dans l'app.
3. **Choisissez le mois**, vérifiez les escales et les volumes (chaque chiffre est modifiable),
   puis copiez ou téléchargez la note.

Règles : seuls les navires **terminés** comptent dans les volumes ; l'en-tête compte les navires prévus du mois
hors navires à 0 mouvement ; volumes = réalisé du fichier situation, complété par les manifestes ;
TEU = 20' et 40' (MAFI et bolsters hors TEU) ; « plus de 50 m3 » = volume unitaire **strictement** supérieur à 50 m3 ;
empilés / attelés hors total ; vides export lus dans l'Observation.
        """
    )

# ── 1. Fichiers ──────────────────────────────────────────────────────────────
section_header("1 · Fichiers", "Chaque fichier est lu séparément : une erreur ne bloque pas les autres")
c1, c2 = st.columns(2)
sit_files = filter_uploads(c1.file_uploader(
    "Fichier situation navires (.xlsm)", type=["xlsm", "xlsx", "xls"], accept_multiple_files=True,
    key=upl_key("nv_sit"), help="Classeur tenu par les agents (ex. 19_OCTOBRE_2026.xlsm)."))
man_files = filter_uploads(c2.file_uploader(
    "Manifestes hors Archives (facultatif)", type=["pdf", "xls", "xlsx"], accept_multiple_files=True,
    key=upl_key("nv_man"), help="Grimaldi PDF (un par port de chargement), chinois XLS/XLSX, MOL / NYK PDF."))
reset_page_button(["nv_sit", "nv_man"], ("nv_msgs",), key="nv_reset", state_prefixes=("nv_ed_",),
                  has_content=bool(sit_files or man_files or st.session_state.get("nv_msgs")))

if st.button("Lire les fichiers", type="primary", icon=":material/play_arrow:",
             disabled=not (sit_files or man_files), key="nv_go"):
    msgs, total = [], len(sit_files) + len(man_files)
    bar = st.progress(0.0, text="Démarrage…")
    done = 0
    for f in sorted(sit_files, key=lambda x: x.name):
        bar.progress(done / total, text=f"{f.name}…")
        try:
            sit = sp.read_situation(f.getvalue())
            n, ok_db = store.save_situation(sit["navires"], f.name)
            store.save_last(sit, f.name)
            msgs.append(("ok", f"{f.name} : {len(sit['navires'])} navires lus, {n} mémorisés"
                               + ("" if ok_db else " (base indisponible : gardés pour cette session)")))
        except Exception as e:
            safe_error("note_volumes: situation", e, f"{f.name} : fichier situation illisible ({e}).")
            msgs.append(("ko", f"{f.name} : non lu"))
        done += 1
    par_escale = {}
    for f in man_files:
        def _cb(p, t, _d=done, _n=f.name):
            bar.progress(min((_d + (p / t if t else 1)) / total, 1.0), text=f"{_n} — page {p}/{t}")
        try:
            r = nv.lire_manifeste(f.name, f.getvalue(), progress_cb=_cb)
            e = par_escale.setdefault(r["escale"], {"volumes": None, "fichiers": [], "conteneurs": r["conteneurs"],
                                                    "format": r["format"], "navire_brut": r["navire_brut"]})
            e["volumes"] = nv.add_volumes(e["volumes"], r["volumes"])
            e["fichiers"].append(f.name)
        except Exception as e:
            safe_error("note_volumes: manifeste", e, f"{f.name} : {e}")
            msgs.append(("ko", f"{f.name} : non lu"))
        done += 1
    for esc, e in par_escale.items():
        ok_db = store.save_manifeste(esc, e["volumes"], e["fichiers"], e["conteneurs"], e["format"], e["navire_brut"])
        msgs.append(("ok", f"{e['navire_brut']} : {len(e['fichiers'])} manifeste(s), "
                           f"{e['volumes'].get('veh_total', 0)} véhicules"
                           + ("" if ok_db else " (base indisponible : gardé pour cette session)")))
    bar.empty()
    st.session_state["nv_msgs"] = msgs

for kind, m in st.session_state.get("nv_msgs", []):
    (st.success if kind == "ok" else st.warning)(m)

last = store.load_last()
situations, db_ok = store.load_situations()
manifestes, _ = store.load_manifestes()
if not db_ok:
    st.warning("Base de données indisponible : les fichiers lus ne sont gardés que pour cette session.")
if last is None:
    st.info(":material/upload: Déposez au moins un fichier situation navires pour construire la note.")
    st.stop()
st.caption(f"Fichier situation de référence : **{last['fichier']}**")

# ── 2. Escales du mois ───────────────────────────────────────────────────────
st.divider()
annee_def, mois_def = nv.now_month()
mois_dispo = sorted(last["cumul"]) or list(range(1, 13))
cm, ca = st.columns([2, 1])
mois = cm.selectbox("Mois", mois_dispo, index=mois_dispo.index(mois_def) if mois_def in mois_dispo else len(mois_dispo) - 1,
                    format_func=lambda m: nv.MOIS_FR[m - 1].capitalize(), key="nv_mois")
annee = ca.number_input("Année", min_value=2024, max_value=2100, value=annee_def, step=1, key="nv_annee")

esc = nv.escales_du_mois(last, int(annee), int(mois))
section_header("2 · Escales du mois", "Cochez / décochez pour corriger l'en-tête ou les volumes",
               source="Fichier situation : onglet CUMUL du mois, sections OPERATING / EXPECTED")
if esc.empty:
    st.info("Aucun navire trouvé pour ce mois dans le fichier situation.")
    st.stop()

# Manifestes des Archives : lus automatiquement (une seule fois par jeu de
# fichiers archivés), puis mémorisés comme les manifestes déposés.
cr1, cr2 = st.columns([3, 1])
force = cr2.button("Relire les archives", icon=":material/refresh:", key="nv_force_arch",
                   help="Relit tous les manifestes archivés des escales du mois (après une correction).")
_bar = st.empty()
try:
    _err = store.charger_archives(
        esc["escale"].tolist(), nv.lire_manifeste, force=force,
        progress=lambda f, t: _bar.progress(min(f, 1.0), text=t))
except Exception as e:
    _err = {}
    safe_error("note_volumes: archives", e, "Archives indisponibles : seuls les manifestes déposés sont utilisés.")
_bar.empty()
for _e, _m in _err.items():
    st.warning(f"Archives · {_e.replace('|', ' ')} — {_m}")
manifestes, _ = store.load_manifestes()
_orig = {e: (manifestes.get(nv.match_manifeste(e, manifestes) or "", {}).get("origine") or "Dépôt")
         for e in esc["escale"] if nv.match_manifeste(e, manifestes)}
cr1.caption(f"Manifestes trouvés : {sum(1 for o in _orig.values() if o == 'Archives')} escale(s) depuis les Archives, "
            f"{sum(1 for o in _orig.values() if o != 'Archives')} déposée(s) à la main")

vue = pd.DataFrame({
    "En-tête": esc["compte_entete"], "Volumes": esc["compte_volumes"],
    "Navire": esc["navire_brut"], "Type": esc["type"], "Ligne": esc["ligne"],
    "Date": esc["date"].map(nv.date_label), "Statut": esc["statut"],
    "Mouvements prévus": pd.to_numeric(esc["total_moves"], errors="coerce").astype("Int64"),
    "Manifeste": [_orig.get(e, "—") for e in esc["escale"]],
    "Détail situation": [("Oui" if (situations.get(e) or {}).get("statut") == "Terminé" else "—") for e in esc["escale"]],
})
ed = st.data_editor(
    vue, hide_index=True, width="stretch", key=f"nv_ed_esc_{annee}_{mois}",
    disabled=["Navire", "Date", "Statut", "Mouvements prévus", "Manifeste", "Détail situation"],
    column_config={
        "En-tête": st.column_config.CheckboxColumn(help="Compté dans « N navires prévus »"),
        "Volumes": st.column_config.CheckboxColumn(help="Compté dans les volumes (navires terminés)"),
        "Type": st.column_config.SelectboxColumn(options=sorted(set(esc["type"]) | {"CARCAR", "LOLO", "CONRO"})),
        "Ligne": st.column_config.SelectboxColumn(options=["", "ATL", "MED"]),
    })
esc = esc.assign(compte_entete=ed["En-tête"].values, compte_volumes=ed["Volumes"].values,
                 type=ed["Type"].values, ligne=ed["Ligne"].fillna("").values)

# ── 3. Volumes ───────────────────────────────────────────────────────────────
st.divider()
section_header("3 · Volumes des escales traitées", "Chiffre vide = à compléter ; toute valeur est modifiable",
               source="Fichier situation, navire terminé (réalisé) en priorité ; manifeste pour ce qui manque "
                      "(hinterland, transbo, navire non vu terminé)")
traitees = esc[esc["compte_volumes"]]
rows, src_rows, alertes = [], [], []
for r in traitees.itertuples():
    vals, srcs = nv.volumes_escale(r.escale, manifestes, situations)
    rows.append({"Navire": r.navire_brut, **{nv.LABELS[k]: vals.get(k) for k in nv.VEH + nv.TC}})
    src_rows.append({"Navire": r.navire_brut, **{nv.LABELS[k]: srcs.get(k, "À compléter") for k in nv.VEH + nv.TC}})
    for c in nv.controles(r.escale, manifestes, situations):
        alertes.append(f"**{r.navire_brut}** · {c}")

if not rows:
    st.info("Aucune escale terminée cochée pour ce mois.")
    detail = pd.DataFrame(columns=["compte_volumes"])
else:
    tab = pd.DataFrame(rows)
    for col in tab.columns[1:]:
        tab[col] = pd.to_numeric(tab[col], errors="coerce").astype("Int64")
    tab_ed = st.data_editor(tab, hide_index=True, width="stretch", key=f"nv_ed_vol_{annee}_{mois}",
                            disabled=["Navire"],
                            column_config={c: st.column_config.NumberColumn(min_value=0, step=1)
                                           for c in tab.columns[1:]})
    with st.expander("Source de chaque chiffre"):
        st.dataframe(pd.DataFrame(src_rows), hide_index=True, width="stretch")
    detail = pd.DataFrame({k: tab_ed[nv.LABELS[k]] for k in nv.VEH + nv.TC})
    detail["compte_volumes"] = True

tot = nv.totaux(detail)
manquants = [nv.LABELS[k] for k in nv.VEH + nv.TC if tot.get(k) is None]
pleins = None if tot.get("tc_pleins_imp") is None or tot.get("tc_pleins_exp") is None \
    else tot["tc_pleins_imp"] + tot["tc_pleins_exp"]
kpi_row([kpi_card("Véhicules", tot.get("veh_total"), icon_name="car"),
         kpi_card("Plus de 50 m3", tot.get("veh_gt50"), icon_name="car", tone=1),
         kpi_card("Neufs", tot.get("veh_neufs"), icon_name="tag"),
         kpi_card("Hinterland", tot.get("veh_hinterland"), icon_name="globe", tone=1),
         kpi_card("TEU pleins", pleins, icon_name="container", tone=2),
         kpi_card("TEU vides", tot.get("tc_vides"), icon_name="container")])
if manquants:
    st.warning("À compléter dans le tableau : " + ", ".join(manquants)
               + ". La note affiche « [À COMPLÉTER] » à la place.")
if alertes:
    with st.expander(f"Contrôles de cohérence ({len(alertes)}) — le fichier situation (réalisé) fait foi",
                     expanded=True):
        for a in alertes:
            st.markdown(f"- {a}")

# ── 4. Note ──────────────────────────────────────────────────────────────────
st.divider()
section_header("4 · Note générée", "Texte modifiable avant envoi")
texte = nv.build_note(esc, tot, int(annee), int(mois))
final = st.text_area("Note", texte, height=430, key=f"nv_txt_{hash(texte)}", label_visibility="collapsed")
b1, b2 = st.columns(2)
b1.download_button("Télécharger (.txt)", final.encode("utf-8"), icon=":material/download:",
                   file_name=f"note_volumes_{nv.MOIS_FR[int(mois) - 1]}_{int(annee)}.txt", mime="text/plain")
sujet = f"Volumes escales {nv.MOIS_FR[int(mois) - 1].capitalize()} {int(annee)}"
b2.link_button("Ouvrir dans Outlook", f"mailto:?subject={quote(sujet)}&body={quote(final)}", icon=":material/mail:")
st.caption("Pour copier : icône en haut à droite du bloc ci-dessous.")
st.code(final, language=None)
