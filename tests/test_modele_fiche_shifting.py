"""Modèle de fiche shifting : le fichier s'ouvre et contient les colonnes attendues."""
import io
import os
import sys

from openpyxl import load_workbook

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import modele_fiche_shifting as mod  # noqa: E402


def test_modele_fiche_shifting():
    ws = load_workbook(io.BytesIO(mod.modele_shifting_xlsx("NAVIRE TEST", "V000"))).active
    entetes = [c.value for c in ws[mod.LIGNE_ENTETE + 1]][:len(mod.COLONNES_SHIFTING)]
    assert [e.rstrip(" *") for e in entetes] == mod.COLONNES_SHIFTING
    assert ws["B2"].value == "NAVIRE TEST" and ws.protection.sheet
    assert ws.cell(row=mod.LIGNE_ENTETE + 1 + mod.NB_LIGNES, column=1).value == mod.NB_LIGNES


if __name__ == "__main__":
    test_modele_fiche_shifting()
    print("OK test_modele_fiche_shifting")
