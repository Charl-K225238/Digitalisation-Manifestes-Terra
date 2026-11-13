"""Tests du module operations_navire sur données FICTIVES (aucune donnée de production).

Lancer : python -m pytest tests/test_operations_navire.py   (ou python tests/test_operations_navire.py)
"""
import io
import os
import sys
from datetime import datetime

from openpyxl import Workbook

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import operations_navire as on  # noqa: E402


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(list(r))
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def _discharging():
    rows = [["DONNEES IMPORT"], [], ["Navire:", "NAVIRE TEST"], ["Voyage:", "V000"],
            ["Consignataire:", "AGENT"], ["Date arrivée:", "01/01/2026"], ["Acconier:", "TERRA"],
            ["N°Ordre", "Ref BL", "PORT", "Marque", "Type", "Genre (Modèle)", "Etat", "N° chassis",
             "POIDS", "CUBAGES", "CYCLE", "DESTINATION"]]
    vehicules = [  # (bl, chassis, poids, cubage)
        ("BL1", "CH001", 1500, 14.9),    # < 15, proche limite
        ("BL1", "CH002", 1499, 12.0),    # < 15
        ("BL2", "CH003", 2000, 15.0),    # 15 pile -> 15-50
        ("BL2", "CH004", 3001, 49.99),   # 15-50
        ("BL3", "CH005", 20000, 50.0),   # 50 pile -> >= 50
    ]
    for i, (bl, ch, kg, m3) in enumerate(vehicules, 1):
        rows.append([i, bl, "PORT A", "MARQUE", "", "MODELE", "NEUF", ch, kg, m3, "IMPORT", "ABIDJAN"])
    return _xlsx(rows), "discharging.xlsx"


def _tetrax():
    rows = [["N° DE COMPTE D'ESCALE", "NAVIRE", "ARMATEUR", "N° CHASSIS OU NUM SERIE", "NOM CLIENT/ IMPORTATEUR"]]
    for ch, cl in [("CH001", "CLIENT UN SARL"), ("CH002", "CLIENT UN SARL"), ("CH003", "CLIENT DEUX"),
                   ("CH004", "CLIENT DEUX"), ("CH005", "CLIENT UN SARL")]:
        rows.append([1234567, "NAVIRE TEST", "ARMATEUR A", ch, cl])
    return _xlsx(rows), "tetrax.xlsx"


def _gc():
    rows = [[], ["N° BL", "MARQUE", "Nature Marchandise", "Tonnage", "Provenance", "Destination",
                 "Date réception", "POIDS & VOLUME"],
            ["BL9", "X", "BUCKET", "", "PORT A", "ABIDJAN", "", "01 COLIS = 8.820 KGS   21,750 m3"],
            ["BL8", "", "PALLET", "", "", "ABIDJAN", "", "08 COLIS = 1.460 KGS   0,000 m3"],
            ["", "", "", "", "", "", "", "TOTAL:  09 COLIS = 10,280 KG  0,000 m3"]]
    return _xlsx(rows), "gc.xlsx"


def _shifting():
    rows = [["Navire", "NAVIRE TEST"], on.COLONNES_SHIFTING,
            [1, "ENGIN", "S001", 46.38, "50 m³ et plus", "Reste à bord", 11.75, 3.51, 4.12],
            [2, "ENGIN", "S002", 5.6, "Moins de 15 m³", "Débarqué puis rembarqué", 11.5, 2.0, 2.3],  # dims -> >=50
            [3, "VOITURE", "S003", 1.35, "Moins de 15 m³", "Débarqué puis rembarqué"],
            [4, "VOITURE", "S004", None, "Moins de 15 m³", "Débarqué puis rembarqué"],             # poids manquant
            [5, "VOITURE", "S003", 1.2, "Moins de 15 m³", "Débarqué puis rembarqué"]]              # doublon
    return _xlsx(rows), "shifting.xlsx"


def _loading():
    entete = ["Ordre", "Navire", "Validation", "Conteneur", "ISO", "Type", "Poids en Kg",
              "Exploitant", "V/P", "E/T"]
    rows = [[], entete,
            [1, "N", "Embarqué", "TC01", 20, "22G1", 2200, "ARMT B", "V", "E"],
            [2, "N", "Embarqué", "TC02", 40, "45G1", 18700, "ARMT B", "P", "E"],
            [3, "N", "Embarqué", "TC03", 40, "45R1", 25000, "ARMT B", "P", "T"],
            [4, "N", "Non Embarqué", "TC04", 20, "22G1", 2200, "ARMT B", "V", "E"],
            [5, "N", "Embarqué", "TC05", "BOL", 2960, 2400, "ARMT B", "V", "E"],
            [6, "N", "Embarqué", "TC06", "MAFI", 9900, 6000, "ARMT B", "V", "E"]]
    return _xlsx(rows), "loading.xlsx"


def _calc(**kw):
    e = on.Entree(armateur="Z00", **kw)
    return on.calculer(e)


def test_classes_et_bornes():
    assert on.classe_volume(14.999) == "<15"
    assert on.classe_volume(15) == "15-50"
    assert on.classe_volume(49.99) == "15-50"
    assert on.classe_volume(50) == ">=50"
    assert on.classe_volume(None) is None and on.classe_volume(0) is None


def test_tonnes_superieures():
    assert on.tonnes_sup(178940) == 179
    assert on.tonnes_sup(8840) == 9
    assert on.tonnes_sup(9000) == 9      # pile : pas d'arrondi
    assert on.tonnes_sup(0) == 0


def test_discharge_operateurs_et_tonnage():
    r = _calc(discharging=_discharging(), masque_tetrax=_tetrax(),
              regles_client={on.cle_client("CLIENT DEUX"): "Z01"})
    c = r.cases
    assert c[("discharge", 222, "Z00")]["unites"] == 2 and c[("discharge", 222, "Z00")]["tonnes"] == 3
    assert c[("discharge", 223, "Z01")]["unites"] == 2 and c[("discharge", 223, "Z01")]["tonnes"] == 6
    assert c[("discharge", 224, "Z00")]["unites"] == 1 and c[("discharge", 224, "Z00")]["tonnes"] == 20
    assert r.meta["n_dossier"] == "1234567"
    assert r.total("discharge") == 5
    assert any(x.cle == "dis_seuils" for x in r.controles)


def test_cle_client_tolerante():
    assert on.cle_client("Client Un SARL") == on.cle_client("CLIENT UN")
    assert on.cle_client("TRACTAFRIC MOTORS COTE D'IVOIRE") == on.cle_client("TRACTAFRIC MOTORS COTE DIVOIRE")


def test_general_cargo_lignes_font_foi():
    r = _calc(general_cargo=_gc())
    v = r.cases[("discharge", 263, "Z00")]
    assert v["tonnes"] == 10.28 and v["unites"] == 9
    assert any(x.cle == "gc_total" for x in r.controles)   # total volume du fichier faux (0 au lieu de 21,75)


def test_shifting():
    r = _calc(shifting=_shifting(), ts_total_shifting=4)
    c = r.cases
    assert c[("shifting", 130, "Z00")] == {"unites": 1, "kg": 46380.0, "tonnes": 47}
    assert c[("shifting", 136, "Z00")]["unites"] == 1          # classe corrigée par L x l x H
    assert c[("shifting", 134, "Z00")]["unites"] == 2          # S003 x2 (doublon signalé), S004 exclu
    cles = {x.cle for x in r.controles}
    assert "sh_manque_4" in cles and "sh_doublons" in cles and "sh_classe_2" in cles
    assert "ts_shifting" not in cles                            # 4 = 4


def test_loading():
    r = _calc(loading=_loading(), exploitants={"ARMT B": "Z02"})
    c = r.cases
    assert c[("loading", 301, "Z02")]["unites"] == 1          # non embarqué exclu
    assert c[("loading", 306, "Z02")]["unites"] == 1
    assert c[("loading", 317, "Z02")]["unites"] == 1          # 40' reefer transbo
    assert c[("loading", 303, "Z02")]["unites"] == 1
    assert c[("loading", 318, "Z02")]["unites"] == 1
    assert any(x.cle == "ld_non_embarque" for x in r.controles)


def test_entete():
    d = lambda h, m=0, j=1: datetime(2026, 1, j, h, m)
    out, ctr = on.entete(d(11, 25), d(12, 42), d(15, 10), d(22, 30), d(0, 0, 2),
                         (d(0).date(), "Jour"), (d(0).date(), "Nuit"))
    assert out == {"attente_accostage": "1:17", "shifts_engages": 2} and not ctr
    _, ctr = on.entete(d(11), d(10), d(15), d(22), None, None, None)
    assert {"Accostage avant eta rade", "Appareillage manquant"} <= {x.titre for x in ctr}


def test_modele_shifting_aller_retour():
    from openpyxl import load_workbook
    import operations_navire_modele as mod
    data = mod.modele_shifting_xlsx("NAVIRE TEST", "V000")
    vide = on.lire_fiche_shifting(data, "modele.xlsx")
    assert len(vide) == 0                                   # lignes numérotées mais vides ignorées
    wb = load_workbook(io.BytesIO(data))
    ws = wb.active
    r = mod.LIGNE_ENTETE + 2
    for i, ligne in enumerate([["ENGIN", "S001", 46.38, "50 m³ et plus", "Reste à bord"],
                               ["VOITURE", "S002", 1.35, "Moins de 15 m³", "Débarqué puis rembarqué"]]):
        for c, v in enumerate(ligne, start=2):
            ws.cell(row=r + i, column=c, value=v)
    b = io.BytesIO()
    wb.save(b)
    res = _calc(shifting=(b.getvalue(), "fiche.xlsx"))
    assert res.cases[("shifting", 130, "Z00")]["unites"] == 1
    assert res.cases[("shifting", 134, "Z00")]["unites"] == 1
    assert not [x for x in res.controles if x.niveau == "corriger"]


def test_detection_des_fichiers():
    import operations_navire_modele as mod
    assert on.detecter_type(*_discharging()) == "discharging"
    assert on.detecter_type(*_tetrax()) == "masque_tetrax"
    assert on.detecter_type(*_gc()) == "general_cargo"
    assert on.detecter_type(*_loading()) == "loading"
    assert on.detecter_type(mod.modele_shifting_xlsx(), "m.xlsx") == "shifting"
    assert on.detecter_type(_xlsx([["rien", "a voir"]]), "x.xlsx") is None


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("OK", n)
