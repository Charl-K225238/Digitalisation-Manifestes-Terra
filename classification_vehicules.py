"""
Générateur de tableau de classification des véhicules par POL et volume.
Supporte 4 formats de manifeste :
  - Chinese RoRo XLSX (ex: Metsovo)
  - MOL ALIS PDF (ex: Euphony Ace)
  - Grimaldi PDF (ex: Great Cotonou)
  - Hyundai Glovis PDF scanné (Bill of Lading + General Cargo Manifest, OCR)

Usage:
  from classification_vehicules import generate_classification
  generate_classification(manifest_path, output_path, ship_name, voyage)
"""

import re
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from collections import defaultdict

# ─── Data structures ───

@dataclass
class VehicleEntry:
    """Un B/L ou une entrée de package dans le manifeste."""
    bl_number: str
    pol: str  # Port of Loading
    nombre: int  # Nombre de véhicules
    tonnage: float  # Poids brut (kg)
    volume: float  # Volume (m³/CBM)
    description: str = ""
    is_new: bool = False  # Véhicule neuf
    unit_volume: float = 0.0  # Volume unitaire calculé
    tranche: str = ""  # <15, 15-50, >50
    excluded: bool = False  # Exclu de la classification
    exclude_reason: str = ""
    pod: str = ""  # Port of Discharge (renseigné uniquement par le parser Hyundai Glovis pour l'instant)

    def classify(self):
        """Calcule le volume unitaire et la tranche."""
        if self.nombre > 0 and self.volume > 0:
            self.unit_volume = self.volume / self.nombre
            if self.unit_volume < 15:
                self.tranche = "<15"
            elif self.unit_volume <= 50:
                self.tranche = "15-50"
            else:
                self.tranche = ">50"
        elif self.nombre > 0 and self.tonnage > 0 and self.volume == 0:
            # Pas de volume mais poids significatif → classer en >50 par défaut
            # (cohérent avec la pratique de référence pour les véhicules lourds)
            self.unit_volume = 0.0
            self.tranche = ">50"
        else:
            self.tranche = "unknown"


# ─── Format detection ───

def detect_format(filepath: str) -> str:
    """Détecte le format du manifeste."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext in ('.xlsx', '.xls'):
        return 'chinese_roro'
    elif ext == '.pdf':
        # Read first page to detect format
        text = _extract_pdf_text(filepath, max_pages=3)
        if 'MOLU' in text or 'MOL LINER' in text or 'MOL (EUROPE)' in text:
            return 'mol_alis'
        elif 'P : P' in text or 'H : H' in text or 'GRIMALDI' in text.upper():
            return 'grimaldi'
        elif any(kw in text for kw in ['Move Type', 'Bill of Lading', 'LM RoRo', 'Small Van']):
            return 'grimaldi'
        elif not text.strip():
            # Aucun texte extractible : PDF scanné (image), pas de couche
            # texte (contrairement à Grimaldi/MOL/RoRo qui sont générés
            # numériquement). Bascule sur une détection OCR rapide (1 page,
            # basse résolution) avant de conclure "unknown".
            hint = _quick_ocr_format_hint(filepath)
            return hint or 'unknown'
        return 'unknown'
    return 'unknown'


def _quick_ocr_format_hint(filepath: str) -> str:
    """Détection OCR légère (1 page, 200 dpi) pour les manifestes scannés
    sans couche texte. Retourne le format détecté ou '' si aucun connu.
    N'est appelée que quand pdftotext ne renvoie rien (voir detect_format)."""
    try:
        import pymupdf as fitz
        import pytesseract
        doc = fitz.open(filepath)
        text_all = ""
        for i in range(min(2, doc.page_count)):
            img = _render_page_rotated(doc, i, dpi=200)
            text_all += pytesseract.image_to_string(img, config="--psm 6").upper()
            if "GLOVIS" in text_all and "HYUNDAI" in text_all:
                break
        doc.close()
        if "GLOVIS" in text_all and "HYUNDAI" in text_all:
            return "hyundai_glovis"
    except Exception:
        pass
    return ""


def _extract_pdf_text(filepath: str, max_pages: int = 0) -> str:
    """Extrait le texte d'un PDF."""
    import subprocess
    cmd = ['pdftotext', '-layout', filepath, '-']
    if max_pages > 0:
        cmd = ['pdftotext', '-layout', '-l', str(max_pages), filepath, '-']
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout


# ─── Parser 1: Chinese RoRo XLSX ───

def parse_chinese_roro(filepath: str) -> Tuple[List[VehicleEntry], dict]:
    """Parse un manifeste Chinese RoRo XLSX."""
    import openpyxl
    wb = openpyxl.load_workbook(filepath)
    ws = wb.active

    # Detect ship name and POL from header rows
    metadata = {'ship_name': '', 'voyage': '', 'pol': '', 'discharge_port': ''}
    for row in ws.iter_rows(min_row=1, max_row=5, values_only=True):
        row_str = ' '.join(str(c) for c in row if c)
        if 'VOYAGE' in row_str.upper() or "SHIP'S NAME" in row_str.upper():
            # Extract ship name and voyage
            for cell in row:
                if cell and 'V.' in str(cell):
                    parts = str(cell).strip()
                    metadata['ship_name'] = parts.split('V.')[0].strip()
                    metadata['voyage'] = 'V.' + parts.split('V.')[1].strip()
        if 'LOADING PORT' in row_str.upper():
            # Cible la cellule qui SUIT celle contenant "LOADING PORT:"
            # (bug corrigé : l'ancienne logique prenait la 1ère cellule sans
            # "LOADING"/"PORT" dans toute la ligne, ce qui attrapait à tort
            # "SHIP'S NAME VOYAGE:" en colonne 0 avant d'atteindre le POL réel)
            for i, cell in enumerate(row):
                if cell and 'LOADING PORT' in str(cell).upper():
                    if i + 1 < len(row) and row[i + 1]:
                        val = str(row[i + 1]).strip().rstrip(',')
                        if val and 'DISCHARGE' not in val.upper():
                            metadata['pol'] = val
                    break

    # Find header row (B/L NO.)
    header_row = 0
    for row_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=10, values_only=True), 1):
        if any(str(c).upper().startswith('B/L') for c in row if c):
            header_row = row_idx
            break

    entries = []
    for row in ws.iter_rows(min_row=header_row + 1, max_row=ws.max_row, values_only=False):
        bl = row[0].value  # Column A: B/L
        if not bl or str(bl).strip() == '':
            continue

        bl = str(bl).strip()
        pkg_count = row[2].value  # Column C: NO. OF PACKAGE
        unit_type = row[3].value if len(row) > 3 else ''  # Column D: UNIT/UNITS/PACKAGE
        desc = str(row[4].value) if row[4].value else ''  # Column E: DESCRIPTION
        weight = row[5].value if row[5].value else 0  # Column F: WEIGHT
        volume = row[6].value if row[6].value else 0  # Column G: MEASUREMENT

        # Skip empty/summary rows
        if not desc or weight == 0:
            continue

        # Clean weight/volume
        try:
            weight = float(weight)
        except (ValueError, TypeError):
            continue
        try:
            volume = float(volume)
        except (ValueError, TypeError):
            continue

        # Count actual vehicles (not packages which may include tools/spare parts)
        nb_vehicles = _count_vehicles_chinese(desc, pkg_count)
        if nb_vehicles == 0:
            continue

        # Detect NEW vehicles
        is_new = bool(re.search(r'\bNEW\b|BRAND\s*NEW|YEAR\s*(?:OF\s*)?MANUFACTURE\s*:\s*202[5-9]', desc, re.IGNORECASE))

        pol = metadata.get('pol', 'UNKNOWN')

        entry = VehicleEntry(
            bl_number=bl,
            pol=pol,
            nombre=nb_vehicles,
            tonnage=weight,
            volume=volume,
            description=desc[:100],
            is_new=is_new,
        )
        entry.classify()
        entries.append(entry)

    return entries, metadata


def _count_vehicles_chinese(desc: str, pkg_count) -> int:
    """Compte les véhicules réels dans une description Chinese RoRo.
    Exclut les TOOLS/spare parts.

    Stratégie v8 :
    - Sans non-véhicules : MAX(scan global VIN 17-car, pkg_count)
      Les VIN listés dans la description comptent chaque véhicule individuellement,
      même si plusieurs sont empaquetés ensemble (remorques empilées, etc.)
    - Avec non-véhicules (TOOLS/TYRE/etc.) : priorité UNITS/VIN comme avant
    """
    desc_upper = desc.upper()
    has_non_vehicle = any(kw in desc_upper for kw in [
        'TOOLS', 'SPARE PART', 'ACCESSORIES', 'TYRE', 'TIRE', 'PNEU',
    ])
    has_mixed_pkg = bool(re.search(r'\d+\s*(?:PKG|PACKAGE)S?\s+(?:TYRE|TIRE|TOOL|SPARE|ACCESS)', desc_upper))

    try:
        pkg_int = int(pkg_count) if pkg_count else 0
    except (ValueError, TypeError):
        pkg_int = 0

    # ── Scan global VIN/PIN : tous les codes 17-car alphanumériques ──
    all_codes = set(re.findall(r'[A-Z0-9]{17}', desc_upper))

    # Filtrer les faux positifs
    false_positives = set()

    # 1. Codes commençant par "MODEL" (ex: MODELZCZ9400TDPH4)
    for c in all_codes:
        if c.startswith('MODEL'):
            false_positives.add(c)

    # 2. Codes sur la même ligne après "MODEL:" keyword, stop au prochain keyword
    for m in re.finditer(r'MODEL\s*[:/.]?\s*', desc_upper):
        after = desc_upper[m.end():]
        stop = len(after)
        for kw in ['VIN', 'PIN', 'ENGINE', 'YEAR', 'MFG']:
            pos = after.find(kw)
            if 0 <= pos < stop:
                stop = pos
        line_end = after.find('\n')
        if 0 <= line_end < stop:
            stop = line_end
        zone = after[:stop]
        for c in re.findall(r'[A-Z0-9]{17}', zone):
            false_positives.add(c)

    # 3. Format tabulaire "MODEL: ... VIN NO: ..." en-tête de colonnes
    #    Détection : MODEL et VIN sur la même ligne, MAIS pas de code VIN
    #    directement après le keyword VIN (sinon c'est du format inline)
    lines = desc_upper.split('\n')
    for idx, line in enumerate(lines):
        if 'MODEL' in line and ('VIN' in line or 'PIN' in line):
            vin_col = max(line.find('VIN'), line.find('PIN'))
            if vin_col < 0:
                continue
            # Vérifier si c'est un vrai en-tête tabulaire :
            # pas de code 17-car juste après le keyword VIN sur cette ligne
            after_vin = line[vin_col:]
            vin_kw_match = re.match(r'(?:VIN\s*(?:NO\.?|CODE|NUMBER)?|PIN)\s*[：:.]?\s*', after_vin)
            if vin_kw_match:
                rest = after_vin[vin_kw_match.end():]
                if re.match(r'[A-Z0-9]{17}', rest):
                    continue  # Format inline, pas tabulaire
            for didx in range(idx + 1, len(lines)):
                dline = lines[didx].strip()
                if not dline or any(dline.startswith(kw) for kw in ['YEAR', 'FREIGHT', 'GOODS', 'TRANSIT']):
                    break
                for cm in re.finditer(r'[A-Z0-9]{17}', lines[didx]):
                    if cm.start() < vin_col - 5:
                        false_positives.add(cm.group())
            break

    vin_count = len(all_codes - false_positives)

    # ── Branche 1 : PAS de non-véhicules ──
    if not has_non_vehicle:
        result = max(vin_count, pkg_int)
        return result if result > 0 else 1

    # ── Branche 2 : AVEC non-véhicules (TOOLS/TYRE/spare parts) ──
    # P1. Total explicite "(N UNITS)" — fiable pour les B/L mixtes
    explicit_total = re.findall(r'[（(]\s*(\d+)\s*UNITS?\s*[）)]', desc_upper)
    if explicit_total:
        return max(int(m) for m in explicit_total)

    # P2. "N UNITS / N KGS" sous-total véhicules
    subtotal_matches = re.findall(r'(\d+)\s*UNITS?\s*/\s*\d+', desc_upper)
    if subtotal_matches:
        return sum(int(m) for m in subtotal_matches)

    # P3. "N UNITS" avant le premier keyword non-véhicule
    unit_matches = re.findall(r'(\d+)\s*UNITS?\b', desc_upper)
    if unit_matches:
        first_nv = len(desc_upper)
        for kw in ['TOOL', 'SPARE', 'TYRE', 'TIRE', 'PNEU', 'ACCESS']:
            pos = desc_upper.find(kw)
            if 0 <= pos < first_nv:
                first_nv = pos
        if first_nv > 0:
            before = desc_upper[:first_nv]
            before_units = re.findall(r'(\d+)\s*UNITS?\b', before)
            if before_units:
                return sum(int(m) for m in before_units)

    # P4. VIN count global (déjà filtré)
    if vin_count > 0:
        return vin_count

    # P5. "N SEMI TRAILER STACK"
    stack_matches = re.findall(r'(\d+)\s*(?:SEMI[\s-]*)?TRAILER\s*STACK', desc_upper)
    if stack_matches:
        return sum(int(m) for m in stack_matches)

    # P6. Package count seulement si pas de mélange
    if not has_mixed_pkg:
        if pkg_int > 0:
            return pkg_int

    return 1


# ─── Parser 2: MOL ALIS PDF ───


def _mol_clean_pol(raw_pol: str) -> str:
    """Nettoie le nom du POL MOL ALIS: enlève parenthèses, suffixes, espaces."""
    pol = raw_pol.strip()
    # Remove trailing single letters (e.g., "PIPAVAV (VICTOR) P" → "PIPAVAV (VICTOR)")
    pol = re.sub(r'\s+[A-Z]$', '', pol)
    # Remove "PORT" suffix
    pol = re.sub(r'\s+PORT$', '', pol, flags=re.IGNORECASE)
    # Remove parenthetical like (VICTOR)
    pol = re.sub(r'\s*\([^)]*\)\s*', ' ', pol).strip()
    return pol


def _mol_actual_vehicle_count(header_count: int, unit_type: str,
                              description: str) -> int:
    """Détermine le nombre réel de véhicules dans un BL MOL ALIS.

    Le manifeste MOL ALIS indique parfois un nombre de colis (packages)
    supérieur au nombre réel de véhicules. Par exemple:
    - "40 VEHICULES" + "EIGHT (8) S.T.C UNITS" → 8 vrais véhicules
    - "17 PACKAGE" + "2 X 777 OFF HIGHWAY TRUCKS" → 2 vrais véhicules
    - "1 PACKAGE" + "1 UNIT:" → 1 vrai véhicule
    """
    desc_upper = description.upper()

    # Pattern 1: "WORD (N) ...UNITS" - spelled out count with digit in parens
    # e.g., "EIGHT (8) S.T.C UNITS RIGID DUMP TRUCKS"
    m = re.search(r'\b\w+\s*\((\d+)\)\s*(?:S\.?T\.?C\.?\s*)?UNITS?\b', desc_upper)
    if m:
        return int(m.group(1))

    # Pattern 2: "N X [vehicle type]" for PACKAGE BLs
    # e.g., "2 X 777 OFF HIGHWAY TRUCKS"
    if unit_type == 'PACKAGE':
        m = re.search(r'\b(\d+)\s*X\s+\d*\s*(?:OFF\s*HIGHWAY|TRUCK|TRAILER)', desc_upper)
        if m:
            return int(m.group(1))

    # Pattern 3: "N UNIT:" or "N UNITS" for PACKAGE BLs with vehicle keywords
    if unit_type == 'PACKAGE':
        vehicle_kw = ['DRILLING RIG', 'TRUCK', 'VEHICLE', 'RIG TRUCK',
                       'BOREHOLE', 'LEYLAND']
        if any(kw in desc_upper for kw in vehicle_kw):
            m = re.search(r'\b(\d+)\s+UNITS?[:\s]', desc_upper)
            if m:
                return int(m.group(1))
            # Default: if PACKAGE but clearly a vehicle, count as 1
            return 1

    return header_count


def parse_mol_alis(filepath: str = '', text: str = '') -> Tuple[List[VehicleEntry], dict]:
    """Parse un manifeste MOL ALIS PDF (pipe-delimited format).

    Args:
        filepath: chemin vers un PDF (utilise pdftotext)
        text: texte déjà extrait (prioritaire sur filepath)
    """
    if not text:
        if not filepath:
            return [], {'ship_name': '', 'voyage': '', 'format': 'MOL ALIS'}
        text = _extract_pdf_text(filepath)

    metadata = {'ship_name': '', 'voyage': '', 'format': 'MOL ALIS'}

    # ── Split into pages ──
    # Each page starts with "ALIS ABIDJAN PROD"
    pages = re.split(r'(?=\s*ALIS\s+ABIDJAN\s+PROD)', text)
    pages = [p for p in pages if p.strip()]

    # ── Extract metadata from first page header ──
    first_header = pages[0] if pages else ''
    vessel_match = re.search(
        r'Vessel\s*:\s*\w+\s+(.+?)\s+Call\s+date',
        first_header, re.IGNORECASE
    )
    if vessel_match:
        metadata['ship_name'] = vessel_match.group(1).strip()
    voyage_match = re.search(r'Voyage\s*\.+:\s*(\S+)', first_header, re.IGNORECASE)
    if voyage_match:
        metadata['voyage'] = 'V.' + voyage_match.group(1).strip()

    # ── Collect BL data per page ──
    # We accumulate description text across continuation pages for each BL
    bl_data = {}  # bl_number -> {pol, count, unit_type, weight, volume, desc_lines}
    bl_order = []  # preserve insertion order

    for page in pages:
        # Extract POL from page header
        pol_match = re.search(
            r'Port\s+of\s+loading\s*\.+:\s*(.+?)(?:\r?\n|$)',
            page, re.IGNORECASE
        )
        if not pol_match:
            continue
        page_pol_raw = pol_match.group(1).strip()
        page_pol = _mol_clean_pol(page_pol_raw)

        # Skip ALL PORTS summary pages
        if page_pol.upper() == 'ALL PORTS':
            continue

        # Skip "Total port of loading" summary pages (they have different column headers)
        if re.search(r'Total\s+port\s+of\s+loading', page, re.IGNORECASE):
            continue

        # Is this a continuation page?
        is_continuation = bool(re.search(r'!\s*Continued\s*\.{3}\s*!', page, re.IGNORECASE))

        # ── Parse BL entries on this page ──
        # Split page into lines
        lines = page.split('\n')

        # Track which BL is active on this page
        active_bl = None

        for line in lines:
            # Skip summary/total lines
            if re.search(r'Total\s+(?:B/L|place|port)', line, re.IGNORECASE):
                continue
            if re.search(r'!\s*CVL\s*:', line):
                continue
            if re.search(r'!\s*(?:TC|FCL|LCL|SHIP|ROLL)\s', line):
                continue

            # Check for BL number at start of a pipe-delimited line
            bl_match = re.match(r'\s*!(MOLU\d{11,})\s*!', line)
            if bl_match:
                bl_num = bl_match.group(1)
                active_bl = bl_num

                if bl_num not in bl_data:
                    # First appearance: extract count, type, weight, volume
                    # Format: !MOLU... ! SH ... ! ! N VEHICULES ! weight ! volume !
                    parts = [p.strip() for p in line.split('!')]
                    # parts[0] = '' (before first !), parts[1] = BL#,
                    # parts[2] = shipper, parts[3] = marks,
                    # parts[4] = desc/count, parts[5] = weight, parts[6] = volume

                    # Extract count and type from description column
                    desc_col = parts[4] if len(parts) > 4 else ''
                    count_match = re.search(
                        r'(\d+)\s+(VEHICULES?|PACKAGES?)\b',
                        desc_col, re.IGNORECASE
                    )
                    if not count_match:
                        # Sometimes the count is on a subsequent line, skip for now
                        # but register the BL to collect description
                        bl_data[bl_num] = {
                            'pol': page_pol,
                            'count': 0, 'unit_type': '',
                            'weight': 0.0, 'volume': 0.0,
                            'desc_lines': [desc_col] if desc_col else [],
                            'found_data': False,
                        }
                        bl_order.append(bl_num)
                        continue

                    count = int(count_match.group(1))
                    unit_type = count_match.group(2).upper()
                    if unit_type.endswith('S'):
                        unit_type = unit_type[:-1]  # PACKAGES -> PACKAGE
                    if unit_type == 'VEHICULE':
                        unit_type = 'VEHICULES'

                    # Weight and volume from pipe columns
                    weight_str = parts[5] if len(parts) > 5 else ''
                    volume_str = parts[6] if len(parts) > 6 else ''

                    weight = 0.0
                    volume = 0.0
                    w_match = re.search(r'([\d,]+(?:\.\d+)?)', weight_str)
                    v_match = re.search(r'([\d,]+(?:\.\d+)?)', volume_str)
                    if w_match:
                        weight = float(w_match.group(1).replace(',', ''))
                    if v_match:
                        volume = float(v_match.group(1).replace(',', ''))

                    bl_data[bl_num] = {
                        'pol': page_pol,
                        'count': count,
                        'unit_type': unit_type,
                        'weight': weight,
                        'volume': volume,
                        'desc_lines': [desc_col],
                        'found_data': True,
                    }
                    bl_order.append(bl_num)
                else:
                    # BL seen again on continuation page: collect description
                    parts = [p.strip() for p in line.split('!')]
                    desc_col = parts[4] if len(parts) > 4 else ''
                    if desc_col:
                        bl_data[bl_num]['desc_lines'].append(desc_col)
                continue

            # Continuation lines for active BL: collect description text
            if active_bl and active_bl in bl_data:
                parts = [p.strip() for p in line.split('!')]
                desc_col = parts[4] if len(parts) > 4 else ''
                if desc_col:
                    bl_data[active_bl]['desc_lines'].append(desc_col)

    # ── Build VehicleEntry list ──
    entries = []
    seen_bls = set()

    for bl_num in bl_order:
        if bl_num in seen_bls:
            continue
        seen_bls.add(bl_num)

        data = bl_data[bl_num]
        if not data['found_data']:
            continue

        full_desc = ' '.join(data['desc_lines'])

        # Determine actual vehicle count (may differ from header count)
        actual_count = _mol_actual_vehicle_count(
            data['count'], data['unit_type'], full_desc
        )

        # Detect NEW vehicles
        is_new = bool(re.search(r'\bNEW\b|BRAND\s*NEW', full_desc, re.IGNORECASE))

        entry = VehicleEntry(
            bl_number=bl_num,
            pol=data['pol'],
            nombre=actual_count,
            tonnage=data['weight'],
            volume=data['volume'],
            description=full_desc[:100],
            is_new=is_new,
        )
        entry.classify()
        entries.append(entry)

    return entries, metadata


# ─── Parser 3: Grimaldi PDF ───

def parse_grimaldi(filepath: str = '', text: str = '') -> Tuple[List[VehicleEntry], dict]:
    """Parse un manifeste Grimaldi (PDF binaire ou texte extrait).

    Args:
        filepath: chemin vers un PDF (utilise pdftotext)
        text: texte déjà extrait (prioritaire sur filepath)
    """
    if not text and filepath:
        text = _extract_pdf_text(filepath)
    if not text:
        return [], {'ship_name': '', 'voyage': '', 'format': 'Grimaldi'}

    metadata = {'ship_name': '', 'voyage': '', 'format': 'Grimaldi'}

    # Extract ship/voyage from header (e.g. "GREAT COTONOU :GTC0626")
    ship_match = re.search(
        r'([A-Z][A-Z\s]+?)\s*:\s*([A-Z]{3}\d{4})',
        text[:3000]
    )
    if ship_match:
        metadata['ship_name'] = ship_match.group(1).strip()
        metadata['voyage'] = ship_match.group(2).strip()

    entries = []

    # ── Split into pages ──
    # Text format: content separated by "Page N of M\n"
    pages = re.split(r'Page\s+\d+\s+of\s+\d+\s*\n?', text)
    if len(pages) < 2:
        pages = text.split('\x0c')  # Fallback: form feed

    # ── Filter P:P pages only ──
    pp_pages = []
    for page in pages:
        if 'P : P' in page or 'P :P' in page or 'P:P' in page:
            pp_pages.append(page)

    if not pp_pages:
        return entries, metadata

    # ── Patterns ──

    # Vehicle type pattern (with count)
    vehicle_pattern = re.compile(
        r'(\d+)\s*-\s*(Used|New)\s+'
        r'(LM\s*(?:Ro\s*Ro)?|Small\s*Van(?:s)?|Big\s*Van(?:s)?|Car(?:s)?|High\s*&?\s*Heavy)',
        re.IGNORECASE
    )

    # Weight: "14,721.000 K|" or "14,721.000 KG|" — MUST end with pipe
    # For K-only (not KG), require comma or dot in number to avoid TAX ID "2302825K|"
    weight_pattern = re.compile(
        r'(\d[\d,]*\.\d+)\s*K(?:G)?\s*\|'    # with decimal point (matches both K| and KG|)
        r'|(\d[\d,]*)\s*KG\s*\|',             # KG without decimal is OK (not ambiguous)
        re.IGNORECASE
    )

    # Volume: "97.511 CBM" or "1170.450 CBM"
    volume_pattern = re.compile(r'(\d[\d,]*\.?\d*)\s*CBM', re.IGNORECASE)

    # B/L pattern: [S330235226] or S330235226 — bornes non-alphanumériques
    # obligatoires (évite de matcher un sous-numéro de châssis, ex.
    # "SUDNS400300160585" contient la sous-chaîne "S400300160" qui matchait
    # à tort sans ces bornes, cassant l'affectation véhicule → bon B/L)
    bl_pattern = re.compile(r'(?<![A-Za-z0-9])\[?(S\d{9})\]?(?![A-Za-z0-9])')

    # Détection du POL : structurelle, pas une liste de ports en dur (un
    # manifeste peut concerner n'importe quel port). Chaque page P:P
    # Grimaldi a une ligne colonnée "Italy |<master>|<place of receipt>|
    # <POL>|<POD>|<delivery>|" (même pattern que "Nationality Of Ship"
    # dans manifest_parser.py, déjà validé en production) : on prend la
    # 4e colonne après "Italy". Remplace l'ancien scan par mots-clés sur
    # les 600 premiers caractères de la page, qui ratait le POL dès que
    # celui-ci apparaissait plus loin (cas réel : tous les B/L de
    # ANVERS/HAMBURG/TILBURY ressortaient en POL "UNKNOWN").
    italy_row_re = re.compile(r'\|\s*Italy\s*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|')

    def _grimaldi_page_pol(page_text: str) -> str:
        m = italy_row_re.search(page_text)
        if not m:
            return ''
        return m.group(3).strip()

    # No tare_weights exclusion — stacked detection handles token-weight vehicles
    tare_weights = set()

    # Stacked-vehicle token weight pattern
    stacked_weight_pattern = re.compile(
        r'Weight\s*:\s*(\d*\.?\d+)\s*Kgs?\.',
        re.IGNORECASE
    )

    # ── Process P:P pages sequentially ──
    # Track current POL and B/L across pages (for continuation pages)
    current_pol = ''
    current_bl = ''
    # Pending entry from previous page's "Continue On Next Page..."
    pending_continuation = None  # (entry, page_index) when last vehicle had no weight/vol

    for page_idx, page in enumerate(pp_pages):
        # Extract POL from page header
        page_pol = _grimaldi_page_pol(page)
        if page_pol:
            current_pol = page_pol

        # ── Handle continuation from previous page ──
        # If we have a pending entry whose weight/volume was on "Continue On Next Page",
        # look for weight/volume at the TOP of this page (before first marker)
        if pending_continuation is not None:
            pentry = pending_continuation
            pending_continuation = None
            # Search zone: start of page to first vehicle/BL marker.
            # Bug corrigé (28/09) : la zone était plafonnée à 2000 caractères
            # ("cont_zone = page[:min(first_marker_pos, 2000)]"), ce qui
            # coupait le poids/volume de continuation quand l'en-tête de
            # page (CARGO MANIFEST + libellés de colonnes) dépasse 2000
            # caractères avant que la donnée réelle n'apparaisse — cas réel
            # vérifié sur ANVERS/GTC0526 (véhicule S329848471, poids à la
            # position 2413, 1er marqueur à 6145) : le véhicule entier
            # disparaissait silencieusement (poids et volume à 0 → rejeté).
            # first_marker_pos borne déjà correctement la zone à ce qui
            # précède le prochain B/L ou véhicule réel ; pas besoin d'un
            # plafond arbitraire en plus.
            first_marker_pos = len(page)
            for fm in vehicle_pattern.finditer(page):
                first_marker_pos = min(first_marker_pos, fm.start())
                break
            for fm in bl_pattern.finditer(page):
                first_marker_pos = min(first_marker_pos, fm.start())
            cont_zone = page[:first_marker_pos]
            cont_weight = _extract_grimaldi_weight(cont_zone, weight_pattern, tare_weights)
            cont_vol = 0.0
            cv_matches = volume_pattern.findall(cont_zone)
            for cv in cv_matches:
                cv_val = float(cv.replace(',', ''))
                if cv_val > 0:
                    cont_vol = cv_val
                    break
            # Update with whatever was found on continuation page
            if cont_weight > 1:
                pentry.tonnage = cont_weight
            if cont_vol > 0.1:
                pentry.volume = cont_vol
            # Include if entry has at least weight or volume (from either page)
            if pentry.tonnage > 1 or pentry.volume > 0.1:
                pentry.classify()
                entries.append(pentry)

        # NB : current_bl n'est PAS réinitialisé ici au dernier B/L de la page.
        # Bug corrigé (28/09) : l'ancien code faisait
        # "current_bl = page_bls[-1]" AVANT la boucle de marqueurs ordonnée
        # par position ci-dessous, donc sur une page de continuation qui
        # contient encore des véhicules du B/L précédent PUIS un nouveau B/L
        # plus bas, ces véhicules de continuation étaient rattachés à tort
        # au nouveau B/L (trouvé en dernier sur la page) au lieu du B/L
        # réellement en cours. current_bl est mis à jour uniquement au fil
        # de la boucle ci-dessous, dans l'ordre réel d'apparition.

        # Build ordered list of (position, type, data) for BLs and vehicles
        markers = []
        for m in bl_pattern.finditer(page):
            markers.append((m.start(), 'bl', m.group(1)))
        for m in vehicle_pattern.finditer(page):
            markers.append((m.start(), 'veh', m))
        markers.sort(key=lambda x: x[0])

        # Assign each vehicle to the most recent B/L
        active_bl = current_bl
        for pos, mtype, data in markers:
            if mtype == 'bl':
                active_bl = data
                current_bl = data
            elif mtype == 'veh':
                vm = data
                nb = int(vm.group(1))
                condition = vm.group(2)
                veh_type = vm.group(3)
                is_new = condition.upper() == 'NEW'

                # Search zone: from vehicle match to next vehicle/BL or +500
                next_marker_pos = None
                for npos, ntype, _ in markers:
                    if npos > vm.end():
                        next_marker_pos = npos
                        break
                end_pos = next_marker_pos if next_marker_pos else min(vm.end() + 500, len(page))
                search_zone = page[vm.start():end_pos]

                # ── Extract weight ──
                weight = _extract_grimaldi_weight(search_zone, weight_pattern, tare_weights)

                # ── Extract volume ──
                volume = 0.0
                v_matches = volume_pattern.findall(search_zone)
                for v in v_matches:
                    v_val = float(v.replace(',', ''))
                    if v_val > 0:
                        volume = v_val
                        break

                # ── Check for stacked vehicle (token weight) ──
                # Only skip if vehicle itself has no real weight (token weight = stacked on another)
                # Don't skip if main vehicle already has proper weight from weight_pattern
                stacked = stacked_weight_pattern.findall(search_zone)
                if stacked and weight <= 1:
                    stacked_val = float(stacked[0])
                    if stacked_val <= 1:
                        continue  # Token weight = stacked on another vehicle

                entry = VehicleEntry(
                    bl_number=active_bl if active_bl else 'UNKNOWN',
                    pol=current_pol if current_pol else 'UNKNOWN',
                    nombre=nb,
                    tonnage=weight,
                    volume=volume,
                    description=f"{condition} {veh_type}",
                    is_new=is_new,
                )

                # Skip if truly no weight AND no volume
                if weight <= 1 and volume <= 0.1:
                    # Check if this is the last vehicle on a continuation page
                    is_last = all(
                        npos <= vm.start() or ntype != 'veh'
                        for npos, ntype, _ in markers
                        if npos != vm.start()
                    )
                    if is_last and 'Continue On Next Page' in page:
                        pending_continuation = entry
                    continue

                # If weight or volume is missing and this is last vehicle on continuation page,
                # defer to next page for the missing piece
                if (weight <= 1 or volume <= 0.1) and 'Continue On Next Page' in page:
                    is_last = all(
                        npos <= vm.start() or ntype != 'veh'
                        for npos, ntype, _ in markers
                        if npos != vm.start()
                    )
                    if is_last:
                        pending_continuation = entry
                        continue

                entry.classify()
                entries.append(entry)

    # Handle any remaining pending continuation at the end
    if pending_continuation is not None:
        pentry = pending_continuation
        if pentry.tonnage > 1 or pentry.volume > 0.1:
            pentry.classify()
            entries.append(pentry)

    return entries, metadata


def _extract_grimaldi_weight(search_zone: str, weight_pattern, tare_weights: set) -> float:
    """Extrait le poids d'une zone de texte Grimaldi."""
    weight = 0.0
    # Try inline weight (e.g. "14,721.000 K|" or "14,721.000 KG|")
    w_matches = weight_pattern.findall(search_zone)
    for w in w_matches:
        # Pattern has 2 groups: (decimal_k_or_kg, integer_kg_only)
        w_str = w[0] if isinstance(w, tuple) and w[0] else (w[1] if isinstance(w, tuple) else w)
        if not w_str:
            continue
        w_val = float(w_str.replace(',', ''))
        if w_val > 5 and int(w_val) not in tare_weights:
            weight = w_val
            break

    # Fallback: number in weight column (e.g. " 112633.00|")
    if weight == 0:
        col_weight = re.findall(r'[\s|](\d[\d,]*\.\d+)\s*\|', search_zone)
        for cw in col_weight:
            cw_val = float(cw.replace(',', ''))
            if cw_val > 100 and int(cw_val) not in tare_weights:
                weight = cw_val
                break
    return weight


# ─── Parser 4: Hyundai Glovis PDF scanné (OCR) ───
# Format découvert le 28/09 : "GENERAL CARGO MANIFEST" + "BILL OF LADING"
# Hyundai Glovis, scan de copieur sans couche texte (pdftotext renvoie vide).
# Contrairement aux 3 autres formats, chaque PDF alterne 2 pages par B/L
# (Manifest résumé + Bill of Lading détaillé) ; seule la page BILL OF LADING
# est parsée (source unique et fiable par B/L), la page Manifest est
# redondante et ignorée. Testé et validé sur 3 B/L réels (100% des champs
# corrects : n° B/L, POL, POD, poids, volume, nombre, marque/modèle).

def _render_page_rotated(doc, page_index: int, dpi: int = 300):
    """Rend une page en image et corrige sa rotation via l'OSD Tesseract
    (ces manifestes sont scannés en paysage dans une page portrait, sans
    drapeau de rotation PDF — la rotation doit être détectée sur l'image)."""
    import pytesseract
    from PIL import Image
    pix = doc[page_index].get_pixmap(dpi=dpi)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    try:
        osd = pytesseract.image_to_osd(img)
        m = re.search(r"Rotate: (\d+)", osd)
        angle = int(m.group(1)) if m else 0
    except Exception:
        angle = 0
    if angle:
        img = img.rotate(-angle, expand=True)
    return img


_HG_ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _hg_extract_bl_number(rotated_img) -> str:
    """Extrait le n° B/L via un recadrage ciblé + agrandissement (l'OCR
    pleine page mélange souvent cette police, ex. 'HDGL...' lu 'BDGL...')."""
    import pytesseract
    from PIL import Image
    w, h = rotated_img.size
    crop = rotated_img.crop((int(w * 0.568), int(h * 0.0656), w, int(h * 0.097)))
    cw, ch = crop.size
    crop = crop.resize((cw * 3, ch * 3), Image.LANCZOS)
    txt = pytesseract.image_to_string(
        crop, config=f"--psm 7 -c tessedit_char_whitelist={_HG_ALNUM}"
    ).strip()
    return re.sub(r"[^A-Z0-9]", "", txt.upper())


_HG_VESSEL_RE = re.compile(r"\n\s*([A-Z][A-Z0-9 .\-]{2,25}?)\s*\|?\s*(\d{2,4})\s*\|?\s*\n")
_HG_PORT_RE = re.compile(
    r"([A-Z][A-Z ,]*?PORT[A-Z ,]*?(?:KOREA|CHINA|JAPAN))\W+"
    r"([A-Z][A-Z, ]*?(?:ABIDJAN|IVORY COAST|COTE D IVOIRE)[A-Z, ]*)"
)
_HG_WEIGHT_RE = re.compile(r"([\d,]+)\s*KGS")
_HG_VOLUME_RE = re.compile(r"(\d{1,4})[.,](\d{3})\s*CBM")
_HG_DESC_RE = re.compile(
    r"(\d+)\s*UNITS?\s+OF\s+([A-Z]+)\s+VEHICLES?(?:\s+MODEL\s+([A-Z0-9\-]+))?", re.I
)


def _hg_parse_bl_page(text: str, rotated_img) -> dict:
    d = {"bl_number": _hg_extract_bl_number(rotated_img)}
    mvs = _HG_VESSEL_RE.search(text)
    d["vessel"], d["voyage"] = (mvs.group(1).strip(), mvs.group(2)) if mvs else ("", "")
    mport = _HG_PORT_RE.search(text)
    d["pol"] = re.sub(r"\s+", " ", mport.group(1)).strip(" ,") if mport else ""
    d["pod"] = re.sub(r"\s+", " ", mport.group(2)).strip(" ,") if mport else ""
    mw = _HG_WEIGHT_RE.search(text)
    d["gross_weight"] = float(mw.group(1).replace(",", "")) if mw else 0.0
    mv = _HG_VOLUME_RE.search(text)
    d["measurement"] = float(f"{mv.group(1)}.{mv.group(2)}") if mv else 0.0
    md = _HG_DESC_RE.search(text)
    if md:
        d["nombre"] = int(md.group(1))
        d["brand"] = md.group(2).upper()
        d["model"] = (md.group(3) or "").upper()
    else:
        d["nombre"], d["brand"], d["model"] = 0, "", ""
    return d


def parse_hyundai_glovis(filepath: str, progress_cb=None) -> Tuple[List[VehicleEntry], dict]:
    """Parse un manifeste Hyundai Glovis scanné (OCR Tesseract).
    progress_cb(page_courante, total_pages) est appelé après chaque page
    pour permettre une barre de progression côté Streamlit (le traitement
    est nettement plus lent que les formats texte : ~15-25s/page)."""
    import pymupdf as fitz

    entries: List[VehicleEntry] = []
    metadata = {"ship_name": "", "voyage": "", "pol": "", "format": "hyundai_glovis"}
    doc = fitz.open(filepath)
    total = doc.page_count
    for i in range(total):
        img = _render_page_rotated(doc, i, dpi=300)
        import pytesseract
        text = pytesseract.image_to_string(img, config="--psm 6")
        if "BILL OF LADING" in text.upper():
            d = _hg_parse_bl_page(text, img)
            if not metadata["ship_name"] and d["vessel"]:
                metadata["ship_name"] = d["vessel"]
                metadata["voyage"] = d["voyage"]
            desc = f"{d['nombre']} UNITS OF {d['brand']} VEHICLES"
            if d["model"]:
                desc += f" MODEL {d['model']}"
            entry = VehicleEntry(
                bl_number=d["bl_number"] or f"HG_PAGE{i+1}",
                pol=d["pol"] or "INCONNU",
                nombre=d["nombre"],
                tonnage=d["gross_weight"],
                volume=d["measurement"],
                description=desc,
                is_new=True,  # expéditions constructeur (KIA/Hyundai) -> véhicules neufs
                pod=d["pod"] or "",
            )
            entry.classify()
            entries.append(entry)
        if progress_cb:
            try:
                progress_cb(i + 1, total)
            except Exception:
                pass
    doc.close()
    return entries, metadata


def build_hyundai_glovis_excel_bytes(entries: List[VehicleEntry], ship_name: str, voyage: str) -> bytes:
    """Export simple 1 ligne par B/L pour la digitalisation complète
    (onglet Pré-Masque) — ce format n'a pas la structure multi-feuilles
    Grimaldi (conteneur/colis/bébé au dos) : ce sont uniquement des
    véhicules neufs constructeur, avec des champs différents (pas de
    chargeur/destinataire détaillé extrait par l'OCR pour l'instant)."""
    import io
    import xlsxwriter
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    ws = wb.add_worksheet("Hyundai Glovis")
    bold = wb.add_format({"bold": True, "bg_color": "#C0292B", "font_color": "white"})
    title = wb.add_format({"bold": True, "font_size": 14})
    ws.write(0, 0, f"{ship_name} - Voyage {voyage}".strip(" -"), title)
    headers = ["N° B/L", "POL", "POD", "Description", "Nombre", "Poids brut (KGS)", "Volume (CBM)", "Neuf"]
    for c, h in enumerate(headers):
        ws.write(2, c, h, bold)
    for r, e in enumerate(entries, start=3):
        ws.write(r, 0, e.bl_number)
        ws.write(r, 1, e.pol)
        ws.write(r, 2, e.pod)
        ws.write(r, 3, e.description)
        ws.write(r, 4, e.nombre)
        ws.write(r, 5, e.tonnage)
        ws.write(r, 6, e.volume)
        ws.write(r, 7, "OUI" if e.is_new else "")
    ws.set_column(0, 0, 20)
    ws.set_column(1, 3, 28)
    ws.set_column(4, 7, 14)
    wb.close()
    return buf.getvalue()


# ─── Classification table generator ───

def _group_by_pol(entries: List[VehicleEntry]) -> dict:
    """Regroupe les entrées par POL, triées par tranche."""
    pol_groups = defaultdict(list)
    for e in entries:
        if not e.excluded:
            pol_groups[e.pol].append(e)
    return dict(pol_groups)


# ─── Intégration Streamlit (onglet Reporting) ───
# Ajouté le 28/09 pour remplacer classification_builder.classify_vehicules()
# (qui recalculait depuis les données déjà archivées/structurées) : ici on
# reparse directement les manifestes bruts uploadés (PDF/XLSX), avec les 3
# parsers validés ci-dessus (344/344, 505/505, 330/330).

def parse_manifest_bytes(filename: str, data: bytes, format_hint: str = "",
                          progress_cb=None) -> Tuple[List["VehicleEntry"], dict, str]:
    """Parse un manifeste depuis des bytes en mémoire (upload Streamlit).
    pdftotext/openpyxl/pymupdf ont besoin d'un chemin disque réel : écrit
    dans un fichier temporaire, parse, puis nettoie systématiquement
    (finally). Retourne (entries, metadata, format_detecte) ;
    format_detecte == 'unknown' si aucun des 4 formats n'a été reconnu
    (entries alors vide). progress_cb (optionnel, page_courante/total) n'est
    utilisé que par le format hyundai_glovis (OCR, ~15-25s/page)."""
    import tempfile
    suffix = os.path.splitext(filename)[1].lower() or '.pdf'
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        fmt = format_hint or detect_format(tmp_path)
        if fmt == 'chinese_roro':
            entries, meta = parse_chinese_roro(tmp_path)
        elif fmt == 'mol_alis':
            entries, meta = parse_mol_alis(tmp_path)
        elif fmt == 'grimaldi':
            entries, meta = parse_grimaldi(tmp_path)
        elif fmt == 'hyundai_glovis':
            entries, meta = parse_hyundai_glovis(tmp_path, progress_cb=progress_cb)
        else:
            entries, meta = [], {'ship_name': '', 'voyage': '', 'format': 'inconnu'}
        meta['_format'] = fmt
        return entries, meta, fmt
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


TRANCHE_ORDER = ['<15', '15-50', '>50']
TRANCHE_LABELS_VEHICULE = {
    '<15': 'VEHICULE < 15 M³', '15-50': 'VEHICULE 15-50 M³', '>50': 'VEHICULE > 50 M³',
}


def entries_to_pivot_df(entries: List["VehicleEntry"]):
    """Tableau croisé POL (lignes, + ligne TOTAL) x tranche de volume
    (groupes de colonnes NOMBRE/TONNAGE/VOLUME) + colonne NEW VEH — pour
    l'affichage écran (Streamlit) et le contrôle avant export. Les entrées
    de tranche 'unknown' (ni volume ni poids exploitable) sont exclues du
    tableau mais comptées séparément (voir classification_diag)."""
    import pandas as pd
    labels = TRANCHE_LABELS_VEHICULE
    cols = (["POL"] + [f"{labels[t]} - {s}" for t in TRANCHE_ORDER for s in ("NOMBRE", "TONNAGE", "VOLUME")]
            + ["NEW VEH"])
    active = [e for e in entries if not e.excluded and e.tranche in TRANCHE_ORDER]
    if not active:
        return pd.DataFrame(columns=cols)

    pol_order = sorted({e.pol for e in active})
    rows = []
    for pol in pol_order:
        g = [e for e in active if e.pol == pol]
        row = {"POL": pol}
        for t in TRANCHE_ORDER:
            gt = [e for e in g if e.tranche == t]
            row[f"{labels[t]} - NOMBRE"] = sum(e.nombre for e in gt)
            row[f"{labels[t]} - TONNAGE"] = round(sum(e.tonnage for e in gt), 1)
            row[f"{labels[t]} - VOLUME"] = round(sum(e.volume for e in gt), 2)
        row["NEW VEH"] = sum(e.nombre for e in g if e.is_new)
        rows.append(row)

    total = {"POL": "TOTAL"}
    for t in TRANCHE_ORDER:
        total[f"{labels[t]} - NOMBRE"] = sum(r[f"{labels[t]} - NOMBRE"] for r in rows)
        total[f"{labels[t]} - TONNAGE"] = round(sum(r[f"{labels[t]} - TONNAGE"] for r in rows), 1)
        total[f"{labels[t]} - VOLUME"] = round(sum(r[f"{labels[t]} - VOLUME"] for r in rows), 2)
    total["NEW VEH"] = sum(r["NEW VEH"] for r in rows)
    rows.append(total)

    return pd.DataFrame(rows, columns=cols)


def classification_diag(entries: List["VehicleEntry"]) -> dict:
    """Diagnostic pour affichage (jamais d'exclusion silencieuse — même
    principe que classification_builder.py) : total véhicules, dont sans
    tranche exploitable (ni volume ni poids), dont neufs."""
    active = [e for e in entries if not e.excluded]
    total = sum(e.nombre for e in active)
    inconnu = sum(e.nombre for e in active if e.tranche == "unknown")
    neuf = sum(e.nombre for e in active if e.is_new)
    return {"total_vehicules": total, "sans_tranche": inconnu, "neufs": neuf,
            "nb_bl": len(active)}


def build_classification_excel_bytes(entries: List["VehicleEntry"], ship_name: str, voyage: str) -> bytes:
    """Génère le classeur Excel (mise en page x150-onglets, voir
    _write_classification_xlsx) entièrement en mémoire, pour un
    st.download_button Streamlit — sans écrire sur le disque du serveur."""
    import io
    pol_groups = _group_by_pol(entries)
    buf = io.BytesIO()
    _write_classification_xlsx(pol_groups, buf, ship_name, voyage)
    return buf.getvalue()


def generate_classification(
    manifest_paths: list,
    output_path: str,
    ship_name: str = "",
    voyage: str = "",
    format_hint: str = "",
) -> str:
    """
    Génère le tableau de classification des véhicules.

    Args:
        manifest_paths: Liste de chemins vers les manifestes
        output_path: Chemin du fichier Excel de sortie
        ship_name: Nom du navire (auto-détecté si vide)
        voyage: Numéro de voyage (auto-détecté si vide)
        format_hint: Force le format ('chinese_roro', 'mol_alis', 'grimaldi')

    Returns:
        Chemin du fichier généré
    """
    if isinstance(manifest_paths, str):
        manifest_paths = [manifest_paths]

    all_entries = []
    all_metadata = {}

    for path in manifest_paths:
        fmt = format_hint or detect_format(path)
        print(f"[INFO] Parsing {os.path.basename(path)} as {fmt}")

        if fmt == 'chinese_roro':
            entries, meta = parse_chinese_roro(path)
        elif fmt == 'mol_alis':
            entries, meta = parse_mol_alis(path)
        elif fmt == 'grimaldi':
            entries, meta = parse_grimaldi(path)
        else:
            print(f"[WARN] Unknown format for {path}, skipping")
            continue

        all_entries.extend(entries)
        if not all_metadata:
            all_metadata = meta

        # Report
        active = [e for e in entries if not e.excluded]
        excluded = [e for e in entries if e.excluded]
        print(f"  → {len(active)} vehicle entries, {sum(e.nombre for e in active)} units")
        if excluded:
            print(f"  → {len(excluded)} excluded ({sum(e.nombre for e in excluded)} units)")

    # Use provided or auto-detected metadata
    if not ship_name:
        ship_name = all_metadata.get('ship_name', 'UNKNOWN')
    if not voyage:
        voyage = all_metadata.get('voyage', '')

    # Group by POL
    active_entries = [e for e in all_entries if not e.excluded]
    pol_groups = _group_by_pol(active_entries)

    # Generate Excel
    _write_classification_xlsx(pol_groups, output_path, ship_name, voyage)

    total_vehicles = sum(e.nombre for e in active_entries)
    print(f"\n[OK] Classification generated: {output_path}")
    print(f"     {len(pol_groups)} POL(s), {total_vehicles} vehicles")

    return output_path


def _write_classification_xlsx(
    pol_groups: dict,
    output_path: str,
    ship_name: str,
    voyage: str,
):
    """Écrit le tableau de classification au format XLSX."""
    import xlsxwriter

    wb = xlsxwriter.Workbook(output_path)
    ws = wb.add_worksheet(f"{ship_name}_{voyage}".replace(' ', '_')[:31])

    # ── Formats ──
    title_fmt = wb.add_format({
        'bold': True, 'font_size': 14, 'align': 'center',
        'valign': 'vcenter', 'border': 1,
    })
    header_fmt = wb.add_format({
        'bold': True, 'font_size': 10, 'align': 'center',
        'valign': 'vcenter', 'bg_color': '#4472C4', 'font_color': 'white',
        'border': 1, 'text_wrap': True,
    })
    subheader_fmt = wb.add_format({
        'bold': True, 'font_size': 9, 'align': 'center',
        'valign': 'vcenter', 'bg_color': '#5B9BD5', 'font_color': 'white',
        'border': 1,
    })
    pol_fmt = wb.add_format({
        'bold': True, 'font_size': 10, 'align': 'left',
        'valign': 'vcenter', 'bg_color': '#D9E2F3', 'border': 1,
    })
    data_fmt = wb.add_format({
        'font_size': 9, 'align': 'center', 'valign': 'vcenter',
        'border': 1, 'num_format': '#,##0',
    })
    data_vol_fmt = wb.add_format({
        'font_size': 9, 'align': 'center', 'valign': 'vcenter',
        'border': 1, 'num_format': '#,##0.000',
    })
    subtotal_fmt = wb.add_format({
        'bold': True, 'font_size': 10, 'align': 'center',
        'valign': 'vcenter', 'bg_color': '#E2EFDA', 'border': 1,
        'num_format': '#,##0',
    })
    subtotal_vol_fmt = wb.add_format({
        'bold': True, 'font_size': 10, 'align': 'center',
        'valign': 'vcenter', 'bg_color': '#E2EFDA', 'border': 1,
        'num_format': '#,##0.000',
    })
    subtotal_label_fmt = wb.add_format({
        'bold': True, 'font_size': 10, 'align': 'left',
        'valign': 'vcenter', 'bg_color': '#E2EFDA', 'border': 1,
    })
    total_fmt = wb.add_format({
        'bold': True, 'font_size': 11, 'align': 'center',
        'valign': 'vcenter', 'bg_color': '#C6EFCE', 'border': 2,
        'num_format': '#,##0',
    })
    total_vol_fmt = wb.add_format({
        'bold': True, 'font_size': 11, 'align': 'center',
        'valign': 'vcenter', 'bg_color': '#C6EFCE', 'border': 2,
        'num_format': '#,##0.000',
    })
    total_label_fmt = wb.add_format({
        'bold': True, 'font_size': 11, 'align': 'left',
        'valign': 'vcenter', 'bg_color': '#C6EFCE', 'border': 2,
    })
    empty_fmt = wb.add_format({'border': 1})

    # ── Column widths ──
    ws.set_column('A:A', 22)  # POL
    for col in range(1, 10):
        ws.set_column(col, col, 12)
    ws.set_column('K:K', 10)  # NEW VEH

    # ── Title ──
    ws.merge_range(0, 0, 0, 10,
                   f'TABLEAU DE CLASSIFICATION DES VEHICULES PAR POL ET VOLUME {ship_name} {voyage}',
                   title_fmt)

    # ── Headers row 2: tranche groups ──
    ws.merge_range(2, 1, 2, 3, 'VEHICULE < 15M3', header_fmt)
    ws.merge_range(2, 4, 2, 6, 'VEHICULE 15 - 50m3', header_fmt)
    ws.merge_range(2, 7, 2, 9, 'VEHICULE > 50m3', header_fmt)

    # ── Headers row 4: sub-columns ──
    ws.write(4, 0, 'POL', subheader_fmt)
    for offset, tranche_start in enumerate([1, 4, 7]):
        ws.write(4, tranche_start, 'NOMBRE', subheader_fmt)
        ws.write(4, tranche_start + 1, 'TONNAGE', subheader_fmt)
        ws.write(4, tranche_start + 2, 'VOLUME', subheader_fmt)
    ws.write(4, 10, 'NEW VEH', subheader_fmt)

    # ── Data rows ──
    row = 5
    grand_totals = {t: {'nb': 0, 'ton': 0, 'vol': 0} for t in ['<15', '15-50', '>50']}
    grand_new = 0

    for pol_name, entries in pol_groups.items():
        # POL header row
        ws.write(row, 0, pol_name, pol_fmt)
        for c in range(1, 11):
            ws.write(row, c, '', empty_fmt)

        # Sort entries: group by row (entries in same row share a line)
        # Each entry gets its own row in the output
        pol_subtotals = {t: {'nb': 0, 'ton': 0, 'vol': 0} for t in ['<15', '15-50', '>50']}
        pol_new = 0
        first_data_row = True

        for entry in entries:
            if entry.tranche == 'unknown':
                continue

            tranche = entry.tranche
            col_offset = {'<15': 1, '15-50': 4, '>50': 7}[tranche]

            if first_data_row:
                # Write on the POL header row itself
                ws.write(row, col_offset, entry.nombre, data_fmt)
                ws.write(row, col_offset + 1, entry.tonnage, data_fmt)
                ws.write(row, col_offset + 2, entry.volume, data_vol_fmt)
                if entry.is_new:
                    ws.write(row, 10, entry.nombre, data_fmt)
                first_data_row = False
            else:
                row += 1
                # Empty POL cell
                ws.write(row, 0, '', empty_fmt)
                for c in range(1, 11):
                    ws.write(row, c, '', empty_fmt)
                ws.write(row, col_offset, entry.nombre, data_fmt)
                ws.write(row, col_offset + 1, entry.tonnage, data_fmt)
                ws.write(row, col_offset + 2, entry.volume, data_vol_fmt)
                if entry.is_new:
                    ws.write(row, 10, entry.nombre, data_fmt)

            pol_subtotals[tranche]['nb'] += entry.nombre
            pol_subtotals[tranche]['ton'] += entry.tonnage
            pol_subtotals[tranche]['vol'] += entry.volume
            if entry.is_new:
                pol_new += entry.nombre

        # POL subtotal row
        row += 2  # Skip a blank row
        pol_total = sum(pol_subtotals[t]['nb'] for t in pol_subtotals)
        ws.write(row, 0, f'{pol_total} VEHICULES', subtotal_label_fmt)
        for tranche, col_start in [('<15', 1), ('15-50', 4), ('>50', 7)]:
            ws.write(row, col_start, pol_subtotals[tranche]['nb'], subtotal_fmt)
            ws.write(row, col_start + 1, pol_subtotals[tranche]['ton'], subtotal_fmt)
            ws.write(row, col_start + 2, pol_subtotals[tranche]['vol'], subtotal_vol_fmt)

            grand_totals[tranche]['nb'] += pol_subtotals[tranche]['nb']
            grand_totals[tranche]['ton'] += pol_subtotals[tranche]['ton']
            grand_totals[tranche]['vol'] += pol_subtotals[tranche]['vol']

        if pol_new:
            ws.write(row, 10, pol_new, subtotal_fmt)
        grand_new += pol_new

        row += 2  # Gap between POLs

    # ── Grand total row ──
    total_vehicles = sum(grand_totals[t]['nb'] for t in grand_totals)
    ws.write(row, 0, f'TOTAL = {total_vehicles} VEHICULES', total_label_fmt)
    for tranche, col_start in [('<15', 1), ('15-50', 4), ('>50', 7)]:
        ws.write(row, col_start, grand_totals[tranche]['nb'], total_fmt)
        ws.write(row, col_start + 1, grand_totals[tranche]['ton'], total_fmt)
        ws.write(row, col_start + 2, grand_totals[tranche]['vol'], total_vol_fmt)
    if grand_new:
        ws.write(row, 10, grand_new, total_fmt)

    wb.close()


# ─── Entry point ───

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print("Usage: python classification_vehicules.py <manifest_path> <output_path> [ship_name] [voyage]")
        sys.exit(1)

    manifest = sys.argv[1]
    output = sys.argv[2]
    ship = sys.argv[3] if len(sys.argv) > 3 else ""
    voy = sys.argv[4] if len(sys.argv) > 4 else ""

    generate_classification(manifest, output, ship, voy)
