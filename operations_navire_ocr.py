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


def analyser(pages: list[str]) -> dict:
    """-> {debut, fin, premier_shift, dernier_shift, rejets}. Les dates impossibles ou éloignées
    de plus de 3 jours de la médiane (erreurs d'OCR) sont écartées et comptées dans « rejets »."""
    dates, quarts, rejets = [], [], 0
    for t in pages:
        m = _RE_QUART.search(t)
        quart = (QUARTS[0] if m.group(1).upper() == "DAY" else QUARTS[1]) if m else None
        dts = []
        for g in _RE_PERIODE.finditer(t):
            j, mo, a, h, mi = map(int, g.groups())
            try:
                dts.append(datetime(a, mo, j, h, mi))
            except ValueError:
                rejets += 1
        dates += dts
        if quart and dts:
            quarts.append((sorted(dts)[len(dts) // 2].date(), quart))
    if dates:
        med = sorted(dates)[len(dates) // 2]
        ok = [d for d in dates if abs((d - med).total_seconds()) <= 3 * 86400]
        rejets += len(dates) - len(ok)
        dates = ok
    out = {"debut": min(dates) if dates else None, "fin": max(dates) if dates else None, "rejets": rejets}
    if quarts:
        q = sorted(set(quarts), key=lambda s: (s[0], QUARTS.index(s[1])))
        out["premier_shift"], out["dernier_shift"] = q[0], q[-1]
    return out


def lire_time_sheet(data: bytes) -> dict:
    return analyser(texte_pages(data))
