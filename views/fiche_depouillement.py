"""
Page Fiche de dépouillement — tous les types de manifestes (format reconnu
automatiquement, voir fiche_sources).

Compte les unités par catégorie (USED / NEW / 20' / 40' / >50m3 / BOLSTER /
DIVERS) et exporte la fiche en Excel (2 onglets : Fiche + Détail).
"""
import hashlib
import pathlib
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fiche_depouillement import METHODE_CATEGORIES, METHODE_NOTES
from fiche_sources import controles_lot, read_manifest
from mol_manifest_parser import ManifestFormatError, ManifestReadError
from ui_fiche import render_fiche_depouillement
from ui_helpers import help_expander, upl_key, reset_page_button
from security_utils import filter_uploads, safe_error

st.title("Fiche de dépouillement")
st.caption(
    "Chargez un ou plusieurs manifestes, tous types confondus → format reconnu "
    "automatiquement → comptage par catégorie → export Excel."
)

with help_expander(":material/info: Comment utiliser cette page ?"):
    st.markdown(
        """
1. **Chargez** un ou plusieurs manifestes, puis cliquez sur **▶ Générer la fiche**.
   Formats reconnus : Grimaldi, MOL / NYK / K LINE, EUKOR, navire à grue (Excel),
   Cargo Manifest scanné et Hyundai Glovis scanné.
2. **Relisez** les compteurs USED / NEW / 20' / 40' / >50m3 / BOLSTER / DIVERS
   et le tableau par sous-type. Les unités de fiabilité **LOW** sont à vérifier.
3. **Filtrez le détail** des unités pour contrôler une catégorie.
4. **Téléchargez** la fiche Excel (onglets *Fiche* et *Détail*).

Les règles de comptage sont détaillées dans *Comment le décompte est fait*, sur cette
page et dans l'onglet *Méthode* de la fiche Excel. Les manifestes scannés sont plus
lents (lecture par OCR).
        """
    )

with st.expander(":material/rule: Comment le décompte est fait", expanded=False):
    st.dataframe(pd.DataFrame(METHODE_CATEGORIES, columns=["Catégorie", "Grimaldi", "Autres manifestes"]),
                 hide_index=True, width="stretch")
    st.markdown("\n".join(f"- {n}" for n in METHODE_NOTES))

st.divider()

files = st.file_uploader("Manifestes (PDF, Excel)", type=["pdf", "xls", "xlsx"], accept_multiple_files=True,
                         key=upl_key("fiche_upload"))
files = filter_uploads(files)
reset_page_button(["fiche_upload"], ("fiche_units", "fiche_formats", "fiche_controles"), key="reset_fiche",
                  has_content=bool(files) or st.session_state.get("fiche_units") is not None)
if st.button("▶ Générer la fiche", type="primary", disabled=not files, key="fiche_go"):
    units, formats, lus, vus, bar = [], [], [], {}, st.progress(0.0, text="Démarrage…")
    for i, f in enumerate(files):
        _empreinte = hashlib.sha256(f.getvalue()).hexdigest()
        if _empreinte in vus:
            st.warning(f"{f.name} : même contenu que {vus[_empreinte]}, compté une seule fois.")
            continue
        vus[_empreinte] = f.name
        try:
            def _cb(pno, total, _i=i, _n=f.name):
                frac = min((_i + (pno / total if total else 1.0)) / len(files), 1.0)
                bar.progress(frac, text=f"{_n} — page {pno}/{total}")
            bar.progress(i / len(files), text=f"{f.name} — lecture…")
            fmt, u, warns = read_manifest(f.name, f.getvalue(), progress_cb=_cb)
            units.extend(u)
            lus.append((f.name, u))
            formats.append((f.name, fmt, len(u), warns))
        except (ManifestReadError, ManifestFormatError, ValueError) as e:
            st.error(f"{f.name} : {e}")     # message pensé pour l'agent
        except Exception as e:
            safe_error("fiche: parse", e, f"Erreur sur {f.name} : fichier illisible ou format non reconnu.")
    bar.empty()
    st.session_state["fiche_units"] = units
    st.session_state["fiche_formats"] = formats
    st.session_state["fiche_controles"] = controles_lot(lus)

units = st.session_state.get("fiche_units")
if units:
    for _nom, _fmt, _n, _warns in st.session_state.get("fiche_formats", []):
        (st.success if _n else st.warning)(f"{_nom} : format {_fmt}, {_n} unités.")
        for _w in _warns:
            st.warning(_w)
    for _w in st.session_state.get("fiche_controles", []):
        st.warning(_w)
    render_fiche_depouillement(units)
elif units is not None:
    st.warning("Aucune donnée extraite des fichiers fournis.")
else:
    st.info(":material/upload: Chargez un ou plusieurs manifestes PDF puis cliquez sur *Générer la fiche*.")
