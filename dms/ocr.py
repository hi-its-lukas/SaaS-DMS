"""
OCR (Optical Character Recognition) Modul für das DMS
Verwendet Tesseract für Texterkennung aus gescannten PDFs und Bildern
"""

import io
import logging
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict

logger = logging.getLogger('dms')


def extract_text_from_pdf(pdf_content: bytes) -> str:
    """
    Extrahiert Text aus einem PDF.
    Versucht zuerst native Textextraktion, dann OCR falls nötig.
    """
    try:
        import fitz
        
        doc = fitz.open(stream=pdf_content, filetype="pdf")
        text_parts = []
        needs_ocr = False
        
        for page in doc:
            page_text = page.get_text()
            if page_text.strip():
                text_parts.append(page_text)
            else:
                needs_ocr = True
        
        doc.close()
        
        native_text = '\n'.join(text_parts).strip()
        
        if native_text and len(native_text) > 100:
            return native_text
        
        if needs_ocr or len(native_text) < 100:
            ocr_text = ocr_pdf(pdf_content)
            if ocr_text and len(ocr_text) > len(native_text):
                return ocr_text
        
        return native_text
        
    except Exception as e:
        logger.error(f"PDF-Textextraktion fehlgeschlagen: {e}")
        return ""


def ocr_pdf(pdf_content: bytes) -> str:
    """
    Führt OCR auf einem PDF durch (für gescannte Dokumente)
    """
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
        
        images = convert_from_bytes(pdf_content, dpi=300)
        
        text_parts = []
        for i, image in enumerate(images):
            page_text = pytesseract.image_to_string(image, lang='deu+eng')
            text_parts.append(page_text)
        
        return '\n\n'.join(text_parts)
        
    except Exception as e:
        logger.error(f"OCR fehlgeschlagen: {e}")
        return ""


def ocr_image(image_content: bytes) -> str:
    """
    Führt OCR auf einem Bild durch
    """
    try:
        from PIL import Image
        import pytesseract
        
        image = Image.open(io.BytesIO(image_content))
        text = pytesseract.image_to_string(image, lang='deu+eng')
        return text
        
    except Exception as e:
        logger.error(f"Bild-OCR fehlgeschlagen: {e}")
        return ""


def classify_document(text: str) -> Tuple[str, float]:
    """
    Klassifiziert ein Dokument basierend auf dem Textinhalt.
    Gibt den Dokumenttyp und eine Konfidenz (0-1) zurück.
    """
    text_lower = text.lower()
    
    patterns = {
        'LOHNABRECHNUNG': {
            'keywords': ['lohnabrechnung', 'gehaltsabrechnung', 'entgeltabrechnung', 
                        'bruttolohn', 'nettolohn', 'sozialversicherung', 'lohnsteuer',
                        'arbeitgeber-anteil', 'steuerklasse', 'kirchensteuer'],
            'weight': 1.0
        },
        'ARBEITSVERTRAG': {
            'keywords': ['arbeitsvertrag', 'anstellungsvertrag', 'dienstvertrag',
                        'arbeitsverhältnis', 'probezeit', 'kündigungsfrist', 
                        'arbeitszeit', 'vergütung', 'urlaubsanspruch', 'tarifvertrag'],
            'weight': 1.0
        },
        'URLAUBSANTRAG': {
            'keywords': ['urlaubsantrag', 'urlaubsanspruch', 'resturlaub', 
                        'genehmigt', 'abgelehnt', 'erholungsurlaub', 'sonderurlaub'],
            'weight': 1.0
        },
        'KRANKMELDUNG': {
            'keywords': ['arbeitsunfähigkeit', 'krankmeldung', 'au-bescheinigung',
                        'arbeitsunfähigkeitsbescheinigung', 'krankheit', 'arzt'],
            'weight': 1.0
        },
        'ZEUGNIS': {
            'keywords': ['arbeitszeugnis', 'zwischenzeugnis', 'qualifiziertes zeugnis',
                        'zu unserer vollsten zufriedenheit', 'tätigkeiten umfassten',
                        'beurteilung', 'leistung und führung'],
            'weight': 1.0
        },
        'KUENDIGUNG': {
            'keywords': ['kündigung', 'kündigungsschreiben', 'beendigung des arbeitsverhältnisses',
                        'fristgerecht', 'ordentliche kündigung', 'außerordentliche kündigung'],
            'weight': 1.0
        },
        'BEWERBUNG': {
            'keywords': ['bewerbung', 'lebenslauf', 'curriculum vitae', 'cv',
                        'anschreiben', 'motivationsschreiben', 'stellenanzeige'],
            'weight': 1.0
        },
        'SCHULUNG': {
            'keywords': ['teilnahmebescheinigung', 'zertifikat', 'schulung', 
                        'weiterbildung', 'fortbildung', 'seminar', 'workshop'],
            'weight': 1.0
        },
        'ABMAHNUNG': {
            'keywords': ['abmahnung', 'pflichtverstoß', 'arbeitsrechtliche konsequenzen',
                        'verhaltensbedingt', 'verwarnung'],
            'weight': 1.0
        },
        'LOHNSTEUERKARTE': {
            'keywords': ['lohnsteuerbescheinigung', 'elektronische lohnsteuerbescheinigung',
                        'elstam', 'finanzamt', 'steuernummer'],
            'weight': 1.0
        },
        'SOZIALVERSICHERUNG': {
            'keywords': ['sozialversicherungsnachweis', 'jahresmeldung', 
                        'sv-ausweis', 'rentenversicherung', 'sozialversicherungsnummer'],
            'weight': 1.0
        },
        'ZEITNACHWEIS': {
            'keywords': ['zeitnachweis', 'arbeitszeitnachweis', 'stundenzettel',
                        'überstunden', 'arbeitszeit', 'stundenkonto'],
            'weight': 1.0
        }
    }
    
    scores = {}
    
    for doc_type, config in patterns.items():
        score = 0
        for keyword in config['keywords']:
            if keyword in text_lower:
                score += 1
        scores[doc_type] = score * config['weight']
    
    if not scores or max(scores.values()) == 0:
        return ('UNBEKANNT', 0.0)
    
    best_type = max(scores, key=scores.get)
    max_possible = len(patterns[best_type]['keywords'])
    confidence = min(scores[best_type] / (max_possible * 0.3), 1.0)
    
    return (best_type, confidence)


def extract_employee_info(text: str) -> Dict[str, Optional[str]]:
    """
    Extrahiert Mitarbeiterinformationen aus dem Dokumenttext.
    """
    info = {
        'employee_id': None,
        'first_name': None,
        'last_name': None,
        'full_name': None,
    }
    
    employee_id_patterns = [
        r'Personalnummer[:\s]+(\d+)',
        r'Personal-Nr\.[:\s]+(\d+)',
        r'Pers\.Nr\.[:\s]+(\d+)',
        r'Mitarbeiternummer[:\s]+(\d+)',
        r'MA-Nr\.[:\s]+(\d+)',
        r'PersNr[:\s]+(\d+)',
    ]
    
    for pattern in employee_id_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            info['employee_id'] = match.group(1)
            break
    
    name_patterns = [
        r'(?:Herr|Frau|Hr\.|Fr\.)\s+([A-ZÄÖÜ][a-zäöüß]+)\s+([A-ZÄÖÜ][a-zäöüß]+)',
        r'Name[:\s]+([A-ZÄÖÜ][a-zäöüß]+)\s+([A-ZÄÖÜ][a-zäöüß]+)',
        r'Mitarbeiter[:\s]+([A-ZÄÖÜ][a-zäöüß]+)\s+([A-ZÄÖÜ][a-zäöüß]+)',
    ]
    
    for pattern in name_patterns:
        match = re.search(pattern, text)
        if match:
            info['first_name'] = match.group(1)
            info['last_name'] = match.group(2)
            info['full_name'] = f"{match.group(1)} {match.group(2)}"
            break
    
    return info


def get_filing_category_suggestion(doc_type: str) -> Optional[str]:
    """
    Gibt eine Aktenplan-Kategorie basierend auf dem Dokumenttyp zurück.
    """
    category_mapping = {
        'LOHNABRECHNUNG': '05.01',
        'ARBEITSVERTRAG': '02.01',
        'URLAUBSANTRAG': '06.01',
        'KRANKMELDUNG': '07.01',
        'ZEUGNIS': '04.01',
        'KUENDIGUNG': '10.01',
        'BEWERBUNG': '01.01',
        'SCHULUNG': '04.02',
        'ABMAHNUNG': '09.01',
        'LOHNSTEUERKARTE': '05.02',
        'SOZIALVERSICHERUNG': '03.03',
        'ZEITNACHWEIS': '06.02',
    }
    
    return category_mapping.get(doc_type)


def process_document_with_ocr(content: bytes, mime_type: str) -> Dict:
    """
    Verarbeitet ein Dokument mit OCR und KI-Klassifizierung.
    Gibt ein Dictionary mit allen extrahierten Informationen zurück.
    """
    result = {
        'text': '',
        'doc_type': 'UNBEKANNT',
        'doc_type_confidence': 0.0,
        'employee_info': {},
        'category_suggestion': None,
        'ocr_used': False,
    }
    
    try:
        if mime_type == 'application/pdf':
            result['text'] = extract_text_from_pdf(content)
        elif mime_type.startswith('image/'):
            result['text'] = ocr_image(content)
            result['ocr_used'] = True
        else:
            return result
        
        if result['text']:
            doc_type, confidence = classify_document(result['text'])
            result['doc_type'] = doc_type
            result['doc_type_confidence'] = confidence
            result['employee_info'] = extract_employee_info(result['text'])
            result['category_suggestion'] = get_filing_category_suggestion(doc_type)
        
    except Exception as e:
        logger.error(f"Dokumentverarbeitung fehlgeschlagen: {e}")
    
    return result
