"""Time sheet TETRA scanné : lecture OCR pour pré-remplir l'en-tête du formulaire DC_GR-117.

Seules les dates/heures « From / Till » et le quart (DAY / NIGHT) sont exploités :
l'OCR lit mal certains chiffres, les valeurs sont donc présentées « à vérifier ».
"""
from __future__ import annotations

import re
from datetime import datetime

_RE_PERIODE = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{1,2})[:.]?(\d{2})\b")  # « 2230 » lu sans « : »
_RE_QUART = re.compile(r"TIME\s*[:;]?\s*(DAY|NIGHT)", re.I)
QUARTS = ("Jour", "Nuit")


def _pymupdf():
    try:
        import pymupdf
        return pymupdf
    except ImportError:
        import fitz
        return fitz


def texte_pages(data: bytes, dpi: int = 300) -> list[str]:
    """Texte de chaque page : texte natif s'il existe, sinon OCR Tesseract."""
    import pytesseract
    from PIL import Image
    fitz = _pymupdf()
    pages = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for p in doc:
            t = p.get_text()
            if len(t.strip()) > 200:
                pages.append(t)
                continue
            pix = p.get_pixmap(dpi=dpi)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            pages.append(pytesseract.image_to_string(img, config="--psm 6"))
    return pages


_RE_DUREE = re.compile(r"\b([0-9OoIl]{1,2})\s*h\s*(?:([0-9OoIl]{1,2})\s*mi?n?)?|\b([0-9OoIl]{1,2})\s*min", re.I)


def _date_ou_none(g) -> datetime | None:
    j, mo, a, h, mi = map(int, g.groups())
    try:
        return datetime(a, mo, j, h, mi)
    except ValueError:
        return None


def _chiffres(x: str | None) -> int:
    return int((x or "0").translate(str.maketrans("OoIl", "0011")))


def _duree(texte: str):
    from datetime import timedelta
    m = _RE_DUREE.search(texte)
    if not m:
        return None
    try:
        if m.group(3):
            return timedelta(minutes=_chiffres(m.group(3)))
        return timedelta(hours=_chiffres(m.group(1)), minutes=_chiffres(m.group(2)))
    except ValueError:
        return None


def _periodes(texte: str) -> list[tuple]:
    """(From, Till) des lignes d'opérations (partie au-dessus de « SHIFTING »).
    Till est recalculé par From + durée quand l'OCR a mal lu une date (« 14/11 » pour « 11/11 »)."""
    from datetime import timedelta
    zone = re.split(r"\b(?:SHIFTING|DELAYS|EQUIPEMENT)\b", texte, maxsplit=1, flags=re.I)[0]
    out = []
    for ligne in zone.splitlines():
        ms = list(_RE_PERIODE.finditer(ligne))
        if len(ms) < 2:
            continue
        f, t = _date_ou_none(ms[0]), _date_ou_none(ms[1])
        d = _duree(ligne[ms[1].end():])
        if f and d is not None and timedelta(0) < d <= timedelta(hours=24):
            calc = f + d
            if t is None or abs((t - calc).total_seconds()) > 300:
                t = calc
        if f and t and not (timedelta(0) <= t - f <= timedelta(hours=24)):
            t = None
        out.append((f, t))
    return out


def analyser(pages: list[str]) -> dict:
    """-> {debut, fin, premier_shift, dernier_shift, rejets}.

    Seules les lignes d'opérations sont lues (les retards sont ignorés). Les dates éloignées de
    plus de 3 jours de la médiane (erreurs d'OCR) sont écartées et comptées dans « rejets »."""
    par_page, rejets = [], 0
    for t in pages:
        m = _RE_QUART.search(t)
        quart = (QUARTS[0] if m.group(1).upper() == "DAY" else QUARTS[1]) if m else None
        per = _periodes(t)
        rejets += sum(x is None for p in per for x in p)
        par_page.append((quart, per))
    toutes = sorted(x for _, per in par_page for p in per for x in p if x)
    if not toutes:
        return {"debut": None, "fin": None, "rejets": rejets}
    med = toutes[len(toutes) // 2]
    ok = lambda x: x is not None and abs((x - med).total_seconds()) <= 3 * 86400
    debuts = [f for _, per in par_page for f, _ in per if ok(f)]
    fins = [t for _, per in par_page for _, t in per if ok(t)]
    rejets += sum(1 for x in toutes if not ok(x))
    out = {"debut": min(debuts or fins), "fin": max(fins or debuts), "rejets": rejets}
    quarts = [(min(f for f, _ in per if ok(f)).date(), q) for q, per in par_page
              if q and any(ok(f) for f, _ in per)]
    if quarts:
        q = sorted(set(quarts), key=lambda s_: (s_[0], QUARTS.index(s_[1])))
        out["premier_shift"], out["dernier_shift"] = q[0], q[-1]
    return out


def lire_time_sheet(data: bytes) -> dict:
    return analyser(texte_pages(data))
