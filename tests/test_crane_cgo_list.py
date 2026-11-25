"""Liste de cargaison « 卸港货单 » (LP/DP/BL/cargo name/PCS/WEIGHT t) : poids en tonnes,
1 ligne par engin, colis en plus des engins, 1 ligne par colis de marchandise diverse,
contrôle du total TTL. Données fictives."""
import io
import os
import sys

from openpyxl import Workbook

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import crane_manifest_parser as c  # noqa: E402
import premasque_ipaki as P  # noqa: E402


def _fichier(ttl_pcs=10):
    wb = Workbook()
    ws = wb.active
    ws.append(["CONTACT INFORMATION", None, None, "CARGO DETAIL", None, None, None, "TERM", "RT"])
    ws.append(["LP", "DP", "BL", "cargo name", "PCS", "WEIGHT", "VOLUME"])
    ws.append(["TIAN JIN(BH)", "ABIDJAN", "T001", "HOT ROLLED STEEL COILS\nN.W.: 40MT\nFREIGHT PREPAID", 4, 40, None, "LO", 40])
    ws.append(["TIAN JIN(BH)", "ABIDJAN", "T002", "Used excavator CAT320GC\nSerial Number:CAT00320TEST00001\n"
               "Engine No.: ABC12345", 1, 22, 50, "LO", 50])
    ws.append(["TIAN JIN(BH)", "ABIDJAN", "T003", "USED DUMP TRUCK\nCARGO IN TRANSIT TO MALI", 2, 30, 120, "LO", 120])
    ws.append(["TIAN JIN(BH)", "ABIDJAN", "T004", "1 UNIT ZOOMLION CRAWLER CRANE WITH ACCESSORIES\nMODEL:ZCC600V-1\n"
               "YEAR:2026", 3, 50, 200, "LO", 200])
    ws.append([None, None, None, "TTL ", ttl_pcs, 142, 370, None, 410])
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_lecture():
    df = c.parse_crane_manifest(_fichier(), "ABIDJAN_CGO_LIST.xlsx")
    assert len(df) == 10                                            # 1 ligne par PCS
    assert df["POIDS TETRAX (KG)"].replace("", 0).sum() == 142000   # tonnes -> kg
    veh = df[df["CATEGORIE"] == "Vehicule"]
    assert list(veh["BL"]) == ["T002", "T003", "T003", "T004"]
    cat = veh.iloc[0]
    assert (cat["MARQUE"], cat["MODELE"], cat["CHÂSSIS"], cat["_ENGINE_NO"]) == \
        ("CATERPILLAR", "320GC EXCAVATOR", "CAT00320TEST00001", "ABC12345")
    assert "MALI" in veh.iloc[1]["FINAL DESTINATION TETRAX"] and veh.iloc[1]["CHÂSSIS"] == ""
    grue = veh.iloc[3]
    assert (grue["MARQUE"], grue["MODELE"], str(grue["ANNEE DE FABRICATION"])) == \
        ("ZOOMLION", "ZCC600V-1 CRAWLER CRANE", "2026")
    colis = df[(df["CATEGORIE"] == "Colis") & (df["BL"] == "T004")]
    assert len(colis) == 2 and set(colis["MODELE"]) == {"ACCESSORIES"}
    bobines = df[df["BL"] == "T001"]
    assert len(bobines) == 4 and set(bobines["MODELE"]) == {"HOT ROLLED STEEL COILS"}
    assert len(df.attrs["avertissements"]) == 1                     # total TTL cohérent


def test_controle_total_et_premasque():
    df = c.parse_crane_manifest(_fichier(ttl_pcs=11), "x.xlsx")
    assert any("Total colis" in w for w in df.attrs["avertissements"])
    rows, _ = P.rows_from_premasque_df(df)
    assert len(rows) == 4 and rows[0]["POL IPAKI"] == "CNTXG"       # « TIAN JIN(BH) »


def test_sans_colonne_bl_erreur_claire():
    wb = Workbook()
    wb.active.append(["FOO", "BAR"])
    wb.active.append(["a", "b"])
    b = io.BytesIO()
    wb.save(b)
    try:
        c.parse_crane_manifest(b.getvalue(), "x.xlsx")
    except ValueError as e:
        assert "B/L" in str(e)
    else:
        raise AssertionError("ValueError attendue")
