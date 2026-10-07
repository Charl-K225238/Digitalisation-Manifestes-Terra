"""Note mensuelle PDF pour la direction (Stats Flash).

Reprend les 14 lignes du rapport « Reporting RORO & TEUS » et ajoute la
lecture rapide, les graphiques, les écarts expliqués et les navires prévus.
Règle d'or : aucune information vide — colonnes, lignes, sections et cumuls
sans contenu pertinent sont omis. Police Helvetica (latin-1 : pas de flèches
ni de tirets longs). Logo : assets/logo_terra.png s'il existe, sinon mot-symbole.
"""
from __future__ import annotations

import pathlib

import pandas as pd
from fpdf import FPDF

import stats_flash_builder as sfb

ROUGE = (192, 0, 0)
GRIS = (90, 90, 90)
VERT, ROUGE_P = (11, 122, 59), (179, 38, 30)
LOGO = pathlib.Path(__file__).resolve().parent / "assets" / "logo_terra.png"
W = 190


def _f(v) -> str:
    return "" if v is None or pd.isna(v) else f"{v:,.0f}".replace(",", " ")


def _p(v) -> str:
    return "" if v is None or pd.isna(v) else f"{v * 100:+.1f} %".replace(".", ",")


def _ok(v) -> bool:
    return v is not None and not pd.isna(v)


def build_note(annee: int, n: int, tab: pd.DataFrame, r26: dict, r25: dict, bud: dict,
               src: dict, corrections: pd.DataFrame | None, ctrl: pd.DataFrame | None,
               prevus: dict | None, auteur: str = "") -> bytes:
    y1, mois = annee - 1, sfb.MOIS_FR[n - 1].capitalize()
    mc = sfb.MOIS_COURT[n - 1]
    t = tab.copy()
    t["_cur"] = [r26.get((n, k)) for k in t["_ind"]]
    t = t[t["_cur"].map(_ok)].reset_index(drop=True)          # lignes sans chiffre du mois : omises
    kcum = t["_mois_cumules"].fillna(0)
    show_cum = n >= 2 and (kcum >= 2).any()                   # un cumul d'un seul mois = le mois : sans intérêt
    c_tot, c_tot1, c_pc = f"Total {annee} ({n} mois)", f"Total {y1} ({n} mois)", f"% cumul {annee}/{y1}"
    cum_ok = (kcum >= 2)
    cols = [(f"{mc} {annee}", lambda r: _f(r["_cur"]), 17, "num")]
    if t["Budget / mois"].map(_ok).any():
        cols += [("Budget", lambda r: _f(r["Budget / mois"]), 17, "num"),
                 ("% R/B", lambda r: _p(r["% mois R/B"]), 14, "pct")]
    if t[f"{mois} {y1}"].map(_ok).any():
        cols += [(f"{mc} {y1}", lambda r: _f(r[f"{mois} {y1}"]), 17, "num"),
                 (f"% vs {y1}", lambda r: _p(r[f"% mois {annee}/{y1}"]), 14, "pct")]
    if show_cum:
        cols += [(f"Cumul {annee}", lambda r: _f(r[c_tot]) if r["_mois_cumules"] >= 2 else "", 19, "num")]
        if (t[c_tot1].map(_ok) & cum_ok).any():
            cols += [(f"Cumul {y1}", lambda r: _f(r[c_tot1]) if r["_mois_cumules"] >= 2 else "", 19, "num"),
                     ("% cumul", lambda r: _p(r[c_pc]) if r["_mois_cumules"] >= 2 else "", 14, "pct")]
    lab_w = W - sum(c[2] for c in cols)

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, 14)
    pdf.set_margins(10, 10, 10)
    pdf.add_page()
    # --- en-tête -------------------------------------------------------------
    if LOGO.exists():
        pdf.image(str(LOGO), x=10, y=9, h=12)
    else:
        pdf.set_font("Helvetica", "B", 20); pdf.set_text_color(*ROUGE)
        pdf.set_xy(10, 9); pdf.cell(40, 10, "TERRA")
    pdf.set_text_color(*GRIS); pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(120, 10); pdf.cell(80, 4, "Terminal Roulier d'Abidjan", align="R")
    pdf.set_xy(120, 14); pdf.cell(80, 4, f"Généré le {pd.Timestamp.now().strftime('%d/%m/%Y')}" + (f" par {auteur}" if auteur else ""), align="R")
    pdf.set_xy(10, 24); pdf.set_text_color(0, 0, 0); pdf.set_font("Helvetica", "B", 15)
    pdf.cell(W, 8, f"Reporting RORO & TEUS - {mois} {annee}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*ROUGE); pdf.set_line_width(0.6); pdf.line(10, 33, 200, 33); pdf.ln(3)

    # --- chiffres clés -------------------------------------------------------
    cles = [("ESCALES", "escales"), ("TEUS", "teu"), ("RORO", "roro"), ("NEUFS", "neufs"), ("USAGES", "usages")]
    cles = [(l, k) for l, k in cles if _ok(r26.get((n, k)))]
    if cles:
        bw = W / len(cles)
        y0 = pdf.get_y()
        for i, (l, k) in enumerate(cles):
            x = 10 + i * bw
            pdf.set_fill_color(247, 247, 247); pdf.rect(x + 0.8, y0, bw - 1.6, 17, "F")
            pdf.set_xy(x, y0 + 1.5); pdf.set_font("Helvetica", "", 7.5); pdf.set_text_color(*GRIS)
            pdf.cell(bw, 3.5, l, align="C")
            pdf.set_xy(x, y0 + 5.5); pdf.set_font("Helvetica", "B", 13); pdf.set_text_color(0, 0, 0)
            pdf.cell(bw, 6, _f(r26.get((n, k))), align="C")
            d = sfb._pct(r26.get((n, k)), r25.get((n, k)))
            if d is not None:
                pdf.set_xy(x, y0 + 12); pdf.set_font("Helvetica", "B", 7.5)
                pdf.set_text_color(*(VERT if d >= 0 else ROUGE_P)); pdf.cell(bw, 3.5, _p(d) + f" vs {y1}", align="C")
        pdf.set_y(y0 + 20)

    # --- à retenir (règles, pas d'IA) ---------------------------------------
    phrases = []
    row = t[t["_ind"] == "roro"]
    if not row.empty:
        r = row.iloc[0]
        morceaux = [f"RORO : {_f(r['_cur'])} véhicules"]
        if _ok(r["% mois R/B"]): morceaux.append(f"{_p(r['% mois R/B'])} vs budget")
        if _ok(r[f"% mois {annee}/{y1}"]): morceaux.append(f"{_p(r[f'% mois {annee}/{y1}'])} vs {y1}")
        if show_cum and r["_mois_cumules"] >= 2 and _ok(r[c_pc]): morceaux.append(f"cumul {_p(r[c_pc])} vs {y1}")
        phrases.append(", ".join(morceaux))
    bud_rows = t[t["% mois R/B"].map(_ok)]
    if len(bud_rows) >= 2:
        lo, hi = bud_rows.loc[bud_rows["% mois R/B"].idxmin()], bud_rows.loc[bud_rows["% mois R/B"].idxmax()]
        phrases.append(f"Plus en retard sur le budget : {lo['Groupe']} / {lo['Indicateur']} ({_p(lo['% mois R/B'])}) ; "
                       f"plus en avance : {hi['Groupe']} / {hi['Indicateur']} ({_p(hi['% mois R/B'])}).")
    if phrases:
        pdf.set_font("Helvetica", "B", 9.5); pdf.set_text_color(*ROUGE); pdf.cell(W, 5, "À retenir", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9); pdf.set_text_color(0, 0, 0)
        for ph in phrases:
            pdf.set_x(12); pdf.multi_cell(W - 4, 4.6, "- " + ph, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    # --- tableau complet -----------------------------------------------------
    def entete():
        pdf.set_fill_color(31, 56, 100); pdf.set_text_color(255, 255, 255); pdf.set_font("Helvetica", "B", 7.5)
        pdf.cell(lab_w, 7, "Indicateur", border=1, fill=True)
        for h, _, w, _ in cols:
            pdf.cell(w, 7, h, border=1, fill=True, align="C")
        pdf.ln()
    pdf.set_draw_color(190, 190, 190); pdf.set_line_width(0.2)
    entete()
    groupe = None
    for _, r in t.iterrows():
        if r["Groupe"] != groupe:
            groupe = r["Groupe"]
            pdf.set_fill_color(217, 225, 242); pdf.set_text_color(0, 0, 0); pdf.set_font("Helvetica", "B", 8)
            pdf.cell(W, 5.5, groupe, border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8); pdf.set_text_color(0, 0, 0)
        pdf.cell(lab_w, 5.5, "  " + str(r["Indicateur"]), border=1)
        for _, fn, w, kind in cols:
            s = fn(r)
            if kind == "pct" and s:
                pdf.set_text_color(*(VERT if s.startswith("+") else ROUGE_P))
            else:
                pdf.set_text_color(0, 0, 0)
            pdf.cell(w, 5.5, s, border=1, align="R")
        pdf.ln()
    pdf.set_text_color(*GRIS); pdf.set_font("Helvetica", "I", 7)
    notes = []
    part = t[(t["_mois_cumules"] >= 2) & (t["_mois_cumules"] < n)] if show_cum else t.iloc[0:0]
    if not part.empty:
        notes.append(f"Cumul calculé sur les mois disponibles ({int(part['_mois_cumules'].min())} à {n - 1} mois selon l'indicateur) ; "
                     "N-1 et budget comparés sur les mêmes mois.")
    if show_cum and (t["_base25"] == "proratisé").any():
        notes.append(f"Cumul {y1} : total annuel {y1} ramené au nombre de mois disponibles.")
    for ln in notes:
        pdf.multi_cell(W, 3.6, ln, new_x="LMARGIN", new_y="NEXT")

    # --- page 2 : lecture approfondie ---------------------------------------
    graph_mois = [m for m in range(1, n + 1) if _ok(r26.get((m, "roro")))]
    ecarts = []
    if corrections is not None and not corrections.empty:
        c = corrections[(corrections["mois"] == n) & corrections["valeur_saisie"].notna()]
        for _, e in c.iterrows():
            lg, lb = sfb.IND_LABEL.get(e["indicateur"], ("", e["indicateur"]))
            ecarts.append(f"{lg} / {lb} : calculé {_f(e['valeur_calculee'])}, retenu {_f(e['valeur_saisie'])}"
                          + (f" - {e['motif']}" if isinstance(e.get("motif"), str) and e["motif"].strip() else ""))
    a_verifier = []
    if ctrl is not None and not ctrl.empty:
        for _, e in ctrl[ctrl["Statut"] == "À vérifier"].iterrows():
            a_verifier.append(f"{e['Contrôle']} : rapport {_f(e['Valeur rapport'])} / contrôle {_f(e['Valeur de contrôle'])}")
    ref = t[t["% mois R/B"].map(_ok)]
    sections = [len(graph_mois) >= 2, len(ref) >= 1, bool(ecarts), bool(a_verifier), bool(prevus), True]
    if any(sections[:5]):
        pdf.add_page()

        def titre(s):
            pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(*ROUGE)
            pdf.cell(W, 7, s, new_x="LMARGIN", new_y="NEXT"); pdf.set_text_color(0, 0, 0)

        if len(graph_mois) >= 2:
            titre(f"RORO mensuel {annee}" + (f" vs {y1}" if any(_ok(r25.get((m, 'roro'))) for m in graph_mois) else ""))
            vmax = max([r26[(m, "roro")] for m in graph_mois] + [r25.get((m, "roro")) or 0 for m in graph_mois])
            y0, h, bw = pdf.get_y() + 2, 42, W / len(graph_mois)
            for i, m in enumerate(graph_mois):
                x = 10 + i * bw
                a, b = r26[(m, "roro")], r25.get((m, "roro"))
                pdf.set_fill_color(*ROUGE); ha = h * a / vmax
                pdf.rect(x + bw * .15, y0 + h - ha, bw * .3, ha, "F")
                if _ok(b):
                    pdf.set_fill_color(190, 190, 190); hb = h * b / vmax
                    pdf.rect(x + bw * .5, y0 + h - hb, bw * .3, hb, "F")
                pdf.set_font("Helvetica", "", 6.5); pdf.set_text_color(*GRIS)
                pdf.set_xy(x, y0 + h + 1); pdf.cell(bw, 3.5, sfb.MOIS_COURT[m - 1], align="C")
                pdf.set_xy(x, y0 + h - ha - 3.5); pdf.cell(bw * .6, 3, _f(a), align="C")
            pdf.set_y(y0 + h + 7)
        if len(ref) >= 1:
            titre("Réalisé / budget du mois (100 % = budget)")
            for _, r in ref.iterrows():
                v = r["% mois R/B"] + 1
                pdf.set_font("Helvetica", "", 8); pdf.set_text_color(0, 0, 0)
                pdf.cell(60, 5, f"{r['Groupe'][:14]} - {r['Indicateur']}")
                x0, y = pdf.get_x(), pdf.get_y()
                pdf.set_fill_color(*(VERT if v >= 1 else ROUGE_P)); pdf.rect(x0, y + 0.8, min(v, 1.6) / 1.6 * 100, 3.4, "F")
                pdf.set_draw_color(0, 0, 0); pdf.set_line_width(0.3); pdf.line(x0 + 62.5, y, x0 + 62.5, y + 5)
                pdf.set_xy(x0 + 104, y); pdf.cell(20, 5, f"{v * 100:.0f} %")
                pdf.ln(5.5)
            pdf.ln(2)
        for ttl, items in (("Écarts expliqués", ecarts), ("Points à vérifier", a_verifier)):
            if items:
                titre(ttl); pdf.set_font("Helvetica", "", 8.5)
                for it in items:
                    pdf.set_x(12); pdf.multi_cell(W - 4, 4.4, "- " + it, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(2)
        if prevus:
            titre("Navires prévus")
            pdf.set_font("Helvetica", "", 9)
            ligne = f"{prevus['navires']} navire(s) - {_f(prevus['vehicules'])} véhicules"
            if prevus.get("hinterland"): ligne += f" dont {_f(prevus['hinterland'])} Hinterland"
            if prevus.get("sans_eta"): ligne += f" - {prevus['sans_eta']} sans ETA saisie"
            pdf.set_x(12); pdf.multi_cell(W - 4, 4.6, ligne, new_x="LMARGIN", new_y="NEXT"); pdf.ln(2)
        # sources & fiabilité (uniquement ce qui existe)
        compte = {}
        for k in t["_ind"]:
            compte[src.get(k, "")] = compte.get(src.get(k, ""), 0) + 1
        libelle = {sfb.SRC_VOLUMES: "classeur volumes", sfb.SRC_PAA: "extrait PAA", "Saisie manuelle": "saisie manuelle",
                   sfb.SRC_RAPPORT: "rapport existant"}
        parts = [f"{v} chiffre(s) : {libelle[k]}" for k, v in compte.items() if k in libelle]
        if parts:
            titre("Sources et fiabilité"); pdf.set_font("Helvetica", "", 8.5)
            pdf.set_x(12); pdf.multi_cell(W - 4, 4.4, " - ".join(parts), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
