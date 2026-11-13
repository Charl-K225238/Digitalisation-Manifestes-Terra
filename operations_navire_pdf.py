"""Export PDF du formulaire d'opérations navire au gabarit DC_GR-117 (3 pages A4 paysage).

Reproduit les rubriques du formulaire papier ; seules les cases calculées sont remplies.
Police standard (latin-1) : pas de caractères hors latin-1 dans les libellés.
"""
from __future__ import annotations

import os
from datetime import datetime

from fpdf import FPDF

LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo_terra.png")
MAX_OPERATEURS = 4

# Gabarit : page -> [(groupe, [(code | None, libellé, unité)])]
GABARIT = {
    "discharge": [
        ("DISCHARGE EMPTY CONTAINERS", [(201, "Unl 20' mty", "U"), (202, "Unl 40' mty", "U"),
                                        (203, "Unl Bolster mty", "U"), (220, "Unl 40' Platf empty", "U"),
                                        (274, "Unl MAFI mty", "U")]),
        ("DISCHARGE FULL CONTAINERS", [(204, "Unl 20' full", "U"), (205, "Unl 20' full tshp", "U"),
                                       (214, "Unl 20' full reef", "U"), (215, "Unl 20' full reef tshp", "U"),
                                       (206, "Unl 40' full", "U"), (207, "Unl 40' full tshp", "U"),
                                       (216, "Unl 40' full reefer", "U"), (217, "Unl 40' full reefer tshp", "U"),
                                       (208, "Unl Bolster full", "U"), (209, "Unl Bolster full tshp", "U"),
                                       (221, "Unl. 40' Platf full", "U"), (140, "Unl. 40' Platf full tshp", "U"),
                                       (275, "Unl MAFI full", "U"), (276, "Unl MAFI full tshp", "U")]),
        ("DISCHARGE CARS AND RORO UNITS", [(222, "Unl Cars < 15m3", "U"), (141, "Unl Cars < 15m3 Tshp", "U"),
                                           (223, "Unl Trucks >= 15m3, < 50m3", "U"),
                                           (142, "Unl Trucks Tshp >= 15m3, < 50m3", "U"),
                                           (224, "Unl Roro > 50m3", "U"), (225, "Unl Roro > 50m3 CUB SUP", "M3"),
                                           (143, "Unl Roro > 50m3 tshp", "U"),
                                           (144, "Unl Roro > 50m3 tshp CUB SUP", "M3")]),
        ("DISCHARGE BREAKBULK", [(263, "Unl General Cargo", "T"), (None, "Unl General Cargo tshp", "T"),
                                 (264, "Unl Sawn Timber Plywood", "m3 et T"),
                                 (None, "Unl Sawn Timber Plywood tshp", "m3 et T")]),
    ],
    "loading": [
        ("LOADING EMPTY CONTAINERS", [(301, "Load 20' mty", "U"), (302, "Load 40' mty", "U"),
                                      (303, "Load Bolster mty", "U"), (355, "Load 40' PLATF mty", "U"),
                                      (318, "Load MAFI mty", "U")]),
        ("LOADING FULL CONTAINERS", [(304, "Load 20' full", "U"), (305, "Load 20' full tshp", "U"),
                                     (314, "Load 20' full reef", "U"), (315, "Load 20' full reef tshp", "U"),
                                     (306, "Load 40' full", "U"), (307, "Load 40' full tshp", "U"),
                                     (316, "Load 40' full reefer", "U"), (317, "Load 40' full reefer tshp", "U"),
                                     (308, "Load Bolster full", "U"), (309, "Load Bolster full tshp", "U"),
                                     (356, "Load 40' Platf full", "U"), (365, "Load 40' Platf full tshp", "U"),
                                     (0, "Load MAFI full", "U"), (320, "Load MAFI full tshp", "U")]),
        ("LOADING CARS AND RORO UNITS", [(357, "Load Cars < 15m3", "U"), (366, "Load Cars < 15m3 tshp", "U"),
                                         (358, "Load Trucks >= 15m3, < 50m3", "U"),
                                         (367, "Load Trucks >= 15m3, < 50m3 tshp", "U"),
                                         (359, "Load roro > 50m3", "U"), (360, "Load roro > 50m3 CUB SUP", "M3"),
                                         (368, "Load roro > 50m3 tshp", "U"),
                                         (369, "Load roro > 50m3 tshp CUB SUP", "M3")]),
        ("LOADING BREAKBULK", [(345, "Load General Cargo", "T"), (None, "Load General Cargo tshp", "T"),
                               (346, "Load Sawn Timber Plywood", "m3 et T"),
                               (None, "Load Sawn Timber Plywood tshp", "m3 et T")]),
        ("HATCH COVERS", [(403, "Load", "U"), (404, "Unload", "U")]),
    ],
    "shifting": [
        ("SHIP/SHIP EMPTY CONTAINERS", [(100, "Shift S/S 20' mty", "U"), (104, "Shift S/S 40' mty", "U"),
                                        (106, "Shift S/S Bolster mty", "U"), (125, "Shift S/S 40 PLATF mty", "U"),
                                        (150, "Shift S/S MAFI mty", "U")]),
        ("SHIP/SHIP FULL CONTAINERS", [(101, "Shift S/S 20' full", "U"), (105, "Shift S/S 40' full", "U"),
                                       (107, "Shift S/S Bolster full", "U"), (126, "Shift S/S 40 PLATF full", "U"),
                                       (151, "Shift S/S MAFI full", "U")]),
        ("SHIP/SHIP CARS AND RORO UNITS", [(127, "Shift S/S Cars < 15m3", "U"),
                                           (128, "Shift S/S Trucks >=, < 50m3", "U"),
                                           (130, "Shift S/S Roro > 50m3", "U"),
                                           (131, "Shift S/S Roro > 50m3 CUB SUP", "M3")]),
        ("SHIP/SHIP GENERAL CARGO", [(103, "Shift S/S general Cargo", "T")]),
        ("SHIP/SHORE/SHIP CONTAINERS EMPTY", [(109, "Shift S/S/S 20' mty", "U"), (113, "Shift S/S/S 40' mty", "U"),
                                              (115, "Shift S/S/S Bolster mty", "U"),
                                              (132, "Shift S/S/S 40' PLATF mty", "U"),
                                              (160, "Shift S/S/S MAFI mty", "U")]),
        ("SHIP/SHORE/SHIP CONTAINER FULL", [(110, "Shift S/S/S 20' full", "U"), (114, "Shift S/S/S 40' full", "U"),
                                            (116, "Shift S/S/S Bolster full", "U"),
                                            (133, "Shift S/S/S 40' PLATF full", "U"),
                                            (161, "Shift S/S/S MAFI full", "U")]),
        ("SHIP/SHORE/SHIP CARS AND RORO UNITS", [(134, "Shift S/S/S Cars < 15m3", "U"),
                                                 (135, "Shift S/S/S Trucks >= 15m3, < 50m3", "U"),
                                                 (136, "Shift S/S/S Roro > 50m3", "U"),
                                                 (137, "Shift S/S/S Roro > 50m3 CUB SUPP", "M3")]),
        ("SHIP/SHORE/SHIP GENERAL CARGO", [(117, "Shift S/S/S general Cargo", "T")]),
    ],
}
# sous-totaux par classe de volume (codes des unités <= 50 m3 / > 50 m3)
SOUS_TOTAUX = {
    "DISCHARGE CARS AND RORO UNITS": ((222, 141, 223, 142), (224, 143)),
    "LOADING CARS AND RORO UNITS": ((357, 366, 358, 367), (359, 368)),
    "SHIP/SHIP CARS AND RORO UNITS": ((127, 128), (130,)),
    "SHIP/SHORE/SHIP CARS AND RORO UNITS": ((134, 135), (136,)),
}
TITRES = {"discharge": "DECHARGEMENT", "loading": "CHARGEMENT", "shifting": "SHIFTING"}


def _txt(s) -> str:
    return str("" if s is None else s).encode("latin-1", "replace").decode("latin-1")


def _dt(v) -> str:
    if isinstance(v, datetime):
        return v.strftime("%d/%m/%Y %H:%M")
    return _txt(v)


def _t(x) -> str:
    """Tonnage au format du formulaire : 179,000 / 10,280."""
    return f"{x:,.3f}".replace(",", " ").replace(".", ",")


class _Pdf(FPDF):
    def footer(self):
        self.set_y(-8)
        self.set_font("Helvetica", "", 6)
        self.cell(0, 4, "DC_GR-117", align="L")
        self.set_y(-8)
        self.cell(0, 4, f"{self.page_no()}/{{nb}}", align="R")


def _boite(pdf, x, y, w, h, titre, valeur, fond=None):
    if fond:
        pdf.set_fill_color(*fond)
        pdf.rect(x, y, w, h, style="DF")
    else:
        pdf.rect(x, y, w, h)
    pdf.set_xy(x, y + 0.6)
    pdf.set_font("Helvetica", "B", 7)
    pdf.cell(w, 3.4, _txt(titre), align="C")
    pdf.set_xy(x, y + 4.2)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(w, h - 4.6, _txt(valeur), align="C")


def _entete(pdf, e: dict):
    x0, y0 = 10, 8
    if os.path.exists(LOGO):
        pdf.image(LOGO, x=130, y=y0 + 12, h=11)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_xy(x0, y0)
    for lab, val, w in [("M/S", e.get("Navire"), 85), ("VOY", e.get("Voyage"), 45), ("TYPE", e.get("Type"), 50)]:
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(18, 6, lab, border=1, align="C")
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(w - 18, 6, _txt(val), border=1, align="C")
        pdf.cell(4, 6, "")
    y = y0 + 8
    pdf.set_xy(x0, y)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(30, 6, "ARMATEUR", border=1, align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(55, 6, _txt(e.get("Armateur")), border=1, align="C")
    pdf.set_xy(190, y)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(30, 6, "N° DOSSIER", border=1, align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(40, 6, _txt(e.get("N° dossier")), border=1, align="C")
    y = y0 + 16
    _boite(pdf, 50, y, 60, 10, "ETA RADE", _dt(e.get("ETA rade")))
    _boite(pdf, 170, y, 55, 10, "ACCOSTAGE", _dt(e.get("Accostage")))
    _boite(pdf, 232, y, 55, 10, "APPAREILLAGE", _dt(e.get("Appareillage")))
    y += 12
    _boite(pdf, 50, y, 60, 10, "DEBUT OC", _dt(e.get("Début des opérations")))
    _boite(pdf, 170, y, 55, 10, "FIN OC", _dt(e.get("Fin des opérations")))
    _boite(pdf, 232, y, 55, 10, "PREMIER SHIFT ENGAGE", _txt(e.get("Premier shift")))
    y += 12
    _boite(pdf, 10, y - 12, 38, 10, "ATTENTE ACCOSTAGE", _txt(e.get("Attente accostage")))
    _boite(pdf, 10, y, 38, 10, "EQUIPES AYANT ATTENDU", _txt(e.get("Équipes ayant attendu")))
    _boite(pdf, 112, y, 50, 10, "NOMBRE D'EQUIPES", _txt(e.get("Nombre d'équipes")))
    _boite(pdf, 170, y, 55, 10, "NOMBRE SHIFTS ENGAGES", _txt(e.get("Shifts engagés")))
    _boite(pdf, 232, y, 55, 10, "DERNIER SHIFT ENGAGE", _txt(e.get("Dernier shift")))
    return y + 13


def _tableau(pdf, page, y, cases, ops, noms):
    lignes = sum(len(r) for _, r in GABARIT[page])
    h = min(4.4, (210 - 12 - y - 9) / (lignes + 2))
    w_g, w_c, w_r, w_u, w_n, w_t, w_tot = 34, 10, 50, 11, 15, 21, 28
    x0 = 10
    x_ops = x0 + w_g + w_c + w_r + w_u
    # en-têtes
    pdf.set_fill_color(230, 230, 230)
    pdf.set_font("Helvetica", "B", 6.5)
    pdf.set_xy(x0, y)
    for w, t in [(w_g, "GROUPES RUBRIQUES"), (w_c, "CODES"), (w_r, "RUBRIQUES"), (w_u, "UNITES")]:
        pdf.cell(w, 2 * h, t, border=1, align="C", fill=True)
    for i in range(MAX_OPERATEURS):
        o = ops[i] if i < len(ops) else None
        pdf.set_xy(x_ops + i * (w_n + w_t), y)
        lib = f"{noms.get(o, o)} ({o})" if o else ""
        pdf.cell(w_n + w_t, h, _txt(lib), border=1, align="C", fill=True)
        pdf.set_xy(x_ops + i * (w_n + w_t), y + h)
        pdf.cell(w_n, h, "NB UNITES", border=1, align="C", fill=True)
        pdf.cell(w_t, h, "TONNAGE", border=1, align="C", fill=True)
    x_tot = x_ops + MAX_OPERATEURS * (w_n + w_t)
    pdf.set_xy(x_tot, y)
    pdf.cell(w_tot, 2 * h, "TOTAUX", border=1, align="C", fill=True)
    y += 2 * h
    for groupe, rubriques in GABARIT[page]:
        y_g = y
        for code, lib, unite in rubriques:
            pdf.set_xy(x0 + w_g, y)
            pdf.set_font("Helvetica", "B", 6.5)
            pdf.cell(w_c, h, "" if code is None or code == 0 else str(code), border=1, align="C")
            pdf.set_font("Helvetica", "", 6.5)
            pdf.cell(w_r, h, _txt(lib), border=1)
            pdf.cell(w_u, h, unite, border=1, align="C")
            for i in range(MAX_OPERATEURS):
                o = ops[i] if i < len(ops) else None
                v = cases.get((page, code, o)) if (o and code is not None) else None
                gris = unite in ("T", "m3 et T")
                pdf.set_fill_color(200, 200, 200)
                pdf.set_font("Helvetica", "B", 7.5)
                pdf.cell(w_n, h, "" if not v or gris else str(v["unites"]), border=1, align="C", fill=gris)
                pdf.cell(w_t, h, "" if not v else _t(v["tonnes"]), border=1, align="C")
            y += h
        # groupe (cellule fusionnée)
        pdf.rect(x0, y_g, w_g, y - y_g)
        if len(rubriques) == 1:      # une seule ligne : libellé réduit pour tenir dans la case
            pdf.set_font("Helvetica", "B", 4.6)
            pdf.set_xy(x0 + 0.5, y_g + 0.2)
            pdf.multi_cell(w_g - 1, h / 2 - 0.2, _txt(groupe), align="C")
        else:
            pdf.set_font("Helvetica", "B", 6.5)
            pdf.set_xy(x0 + 1, y_g + (y - y_g) / 2 - 3.5)
            pdf.multi_cell(w_g - 2, 3.3, _txt(groupe), align="C")
        # totaux du groupe
        codes = [c for c, _, u in rubriques if c is not None]
        tot_u = sum(v["unites"] for (p, c, _), v in cases.items() if p == page and c in codes
                    and dict((cc, uu) for cc, _, uu in rubriques)[c] == "U")
        tot_t = sum(v["unites"] for (p, c, _), v in cases.items() if p == page and c in codes
                    and dict((cc, uu) for cc, _, uu in rubriques)[c] == "T")
        pdf.rect(x_tot, y_g, w_tot, y - y_g)
        texte = []
        if groupe in SOUS_TOTAUX and tot_u:
            a, b = SOUS_TOTAUX[groupe]
            s = lambda cc: sum(v["unites"] for (p, c, _), v in cases.items() if p == page and c in cc)
            texte += [f"<= 50 m3 : {s(a)}", f"> 50 m3 : {s(b)}"]
        if tot_u:
            texte.append(f"TOTAL : {tot_u}")
        if tot_t:
            texte.append(f"COLIS : {tot_t}")
        if texte:
            pdf.set_font("Helvetica", "B", 7)
            pdf.set_xy(x_tot, y_g + max(0.5, (y - y_g) / 2 - 1.8 * len(texte)))
            pdf.multi_cell(w_tot, 3.6, "\n".join(texte), align="C")
    return y


def pdf_dc_gr_117(entete: dict, cases: dict, operateurs: list[str], noms: dict[str, str]) -> bytes:
    """entete : champs de l'en-tête ; cases : (page, code, opérateur) -> {unites, tonnes} ;
    operateurs : codes dans l'ordre des colonnes (armateur d'abord)."""
    if len(operateurs) > MAX_OPERATEURS:
        raise ValueError(f"Le formulaire n'a que {MAX_OPERATEURS} colonnes d'opérateurs "
                         f"({len(operateurs)} opérateurs sur l'escale).")
    pdf = _Pdf(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.alias_nb_pages()
    for page in ("discharge", "loading", "shifting"):
        pdf.add_page()
        if page == "discharge":
            y = _entete(pdf, entete)
        else:
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_xy(10, 8)
            pdf.cell(0, 6, _txt(f"{TITRES[page]}  -  M/S {entete.get('Navire', '')}  VOY {entete.get('Voyage', '')}"))
            y = 16
        _tableau(pdf, page, y, cases, operateurs, noms)
    return bytes(pdf.output())
