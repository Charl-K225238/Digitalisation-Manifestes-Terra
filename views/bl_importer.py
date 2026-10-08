"""
Page BL Importer — génère le classeur d'import IPAKI « IMPORTER VEHICULE » à
partir d'un manifeste brut (Chinese RoRo, MOL ALIS, Grimaldi, Hyundai Glovis).
"""
import pathlib
import sys

import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ui_helpers import help_expander
from ui_bl_importer import render_bl_importer

st.title("BL Importer IPAKI")
st.caption(
    "Transforme un manifeste en classeur d'import IPAKI « IMPORTER VEHICULE » : "
    "une ligne par véhicule, déjà pré-remplie. Les agents n'ont plus qu'à vérifier "
    "et saisir Call Number et SlotFile."
)

with help_expander(":material/info: Comment utiliser cette page ?"):
    st.markdown(
        """
- **1 · Chargez** le manifeste du navire (PDF ou Excel). Le format est reconnu automatiquement.
- **2 · Vérifiez** le résumé et les points à contrôler (châssis manquants, état neuf/occasion
  non précisé, ports sans code UNLOCODE…).
- **3 · Téléchargez** le classeur `.xls`, ouvrez-le, saisissez **Call Number** et **SlotFile**,
  puis importez-le dans IPAKI.

**Pré-rempli depuis le manifeste** : N° B/L, châssis, nature (Import/Transbo), destination finale,
port de chargement (UNLOCODE), commodity, client, volume et poids, modèle, expéditeur.
Les colonnes noires du classeur sont des formules déjà calculées.
        """
    )

render_bl_importer("bli_page")
