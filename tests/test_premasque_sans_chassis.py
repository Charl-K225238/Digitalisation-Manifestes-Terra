"""Pré-masque Ipaki : véhicule sans châssis gardé (case vide + point rouge), rappel à compléter,
garde-fou modèle lu comme châssis, règle ETAT par l'année. Données fictives."""
import datetime
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import premasque_ipaki as P  # noqa: E402

AN = datetime.date.today().year


def _df(**k):
    base = {"NBRE": 1, "BL": "TEST001", "CATEGORIE": "Vehicule", "MARQUE": "ASHOK LEYLAND",
            "MODELE": "DTH DRILL", "ETAT": "Usager", "CHÂSSIS": "", "POIDS TETRAX (KG)": 40000,
            "VOLUME TETRAX": None, "POL TETRAX": "CHENNAI", "POD TETRAX": "ABIDJAN",
            "_PIECES_JOINTES": True}
    base.update(k)
    return pd.DataFrame([base, {**base, "NBRE": 2, "CATEGORIE": "Colis", "MODELE": "ACCESSORIES"}])


def test_vehicule_sans_chassis_garde():
    rows, pts = P.rows_from_premasque_df(_df())
    assert len(rows) == 1 and rows[0]["CHÂSSIS"] == ""
    assert any(p["niveau"] == P.ROUGE and p["colonne"] == "CHÂSSIS" and p["ligne"] == 1 for p in pts)


def test_rappel_a_completer():
    info = P.a_completer(_df())
    assert info["total"] == 1 and info["complets"] == 0 and info["pieces"] and info["foreuse"]
    assert info["lignes"][0]["Manque"] == "Châssis · Volume"
    assert not P.a_completer(_df(**{"CHÂSSIS": "MB1TEST0000000001", "VOLUME TETRAX": 110.0}))["lignes"]


def test_modele_lu_comme_chassis():
    rows, pts = P.build_rows([{"Chassis": "DX450LCA-7M", "BL_Numero": "T1", "Marque": "DOOSAN",
                               "Modele": "DX450LCA-7M CRAWLER EXCAVATOR"}])
    assert rows[0]["CHÂSSIS"] == "" and rows[0]["MODELE"].startswith("DX450LCA-7M")
    assert P.chassis_est_modele("N12750", "HD785-7") == ""          # n° de série d'engin : gardé


def test_etat_par_annee():
    v = {"Chassis": "LJ1TEST00000000A1", "BL_Numero": "T1", "Marque": "JAC", "Modele": "T9"}
    neuf, _ = P.build_rows([{**v, "Annee_Fabrication": AN}])
    usage, _ = P.build_rows([{**v, "Annee_Fabrication": AN, "Etat": "Usager"}])
    vieux, _ = P.build_rows([{**v, "Annee_Fabrication": AN - 3}])
    assert neuf[0]["ETAT"] == P.ETAT_NEUF and usage[0]["ETAT"] == P.ETAT_USAGE
    assert vieux[0]["ETAT"] == P.ETAT_USAGE
