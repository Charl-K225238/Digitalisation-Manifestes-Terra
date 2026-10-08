"""
Page Fiche de dépouillement — à partir d'un manifeste Grimaldi (PBREPORT PDF).

Compte les unités par catégorie (USED / NEW / 20' / 40' / >50m3 / BOLSTER /
DIVERS) et exporte la fiche en Excel (2 onglets : Fiche + Détail).
"""
import pathlib
import sys

import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from manifest_parser import parse_manifest
from ui_fiche import render_fiche_depouillement
from ui_helpers import help_expander, upl_key, reset_page_button
from security_utils import filter_uploads, safe_error

st.title("Fiche de dépouillement")
st.caption(
    "Chargez un ou plusieurs manifestes PDF Grimaldi → comptage automatique par "
    "catégorie → vérification → export Excel."
)

with help_expander(":material/info: Comment utiliser cette page ?"):
    st.markdown(
        """
1. **Chargez** un ou plusieurs manifestes PDF Grimaldi, puis cliquez sur **▶ Générer la fiche**.
2. **Relisez** les compteurs USED / NEW / 20' / 40' / >50m3 / BOLSTER / DIVERS
   et le tableau par sous-type. Les unités de fiabilité **LOW** sont à vérifier.
3. **Filtrez le détail** des unités pour contrôler une catégorie.
4. **Téléchargez** la fiche Excel (onglets *Fiche* et *Détail*).

Le classement suit le libellé de catégorie du manifeste (pas le volume).
        """
    )

st.divider()

files = st.file_uploader("Manifestes PDF Grimaldi", type=["pdf"], accept_multiple_files=True,
                         key=upl_key("fiche_upload"))
files = filter_uploads(files)
reset_page_button(["fiche_upload"], ("fiche_records",), key="reset_fiche",
                  has_content=bool(files) or st.session_state.get("fiche_records") is not None)
if st.button("▶ Générer la fiche", type="primary", disabled=not files, key="fiche_go"):
    records, bar = [], st.progress(0.0, text="Démarrage…")
    for i, f in enumerate(files):
        try:
            def _cb(pno, total, _i=i, _n=f.name):
                frac = min((_i + (pno / total if total else 1.0)) / len(files), 1.0)
                bar.progress(frac, text=f"{_n} — page {pno}/{total}")
            records.extend(parse_manifest(f, f.name, progress_cb=_cb))
        except Exception as e:
            safe_error("fiche: parse", e, f"Erreur sur {f.name} : fichier illisible ou format non reconnu.")
    bar.empty()
    st.session_state["fiche_records"] = records

records = st.session_state.get("fiche_records")
if records:
    st.success(f"{len(records)} connaissements (B/L) extraits.")
    render_fiche_depouillement(records)
elif records is not None:
    st.warning("Aucune donnée extraite des fichiers fournis.")
else:
    st.info(":material/upload: Chargez un ou plusieurs manifestes PDF puis cliquez sur *Générer la fiche*.")
