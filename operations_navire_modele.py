"""Modèle Excel « Fiche shifting » (opérations navire DC_GR-117).

Le fichier généré est relu par operations_navire.lire_fiche_shifting :
ne pas modifier les intitulés de colonnes sans adapter le lecteur.
"""
from __future__ import annotations

import io
from datetime import date

import xlsxwriter

from operations_navire import COLONNES_SHIFTING, LIBELLE_CLASSE, RUBRIQUES

POSITIONS_LISTE = ["Reste à bord", "Débarqué puis rembarqué"]
NB_LIGNES = 60
LIGNE_ENTETE = 7          # ligne Excel (base 0) des intitulés de colonnes


def modele_shifting_xlsx(navire: str = "", voyage: str = "", jour: date | None = None) -> bytes:
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    ws = wb.add_worksheet("Fiche shifting")
    f_titre = wb.add_format({"bold": True, "font_size": 14})
    f_lab = wb.add_format({"bold": True})
    f_saisie = wb.add_format({"border": 1, "locked": False})
    f_cons = wb.add_format({"italic": True, "font_color": "#333333"})
    f_ent = wb.add_format({"bold": True, "border": 1, "bg_color": "#D9D9D9", "text_wrap": True, "valign": "vcenter"})
    f_ent_obl = wb.add_format({"bold": True, "border": 1, "bg_color": "#BFBFBF", "text_wrap": True, "valign": "vcenter"})
    f_cell = wb.add_format({"border": 1, "locked": False})
    f_num = wb.add_format({"border": 1, "locked": False, "num_format": "0.000"})
    f_dim = wb.add_format({"border": 1, "locked": False, "num_format": "0.00"})
    f_no = wb.add_format({"border": 1, "align": "center", "font_color": "#555555"})
    f_manque = wb.add_format({"bg_color": "#7F7F7F", "font_color": "#FFFFFF"})
    f_double = wb.add_format({"bg_color": "#F4B183"})

    ws.write(0, 0, "Fiche shifting", f_titre)
    for i, (lab, val) in enumerate([("Navire", navire), ("Voyage", voyage),
                                    ("Date", jour.strftime("%d/%m/%Y") if jour else ""),
                                    ("Shift", ""), ("Pointeur", "")]):
        ws.write(1, i * 2, lab, f_lab)
        ws.write(1, i * 2 + 1, val, f_saisie)
    ws.data_validation(1, 7, 1, 7, {"validate": "list", "source": ["Jour", "Nuit"]})
    ws.write(3, 0, "• Une ligne par véhicule déplacé.", f_cons)
    ws.write(4, 0, "• Obligatoire : poids, classe et position (cases grisées si vides).", f_cons)
    ws.write(5, 0, "• Dimensions : gros engins seulement.", f_cons)

    obligatoires = {"N° châssis", "Poids (t)", "Classe", "Position"}
    for c, nom in enumerate(COLONNES_SHIFTING):
        ws.write(LIGNE_ENTETE, c, nom + (" *" if nom in obligatoires else ""),
                 f_ent_obl if nom in obligatoires else f_ent)
    ws.set_row(LIGNE_ENTETE, 30)
    for c, w in enumerate([5, 24, 22, 10, 16, 24, 9, 9, 9]):
        ws.set_column(c, c, w)

    d, f = LIGNE_ENTETE + 1, LIGNE_ENTETE + NB_LIGNES
    for i in range(NB_LIGNES):
        r = d + i
        ws.write(r, 0, i + 1, f_no)
        ws.write_blank(r, 1, None, f_cell)
        ws.write_blank(r, 2, None, f_cell)
        ws.write_blank(r, 3, None, f_num)
        ws.write_blank(r, 4, None, f_cell)
        ws.write_blank(r, 5, None, f_cell)
        for c in (6, 7, 8):
            ws.write_blank(r, c, None, f_dim)

    ws.data_validation(d, 4, f, 4, {"validate": "list", "source": list(LIBELLE_CLASSE.values())})
    ws.data_validation(d, 5, f, 5, {"validate": "list", "source": POSITIONS_LISTE})
    ws.data_validation(d, 3, f, 3, {"validate": "decimal", "criteria": "between", "minimum": 0.1,
                                    "maximum": 300, "error_message": "Poids en tonnes (ex. 1,350)."})
    ws.data_validation(d, 6, f, 8, {"validate": "decimal", "criteria": "between", "minimum": 0.5,
                                    "maximum": 30, "error_message": "Dimension en mètres (ex. 11,50)."})

    x1 = d + 1  # numéro de ligne Excel (base 1)
    # case obligatoire vide alors que la ligne est commencée
    deb = f'OR($B{x1}<>"",$C{x1}<>"",$D{x1}<>"",$E{x1}<>"",$F{x1}<>"")'
    for col in "CDEF":
        ws.conditional_format(f"{col}{x1}:{col}{f + 1}",
                              {"type": "formula", "criteria": f'=AND({deb},${col}{x1}="")', "format": f_manque})
    ws.conditional_format(f"C{x1}:C{f + 1}", {"type": "formula", "format": f_double,
                          "criteria": f'=AND($C{x1}<>"",COUNTIF($C${x1}:$C${f + 1},$C{x1})>1)'})
    ws.protect("", {"format_columns": True, "format_rows": True, "select_locked_cells": True,
                    "select_unlocked_cells": True})
    ws.freeze_panes(LIGNE_ENTETE + 1, 0)
    ws.set_landscape()
    ws.fit_to_pages(1, 0)
    wb.close()
    return buf.getvalue()


PAGES = {"discharge": "Déchargement", "loading": "Chargement", "shifting": "Shifting"}


def detail_xlsx(res, entete: dict, noms_op: dict[str, str]) -> bytes:
    """Excel « détail » : formulaire (cases), lignes sources, contrôles. Fichier séparé du PDF."""
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    gras = wb.add_format({"bold": True, "bg_color": "#D9D9D9", "border": 1})
    ws = wb.add_worksheet("Formulaire")
    ligne = 0
    for k, v in entete.items():
        ws.write(ligne, 0, k, gras)
        ws.write(ligne, 1, "" if v is None else str(v))
        ligne += 1
    ligne += 1
    for j, h in enumerate(["Page", "Code", "Rubrique", "Unité", "Opérateur", "Unités", "Tonnes"]):
        ws.write(ligne, j, h, gras)
    for (p, c, o), v in sorted(res.cases.items(), key=lambda x: (list(PAGES).index(x[0][0]), x[0][1], x[0][2])):
        ligne += 1
        lib, unite = RUBRIQUES[(p, c)]
        ws.write_row(ligne, 0, [PAGES[p], c or "", lib, unite, noms_op.get(o, o), v["unites"], v["tonnes"]])
    ws.set_column(0, 0, 14); ws.set_column(2, 2, 34); ws.set_column(4, 4, 18)
    if len(res.detail):
        d = res.detail.copy()
        d["page"] = d["page"].map(PAGES)
        d["operateur"] = d["operateur"].map(lambda o: noms_op.get(o, o))
        wd = wb.add_worksheet("Lignes sources")
        for j, h in enumerate(d.columns):
            wd.write(0, j, h, gras)
        for i, row in enumerate(d.itertuples(index=False), start=1):
            wd.write_row(i, 0, ["" if (isinstance(x, float) and x != x) else x for x in row])
    wc = wb.add_worksheet("Contrôles")
    for j, h in enumerate(["Niveau", "Contrôle", "Détail"]):
        wc.write(0, j, h, gras)
    for i, c in enumerate(res.controles, start=1):
        wc.write_row(i, 0, [c.niveau, c.titre, c.detail])
    wc.set_column(1, 2, 60)
    wb.close()
    return buf.getvalue()
