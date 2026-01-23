import os
import logging
import magic
from pathlib import Path
from datetime import datetime
import redis
from contextlib import contextmanager

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import Document, ProcessedFile, Employee, Task, SystemLog, Tenant, ScanJob, MatchingRule
from .encryption import encrypt_data, decrypt_data, calculate_sha256, encrypt_file, calculate_sha256_chunked, encrypt_file_streaming
from .ocr import process_document_with_ocr, classify_document, extract_employee_info
from .middleware import set_current_tenant, clear_tenant_context
import re


@contextmanager
def tenant_context(tenant):
    """
    Setzt den Tenant-Kontext für den aktuellen Thread (wichtig für Celery Tasks).
    Stellt sicher, dass der TenantAwareManager korrekte Filter anwendet.
    
    Usage:
        with tenant_context(tenant):
            # Code here will have tenant context set
            # TenantAwareManager will filter correctly
    """
    if tenant:
        set_current_tenant(tenant)
    try:
        yield
    finally:
        clear_tenant_context()


def create_review_task(document, source='UNKNOWN'):
    """
    Erstellt automatisch eine Aufgabe für Dokumente die manuelle Prüfung benötigen.
    
    Args:
        document: Das Dokument das geprüft werden muss
        source: Quelle des Dokuments (SAGE_ARCHIVE, EMAIL, MANUAL_SCAN, UPLOAD)
    """
    source_names = {
        'SAGE_ARCHIVE': 'Sage-Archiv',
        'EMAIL': 'E-Mail',
        'MANUAL_SCAN': 'Manueller Scan',
        'UPLOAD': 'Web-Upload',
        'UNKNOWN': 'Import'
    }
    source_display = source_names.get(source, source)
    
    existing_task = Task.objects.filter(
        document=document,
        status__in=['OPEN', 'IN_PROGRESS']
    ).first()
    
    if existing_task:
        return existing_task
    
    task = Task.objects.create(
        title=f"Dokument prüfen: {document.original_filename[:50]}",
        description=f"Dieses Dokument aus {source_display} konnte nicht automatisch zugeordnet werden.\n\n"
                    f"Bitte prüfen Sie:\n"
                    f"- Mitarbeiter-Zuordnung\n"
                    f"- Dokumenttyp\n"
                    f"- Periode (Monat/Jahr)",
        document=document,
        priority=2,
        status='OPEN'
    )
    
    SystemLog.objects.create(
        level='INFO',
        source='TASK_CREATE',
        message=f"Prüfaufgabe erstellt für: {document.original_filename}",
        details={'document_id': str(document.id), 'task_id': str(task.id), 'source': source}
    )
    
    return task


def auto_classify_document(document, tenant=None):
    """
    Wendet Matching-Regeln auf ein Dokument an.
    Wird beim Import automatisch aufgerufen.
    
    Returns: True wenn Klassifizierung erfolgt ist
    """
    from django.db.models import Q
    
    rules = MatchingRule.objects.filter(is_active=True).order_by('-priority')
    if tenant:
        rules = rules.filter(Q(tenant=tenant) | Q(tenant__isnull=True))
    
    search_text = f"{document.original_filename} {document.title}"
    
    for rule in rules:
        pattern = rule.match_pattern
        
        if not rule.is_case_sensitive:
            search_text_check = search_text.lower()
            pattern = pattern.lower()
        else:
            search_text_check = search_text
        
        matched = False
        
        if rule.algorithm == 'EXACT':
            matched = pattern in search_text_check
        elif rule.algorithm == 'ANY':
            words = pattern.split()
            matched = any(word in search_text_check for word in words)
        elif rule.algorithm == 'ALL':
            words = pattern.split()
            matched = all(word in search_text_check for word in words)
        elif rule.algorithm == 'REGEX':
            try:
                flags = 0 if rule.is_case_sensitive else re.IGNORECASE
                matched = bool(re.search(rule.match_pattern, search_text, flags))
            except re.error:
                matched = False
        elif rule.algorithm == 'FUZZY':
            words = pattern.split()
            for word in words:
                if len(word) >= 4:
                    for i in range(len(search_text_check) - len(word) + 1):
                        substring = search_text_check[i:i+len(word)]
                        matches = sum(a == b for a, b in zip(word, substring))
                        if matches >= len(word) * 0.8:
                            matched = True
                            break
                if matched:
                    break
        
        if matched:
            changed = False
            
            if rule.assign_document_type and not document.document_type:
                document.document_type = rule.assign_document_type
                changed = True
            
            if rule.assign_employee and not document.employee:
                document.employee = rule.assign_employee
                changed = True
            
            if rule.assign_status and document.status in ('UNASSIGNED', 'NEW'):
                document.status = rule.assign_status
                changed = True
            
            if changed:
                document.save()
                log_system_event('DEBUG', 'AutoClassify', 
                    f"Dokument klassifiziert: {document.original_filename}",
                    {'rule': rule.name, 'document_type': str(document.document_type)})
            
            if rule.assign_tags.exists():
                document.tags.add(*rule.assign_tags.all())
            
            return True
    
    return False

logger = logging.getLogger('dms')


def get_redis_client():
    """
    Erstellt eine NEUE Redis-Verbindung bei jedem Aufruf.
    Wichtig für Celery Prefork-Worker - gecachte Verbindungen funktionieren nicht nach Fork.
    """
    redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    return redis.from_url(redis_url)


@contextmanager
def distributed_lock(lock_name, timeout=1800):
    """
    Redis-basierter verteilter Lock mit SETNX (atomar).
    Verhindert, dass zwei Celery-Worker gleichzeitig denselben Job starten.
    
    Features:
    - Standardmäßig 30 Minuten TTL (statt 1 Stunde)
    - Automatische Erkennung und Bereinigung von verwaisten Locks
    - Metadaten für bessere Diagnose
    """
    import uuid
    import time
    import socket
    
    client = get_redis_client()
    lock_key = f"dms:lock:{lock_name}"
    meta_key = f"dms:lock:{lock_name}:meta"
    lock_value = str(uuid.uuid4())
    acquired = False
    
    try:
        # Prüfe ob ein alter Lock existiert und zu alt ist (stale lock detection)
        try:
            existing_meta = client.hgetall(meta_key)
            if existing_meta:
                start_time_raw = existing_meta.get(b'start_time') or existing_meta.get('start_time')
                if start_time_raw:
                    start_time = float(start_time_raw)
                    max_age = timeout * 1.5  # 50% Puffer über TTL
                    lock_age = time.time() - start_time
                    
                    if lock_age > max_age:
                        logger.warning(f"[Lock] {lock_name}: Stale lock detected (age={lock_age:.0f}s > max={max_age:.0f}s), auto-clearing")
                        client.delete(lock_key)
                        client.delete(meta_key)
        except Exception as e:
            logger.warning(f"[Lock] Stale check failed: {e}")
        
        # SETNX ist atomar - nur EIN Client kann erfolgreich setzen
        acquired = client.set(lock_key, lock_value, nx=True, ex=timeout)
        
        if acquired:
            # Speichere Metadaten für Diagnose
            try:
                client.hset(meta_key, mapping={
                    'start_time': str(time.time()),
                    'hostname': socket.gethostname(),
                    'lock_value': lock_value,
                    'timeout': str(timeout)
                })
                client.expire(meta_key, timeout + 60)
            except Exception as e:
                logger.warning(f"[Lock] Failed to set metadata: {e}")
        
        logger.info(f"[Lock] {lock_name}: acquired={acquired}, key={lock_key}")
        
        yield bool(acquired)
    except redis.exceptions.ConnectionError as e:
        logger.error(f"[Lock] Redis connection error: {e}")
        # Bei Verbindungsfehler: Lock überspringen, Task trotzdem ausführen
        yield True
    finally:
        if acquired:
            # Nur löschen wenn wir den Lock besitzen (Lua-Script für Atomarität)
            lua_script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                redis.call("del", KEYS[2])
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            try:
                client.eval(lua_script, 2, lock_key, meta_key, lock_value)
                logger.info(f"[Lock] {lock_name}: released")
            except Exception as e:
                logger.warning(f"[Lock] Failed to release {lock_name}: {e}")


def log_system_event(level, source, message, details=None):
    SystemLog.objects.create(
        level=level,
        source=source,
        message=message,
        details=details or {}
    )
    getattr(logger, level.lower())(f"[{source}] {message}")


def get_mime_type(file_path):
    try:
        return magic.from_file(file_path, mime=True)
    except Exception:
        return 'application/octet-stream'


def extract_employee_from_datamatrix(file_path, max_pages=1, timeout_seconds=10):
    """
    Extrahiert DataMatrix-Codes aus einem PDF.
    Optimiert: Nur erste Seite scannen, mit Timeout.
    
    Returns:
        dict with keys:
            'success': bool - True if processing succeeded
            'error': str or None - Error message if failed
            'codes': list - List of extracted code data
            'employee_ids': list - Parsed employee IDs from codes
            'mandant_code': str or None - Mandant code from Sage format (MD1 -> "1")
            'metadata': dict - All parsed metadata from DataMatrix
    """
    import signal
    
    result = {
        'success': False,
        'error': None,
        'codes': [],
        'employee_ids': [],
        'mandant_code': None,
        'metadata': {}
    }
    
    def timeout_handler(signum, frame):
        raise TimeoutError("DataMatrix extraction timed out")
    
    try:
        import fitz
        from pylibdmtx.pylibdmtx import decode
        from PIL import Image
        import io
        
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout_seconds)
        
        try:
            doc = fitz.open(file_path)
            pages_to_scan = min(len(doc), max_pages)
            
            for page_num in range(pages_to_scan):
                page = doc[page_num]
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))
                
                decoded = decode(img)
                for d in decoded:
                    raw_data = d.data.decode('utf-8')
                    result['codes'].append({'page': page_num, 'raw': raw_data})
                    
                    emp_id = parse_employee_id_from_datamatrix(raw_data)
                    if emp_id and emp_id not in result['employee_ids']:
                        result['employee_ids'].append(emp_id)
                    
                    metadata = parse_datamatrix_metadata(raw_data)
                    if metadata:
                        result['metadata'] = metadata
                        if 'tenant_code' in metadata and not result['mandant_code']:
                            result['mandant_code'] = metadata['tenant_code']
                
                if result['employee_ids']:
                    break
            
            doc.close()
            result['success'] = True
            
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
        
        return result
        
    except TimeoutError:
        logger.warning(f"DataMatrix extraction timed out for {file_path}")
        result['error'] = 'Timeout'
        result['success'] = True
        return result
    except Exception as e:
        logger.warning(f"DataMatrix extraction failed for {file_path}: {e}")
        result['error'] = str(e)
        return result


def parse_employee_id_from_datamatrix(raw_data):
    """
    Parst die Mitarbeiter-ID aus den DataMatrix-Rohdaten.
    
    Unterstützte Formate:
    - Sage Lohnscheine: DDLGA;MD1;PN1;UNlukas.hengl;ED01.12.2025;ES12/2025;YR2025
      → PN = Personalnummer
    - Reine Zahlen
    - ACCOLD-Format: ^1008=PersonalNr^
    - Klartext: PersNr: 123
    """
    if not raw_data:
        return None
    
    raw_data = raw_data.strip()
    
    if raw_data.isdigit():
        return raw_data
    
    patterns = [
        r';PN(\d+)',
        r'^PN(\d+)',
        r'PN(\d+);',
        r'\^1008=([^^\s]+)\^',
        r'\^1010=(\d+)',
        r'PersNr[:\s]*(\d+)',
        r'Personalnummer[:\s]*(\d+)',
        r'PersonalNr[:\s]*(\d+)',
        r'MA[:\s]*(\d+)',
        r'EmpID[:\s]*(\d+)',
        r'EmployeeID[:\s]*(\d+)',
        r'^(\d{4,8})$',
        r'\|(\d+)\|',
        r'=(\d{1,10})\^',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, raw_data, re.IGNORECASE)
        if match:
            value = match.group(1)
            if value.isdigit():
                return value
            digits = re.search(r'(\d+)', value)
            if digits:
                return digits.group(1)
    
    if ';' in raw_data:
        parts = raw_data.split(';')
        for part in parts:
            if part.startswith('PN') and len(part) > 2:
                emp_id = part[2:]
                if emp_id.isdigit():
                    return emp_id
                digits = re.search(r'(\d+)', emp_id)
                if digits:
                    return digits.group(1)
    
    parts = re.split(r'[|;,\s\^=]+', raw_data)
    for part in parts:
        if part.isdigit() and 1 <= len(part) <= 10:
            return part
    
    return None


def parse_datamatrix_metadata(raw_data):
    """
    Extrahiert alle Metadaten aus dem Sage DataMatrix-Format.
    Format: DDLGA;MD1;PN1;UNlukas.hengl;ED01.12.2025;ES12/2025;YR2025
    
    Returns: dict mit keys: employee_id, tenant_code, username, date, period, year
    """
    result = {}
    if not raw_data or ';' not in raw_data:
        return result
    
    parts = raw_data.strip().split(';')
    for part in parts:
        if part.startswith('PN'):
            result['employee_id'] = part[2:]
        elif part.startswith('MD'):
            result['tenant_code'] = part[2:]
        elif part.startswith('UN'):
            result['username'] = part[2:]
        elif part.startswith('ED'):
            result['date'] = part[2:]
        elif part.startswith('ES'):
            result['period'] = part[2:]
        elif part.startswith('YR'):
            result['year'] = part[2:]
    
    return result


def log_datamatrix_content(raw_data, file_name):
    """Loggt den Inhalt eines DataMatrix-Codes für Debugging"""
    logger.info(f"DataMatrix in {file_name}: {raw_data[:200] if raw_data else 'None'}")


def split_pdf_by_datamatrix(file_path, output_dir, timeout_per_page=5):
    """
    Teilt ein mehrseitiges PDF anhand von DataMatrix-Codes auf.
    Bei jedem neuen Mitarbeiter-Code wird ein neues Segment gestartet.
    Behält die Seitenreihenfolge bei (zusammenhängende Segmente).
    
    Args:
        file_path: Pfad zur Original-PDF
        output_dir: Verzeichnis für die geteilten PDFs
        timeout_per_page: Timeout in Sekunden pro Seite
        
    Returns:
        list of dicts: [{'file_path': str, 'employee_id': str, 'pages': list, 'page_count': int}]
    """
    import fitz
    from pylibdmtx.pylibdmtx import decode
    from PIL import Image
    import io
    
    result = []
    
    try:
        doc = fitz.open(file_path)
        total_pages = len(doc)
        
        if total_pages <= 1:
            doc.close()
            return result
        
        segments = []
        current_segment = {'employee_id': None, 'pages': []}
        
        log_system_event('INFO', 'PDFSplitter', f"Scanne {total_pages} Seiten für DataMatrix-Codes: {Path(file_path).name}")
        
        mandant_code_found = None
        
        for page_num in range(total_pages):
            page_emp_id = None
            page_mandant = None
            
            try:
                page = doc[page_num]
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))
                
                decoded = decode(img)
                
                for d in decoded:
                    try:
                        raw_data = d.data.decode('utf-8')
                        emp_id = parse_employee_id_from_datamatrix(raw_data)
                        if emp_id:
                            page_emp_id = emp_id
                            metadata = parse_datamatrix_metadata(raw_data)
                            if metadata.get('tenant_code') and not mandant_code_found:
                                mandant_code_found = metadata['tenant_code']
                            break
                    except:
                        continue
                
            except Exception as e:
                logger.warning(f"Error scanning page {page_num}: {e}")
            
            if page_emp_id and page_emp_id != current_segment['employee_id']:
                if current_segment['pages']:
                    segments.append(current_segment)
                current_segment = {'employee_id': page_emp_id, 'pages': [page_num]}
            else:
                current_segment['pages'].append(page_num)
                if page_emp_id:
                    current_segment['employee_id'] = page_emp_id
        
        if current_segment['pages']:
            segments.append(current_segment)
        
        segments_with_employee = [s for s in segments if s['employee_id']]
        
        if len(segments_with_employee) <= 1:
            doc.close()
            log_system_event('INFO', 'PDFSplitter', f"Nur ein Mitarbeiter-Segment gefunden, kein Split nötig: {Path(file_path).name}")
            return result
        
        if segments and not segments[0]['employee_id'] and len(segments) > 1:
            segments[1]['pages'] = segments[0]['pages'] + segments[1]['pages']
            segments = segments[1:]
        
        log_system_event('INFO', 'PDFSplitter', f"Gefunden: {len(segments)} Segmente in {Path(file_path).name}")
        
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        base_name = Path(file_path).stem
        segment_counter = {}
        
        for segment in segments:
            emp_id = segment['employee_id']
            pages = segment['pages']
            
            if not emp_id:
                emp_id = 'UNBEKANNT'
            
            if emp_id not in segment_counter:
                segment_counter[emp_id] = 0
            segment_counter[emp_id] += 1
            
            try:
                new_doc = fitz.open()
                
                for page_num in pages:
                    new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
                
                suffix = f"_{segment_counter[emp_id]}" if segment_counter[emp_id] > 1 else ""
                split_filename = f"{base_name}_MA{emp_id}{suffix}.pdf"
                split_path = output_path / split_filename
                new_doc.save(str(split_path))
                new_doc.close()
                
                result.append({
                    'file_path': str(split_path),
                    'employee_id': emp_id if emp_id != 'UNBEKANNT' else None,
                    'pages': pages,
                    'page_count': len(pages),
                    'original_file': str(file_path),
                    'mandant_code': mandant_code_found
                })
                
                log_system_event('INFO', 'PDFSplitter', 
                    f"Erstellt: {split_filename} ({len(pages)} Seiten, Segment für MA {emp_id})")
                
            except Exception as e:
                logger.error(f"Error creating split PDF for segment {emp_id}: {e}")
        
        doc.close()
        
        log_system_event('INFO', 'PDFSplitter', 
            f"Split abgeschlossen: {len(result)} Dokumente aus {Path(file_path).name}")
        
        return result
        
    except Exception as e:
        logger.error(f"PDF split failed for {file_path}: {e}")
        log_system_event('ERROR', 'PDFSplitter', f"Split fehlgeschlagen: {str(e)}", {'file': str(file_path)})
        return result


def parse_month_folder(month_folder):
    """
    Extrahiert Jahr und Monat aus YYYYMM Ordnername.
    z.B. '202601' → (2026, 1)
    
    Returns: tuple (year, month) oder (None, None)
    """
    if not month_folder or len(month_folder) != 6:
        return None, None
    try:
        year = int(month_folder[:4])
        month = int(month_folder[4:6])
        if 1 <= month <= 12 and 2000 <= year <= 2100:
            return year, month
    except (ValueError, TypeError):
        pass
    return None, None


def find_employee_by_id(employee_id, tenant=None, mandant_code=None):
    """
    Sucht einen Mitarbeiter anhand der ID.
    Versucht verschiedene ID-Formate inkl. Sage-Format (Mandant_PersonalNr).
    
    Fallback-Strategie:
    1. Mit Tenant-Filter suchen
    2. Bei tenant=None-Mitarbeitern auch ohne Filter suchen (Legacy-Daten)
    
    Args:
        employee_id: Personalnummer (z.B. "1", "9")
        tenant: Tenant-Objekt für Filterung
        mandant_code: Mandant-Code aus DataMatrix (z.B. "1") 
    """
    if not employee_id:
        return None
    
    def search_in_queryset(qs, emp_id, mandant_code_local, tenant_local):
        """Hilfsfunktion für die Suche in einem Queryset"""
        employee = qs.filter(employee_id=emp_id).first()
        if employee:
            return employee
        
        if mandant_code_local:
            sage_id = f"{mandant_code_local}_{emp_id}"
            employee = qs.filter(employee_id=sage_id).first()
            if employee:
                return employee
        
        if tenant_local and tenant_local.code:
            mandant_num = tenant_local.code.lstrip('0') or '1'
            sage_id = f"{mandant_num}_{emp_id}"
            employee = qs.filter(employee_id=sage_id).first()
            if employee:
                return employee
        
        for prefix in ['1', '2', '3', '4', '5']:
            sage_id = f"{prefix}_{emp_id}"
            employee = qs.filter(employee_id=sage_id).first()
            if employee:
                return employee
        
        if emp_id.isdigit():
            employee = qs.filter(employee_id=emp_id.lstrip('0')).first()
            if employee:
                return employee
            employee = qs.filter(employee_id=emp_id.zfill(8)).first()
            if employee:
                return employee
        
        return None
    
    try:
        if tenant:
            queryset = Employee.objects.filter(tenant=tenant)
            employee = search_in_queryset(queryset, employee_id, mandant_code, tenant)
            if employee:
                return employee
        
        queryset_null = Employee.objects.filter(tenant__isnull=True)
        employee = search_in_queryset(queryset_null, employee_id, mandant_code, tenant)
        if employee:
            return employee
        
        if tenant:
            queryset_all = Employee.objects.all()
            employee = search_in_queryset(queryset_all, employee_id, mandant_code, tenant)
            if employee:
                return employee
        
        return None
    except Exception:
        return None


SAGE_DOCUMENT_TYPES = {
    'LOHNSCHEINE': {
        'patterns': ['Lohnscheine', 'Korrekturlohnscheine'],
        'is_personnel': True,
        'category': '05.01',
        'description': 'Lohnabrechnung'
    },
    'LOHNSTEUERBESCHEINIGUNG': {
        'patterns': ['Elektronische Lohnsteuerbescheinigung', 'Lohnsteuerbescheinigung'],
        'is_personnel': True,
        'category': '05.02',
        'description': 'Lohnsteuerbescheinigung'
    },
    'MELDEBESCHEINIGUNG': {
        'patterns': ['Meldebescheinigung'],
        'is_personnel': True,
        'category': '05.03',
        'description': 'SV-Meldebescheinigung (DEÜV)'
    },
    'ENTGELTBESCHEINIGUNG': {
        'patterns': ['Entgeltbescheinigung'],
        'is_personnel': True,
        'category': '07.01',
        'description': 'Entgeltbescheinigung'
    },
    'BEITRAGSNACHWEIS': {
        'patterns': ['Beitragsnachweis', 'Protokoll Beitragsnachweis'],
        'is_personnel': False,
        'category': '05.03',
        'description': 'Beitragsnachweis'
    },
    'LOHNSTEUERANMELDUNG': {
        'patterns': ['Lohnsteueranmeldung'],
        'is_personnel': False,
        'category': '05.02',
        'description': 'Lohnsteueranmeldung'
    },
    'FIBU': {
        'patterns': ['Fibu-Journal', 'Fibu-Buchungsjournal'],
        'is_personnel': False,
        'category': '05.04',
        'description': 'Fibu-Buchungen'
    },
    'LOHNJOURNAL': {
        'patterns': ['Lohnjournal', 'Jahreslohnjournal'],
        'is_personnel': False,
        'category': '05.01',
        'description': 'Lohnjournal'
    },
    'LOHNKONTO': {
        'patterns': ['Lohnkonto', 'Jahreslohnkonto', 'erweitertes Lohnkonto'],
        'is_personnel': True,
        'category': '05.01',
        'description': 'Lohnkonto'
    },
    'BERUFSGENOSSENSCHAFT': {
        'patterns': ['Berufsgenossenschaftsliste', 'Jahreslohnnachweis Berufsgenossenschaft'],
        'is_personnel': False,
        'category': '07.05',
        'description': 'Berufsgenossenschaft/Unfallmeldungen'
    },
    'ELSTAM': {
        'patterns': ['ELStAM'],
        'is_personnel': False,
        'category': '05.02',
        'description': 'ELStAM-Meldung'
    },
    'ERSTATTUNG': {
        'patterns': ['Erstattungsantrag'],
        'is_personnel': False,
        'category': '05.03',
        'description': 'Erstattungsantrag U1/U2'
    },
    'KUG': {
        'patterns': ['Saison-KUG', 'Saison-Kug'],
        'is_personnel': False,
        'category': '06.03',
        'description': 'Kurzarbeitergeld'
    },
    'STUNDENKALENDARIUM': {
        'patterns': ['Stundenkalendarium', 'Soll-Istprotokoll'],
        'is_personnel': False,
        'category': '06.01',
        'description': 'Arbeitszeitnachweise'
    },
    'ZVK': {
        'patterns': ['ZVK-LAK'],
        'is_personnel': False,
        'category': '05.05',
        'description': 'ZVK-Beitragsliste (Altersvorsorge)'
    },
    'DIFFERENZABRECHNUNG': {
        'patterns': ['Differenzabrechnung'],
        'is_personnel': False,
        'category': '05.01',
        'description': 'Differenzabrechnung'
    },
    'RESTURLAUB': {
        'patterns': ['Resturlaub'],
        'is_personnel': False,
        'category': '06.01',
        'description': 'Urlaubsübersicht'
    },
    'LST_JAHRESAUSGLEICH': {
        'patterns': ['LSt-Jahresausgleich'],
        'is_personnel': False,
        'category': '05.02',
        'description': 'Lohnsteuer-Jahresausgleich'
    },
    'BUCHUNGSSTAPEL': {
        'patterns': ['EXTF_Buchungsstapel', 'Buchungsstapel'],
        'is_personnel': False,
        'category': '05.04',
        'description': 'DATEV-Export'
    },
    'SAGE_EXPORT': {
        'patterns': ['E_Sage_'],
        'is_personnel': False,
        'category': '05.04',
        'description': 'Sage-Export'
    },
    'BEITRAGSSCHULD': {
        'patterns': ['Berechnung voraussichtliche Beitragsschuld', 'Beitragsschuld'],
        'is_personnel': False,
        'category': '05.03',
        'description': 'Beitragsschuld-Berechnung'
    },
    'BEITRAGSLISTE': {
        'patterns': ['Beitragsliste'],
        'is_personnel': False,
        'category': '05.03',
        'description': 'Beitragsliste'
    },
}


def classify_sage_document(filename):
    """
    Klassifiziert ein Sage-Dokument anhand des Dateinamens.
    Gibt (doc_type, is_personnel, category, description) zurück.
    """
    for doc_type, config in SAGE_DOCUMENT_TYPES.items():
        for pattern in config['patterns']:
            if pattern.lower() in filename.lower():
                return (
                    doc_type,
                    config['is_personnel'],
                    config['category'],
                    config['description']
                )
    return ('UNBEKANNT', False, None, 'Unbekanntes Dokument')


def get_or_create_document_type(doc_type_name, description, category_code, tenant=None):
    """
    Holt oder erstellt einen DocumentType basierend auf der Sage-Klassifizierung.
    Verknüpft automatisch mit der passenden FileCategory.
    """
    from dms.models import DocumentType, FileCategory
    
    doc_type_obj, created = DocumentType.objects.get_or_create(
        name=doc_type_name,
        tenant=tenant,
        defaults={
            'description': description or '',
            'is_active': True,
        }
    )
    
    if category_code and not doc_type_obj.file_category:
        try:
            file_category = FileCategory.objects.filter(
                code=category_code
            ).first()
            if not file_category:
                file_category = FileCategory.objects.filter(
                    code__startswith=category_code.split('.')[0]
                ).first()
            if file_category:
                doc_type_obj.file_category = file_category
                doc_type_obj.save(update_fields=['file_category'])
                logger.info(f"DocumentType '{doc_type_name}' mit FileCategory '{file_category.code}' verknüpft")
        except Exception as e:
            logger.warning(f"Konnte FileCategory für {category_code} nicht zuordnen: {e}")
    
    if created:
        logger.info(f"Neuer DocumentType erstellt: {doc_type_name}")
    
    return doc_type_obj


@shared_task(bind=True, max_retries=3)
def scan_sage_archive(self):
    """
    Scannt das Sage-Archiv und importiert Dokumente.
    
    SaaS-Modus: Verwendet Azure Blob Storage wenn konfiguriert.
    Fallback: Lokales Dateisystem (SAGE_ARCHIVE_PATH).
    
    Azure Blob Struktur: sage-archive/{tenant_code}/{YYYYMM}/{filename}
    Lokale Struktur: sage_archiv/{tenant_code}/{YYYYMM}/{filename}
    
    Personalunterlagen (Lohnscheine, etc.) werden via DataMatrix-Code getrennt.
    Firmendokumente (Beitragsnachweis, etc.) werden nach Dateiname klassifiziert.
    """
    with distributed_lock('sage_scanner', timeout=1800) as acquired:
        if not acquired:
            log_system_event('INFO', 'SageScanner', "Scan übersprungen - Redis-Lock aktiv")
            return {'status': 'skipped', 'message': 'Another scan is already running (Redis lock)'}
        
        # Check if Azure Blob Storage is configured
        from dms.models import SystemSettings
        settings_obj = SystemSettings.load()
        
        if settings_obj.azure_storage_connection_string_encrypted:
            log_system_event('INFO', 'SageScanner', "Verwende Azure Blob Storage")
            return _run_sage_scan_azure(self)
        else:
            log_system_event('INFO', 'SageScanner', "Verwende lokales Dateisystem")
            return _run_sage_scan(self)


def _run_sage_scan(task_self):
    """
    Optimierte Scan-Logik nach paperless-ngx Vorbild:
    - Chunked Hash-Berechnung (kein voller RAM-Load)
    - Pfad-basierte Deduplizierung
    - Parallele Verarbeitung mit ThreadPoolExecutor
    - Weniger DB-Roundtrips
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    
    scan_job = ScanJob.objects.create(
        source='SAGE',
        status='RUNNING',
        total_files=0
    )
    
    sage_path = Path(settings.SAGE_ARCHIVE_PATH)
    
    if not sage_path.exists():
        log_system_event('WARNING', 'SageScanner', f"Sage archive path does not exist: {sage_path}")
        scan_job.status = 'FAILED'
        scan_job.save(update_fields=['status'])
        return {'status': 'error', 'message': 'Path does not exist'}
    
    supported_extensions = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.jpg', '.jpeg', '.png', '.tiff', '.txt', '.csv'}
    skip_files = {'thumbs.db', 'desktop.ini', '.ds_store'}
    tenant_folder_pattern = re.compile(r'^\d{8}$')
    month_folder_pattern = re.compile(r'^\d{6}$')
    
    # Phase 1: Bekannte Pfade UND Hashes laden (schneller Lookup)
    log_system_event('INFO', 'SageScanner', "Lade bekannte Dateien aus Datenbank...")
    
    known_paths = set(ProcessedFile.objects.values_list('original_path', flat=True))
    known_hashes_by_tenant = {}
    tenant_cache = {}
    
    for tenant in Tenant.objects.filter(is_active=True):
        tenant_cache[tenant.code] = tenant
        known_hashes_by_tenant[tenant.code] = set(
            ProcessedFile.objects.filter(tenant=tenant).values_list('sha256_hash', flat=True)
        )
    
    # Phase 2: Dateien sammeln - NUR PFADE, kein Hash berechnen für bekannte Pfade!
    new_file_paths = []
    already_processed_count = 0
    
    scan_job.current_file = "Scanne Verzeichnis..."
    scan_job.save(update_fields=['current_file'])
    
    for tenant_folder in sage_path.iterdir():
        if not tenant_folder.is_dir() or not tenant_folder_pattern.match(tenant_folder.name):
            continue
        
        tenant_code = tenant_folder.name
        
        # Mandant erstellen falls nicht vorhanden
        if tenant_code not in tenant_cache:
            tenant, created = Tenant.objects.get_or_create(
                code=tenant_code,
                defaults={'name': f'Mandant {tenant_code}', 'is_active': True}
            )
            tenant_cache[tenant_code] = tenant
            known_hashes_by_tenant[tenant_code] = set()
            if created:
                log_system_event('INFO', 'SageScanner', f"Neuer Mandant erstellt: {tenant_code}")
        
        for file_path in tenant_folder.rglob('*'):
            if not file_path.is_file():
                continue
            if file_path.name.lower() in skip_files:
                continue
            if file_path.suffix.lower() not in supported_extensions:
                continue
            
            # OPTIMIZATION: Pfad-basierter Quick-Check - KEIN Hash für bekannte Pfade!
            path_str = str(file_path)
            if path_str in known_paths:
                already_processed_count += 1
            else:
                new_file_paths.append((file_path, tenant_code))
    
    scan_job.total_files = len(new_file_paths)
    scan_job.skipped_files = already_processed_count
    scan_job.save(update_fields=['total_files', 'skipped_files'])
    
    log_system_event('INFO', 'SageScanner', 
        f"Gefunden: {len(new_file_paths)} neue Dateien, {already_processed_count} bereits verarbeitet (Pfad-Check)")
    
    if not new_file_paths:
        scan_job.status = 'COMPLETED'
        scan_job.completed_at = timezone.now()
        scan_job.current_file = ''
        scan_job.save()
        return {'status': 'success', 'processed': 0, 'already_processed': already_processed_count}
    
    # Shared counters with thread-safe lock
    processed_count = 0
    error_count = 0
    personnel_docs = 0
    company_docs = 0
    counter_lock = threading.Lock()
    hashes_lock = threading.Lock()  # Lock für known_hashes Modifikation
    
    def process_single_file(file_info):
        """Verarbeitet eine einzelne Datei - thread-safe"""
        nonlocal processed_count, error_count, personnel_docs, company_docs, already_processed_count
        
        file_path, tenant_code = file_info
        tenant = tenant_cache[tenant_code]
        
        # SAAS FIX: Tenant-Kontext setzen, damit TenantAwareManager korrekt filtert
        with tenant_context(tenant):
            try:
                # OPTIMIZATION: Chunked Hash ohne volle Datei in RAM
                file_hash = calculate_sha256_chunked(str(file_path))
                
                # Thread-safe Hash-Check im Memory-Cache (keine verschachtelten Locks!)
                is_known = False
                with hashes_lock:
                    known_hashes = known_hashes_by_tenant.get(tenant_code, set())
                    is_known = file_hash in known_hashes
                
                if is_known:
                    with counter_lock:
                        already_processed_count += 1
                    return None
                
                # DB-Level Duplikat-Prüfung (race condition safety)
                if ProcessedFile.objects.filter(tenant=tenant, sha256_hash=file_hash).exists():
                    with counter_lock:
                        already_processed_count += 1
                    return None
                
                # Monatsordner extrahieren (vor Content-Laden für Split-Check)
                month_folder = None
                try:
                    tenant_folder = sage_path / tenant_code
                    relative_path = file_path.relative_to(tenant_folder)
                    path_parts = relative_path.parts
                    if len(path_parts) >= 2 and month_folder_pattern.match(path_parts[0]):
                        month_folder = path_parts[0]
                except ValueError:
                    pass
                
                mime_type = get_mime_type(str(file_path))
                
                employee = None
                status = 'UNASSIGNED'
                needs_review = False
                dm_result = None
                is_personnel = False
                doc_type = 'UNBEKANNT'
                category = None
                description = 'Unbekanntes Dokument'
                
                if file_path.suffix.lower() == '.pdf':
                    import fitz
                    try:
                        pdf_doc = fitz.open(str(file_path))
                        page_count = len(pdf_doc)
                        pdf_doc.close()
                    except:
                        page_count = 1
                    
                    if page_count > 1:
                        doc_type, is_personnel_type, _, _ = classify_sage_document(file_path.name)
                        if is_personnel_type:
                            split_output_dir = Path(settings.BASE_DIR) / 'data' / 'split_temp' / tenant_code
                            split_results = split_pdf_by_datamatrix(str(file_path), str(split_output_dir))
                            
                            if split_results and len(split_results) > 1:
                                log_system_event('INFO', 'SageScanner', 
                                    f"PDF aufgeteilt: {file_path.name} → {len(split_results)} Dokumente")
                                
                                split_docs_created = []
                                for split_info in split_results:
                                    split_path = Path(split_info['file_path'])
                                    emp_id = split_info['employee_id']
                                    mandant_code_dm = split_info.get('mandant_code')
                                    
                                    with open(split_path, 'rb') as sf:
                                        split_content = sf.read()
                                    split_encrypted = encrypt_data(split_content)
                                    split_hash = calculate_sha256_chunked(str(split_path))
                                    split_size = len(split_content)
                                    
                                    split_employee = find_employee_by_id(emp_id, tenant=tenant, mandant_code=mandant_code_dm)
                                    split_status = 'ASSIGNED' if split_employee else 'REVIEW_NEEDED'
                                    
                                    doc_type_split, _, category_split, desc_split = classify_sage_document(file_path.name)
                                    
                                    split_metadata = {
                                        'original_path': str(file_path),
                                        'split_from': file_path.name,
                                        'employee_id_from_datamatrix': emp_id,
                                        'pages_in_split': split_info['page_count'],
                                        'tenant_code': tenant_code,
                                        'doc_type': doc_type_split,
                                        'is_personnel_document': True,
                                        'month_folder': month_folder,
                                    }
                                    
                                    period_year, period_month = parse_month_folder(month_folder)
                                    split_doc = Document.objects.create(
                                        tenant=tenant,
                                        title=split_path.stem,
                                        original_filename=split_path.name,
                                        file_extension='.pdf',
                                        mime_type='application/pdf',
                                        encrypted_content=split_encrypted,
                                        file_size=split_size,
                                        employee=split_employee,
                                        status=split_status,
                                        source='SAGE',
                                        sha256_hash=split_hash,
                                        metadata=split_metadata,
                                        period_year=period_year,
                                        period_month=period_month
                                    )
                                    
                                    auto_classify_document(split_doc, tenant=tenant)
                                    
                                    if split_status == 'REVIEW_NEEDED':
                                        create_review_task(split_doc, source='SAGE_ARCHIVE')
                                    
                                    split_docs_created.append(str(split_doc.id))
                                    
                                    del split_content
                                    del split_encrypted
                                    
                                    try:
                                        split_path.unlink()
                                    except:
                                        pass
                                
                                ProcessedFile.objects.create(
                                    tenant=tenant,
                                    sha256_hash=file_hash,
                                    original_path=str(file_path),
                                    document=None
                                )
                                
                                with hashes_lock:
                                    if tenant_code not in known_hashes_by_tenant:
                                        known_hashes_by_tenant[tenant_code] = set()
                                    known_hashes_by_tenant[tenant_code].add(file_hash)
                                
                                with counter_lock:
                                    processed_count += len(split_results)
                                    personnel_docs += len(split_results)
                                
                                return {'success': True, 'split': True, 'split_count': len(split_results),
                                        'filename': file_path.name, 'doc_ids': split_docs_created, 'tenant': tenant_code}
                    
                    dm_result = extract_employee_from_datamatrix(str(file_path))
                    dm_mandant_code = dm_result.get('mandant_code')
                    
                    if dm_result['success'] and dm_result['employee_ids']:
                        is_personnel = True
                        for emp_id in dm_result['employee_ids']:
                            employee = find_employee_by_id(emp_id, tenant=tenant, mandant_code=dm_mandant_code)
                            if employee:
                                status = 'ASSIGNED'
                                break
                        
                        if not employee:
                            needs_review = True
                            status = 'REVIEW_NEEDED'
                        
                        doc_type, _, category, description = classify_sage_document(file_path.name)
                    elif dm_result['success'] and dm_result['codes']:
                        is_personnel = True
                        needs_review = True
                        status = 'REVIEW_NEEDED'
                        doc_type, _, category, description = classify_sage_document(file_path.name)
                    else:
                        doc_type, is_personnel, category, description = classify_sage_document(file_path.name)
                        if is_personnel:
                            needs_review = True
                            status = 'REVIEW_NEEDED'
                        else:
                            status = 'COMPANY'
                else:
                    doc_type, is_personnel, category, description = classify_sage_document(file_path.name)
                status = 'COMPANY' if not is_personnel else 'UNASSIGNED'
            
            # Content erst hier laden (nach Split-Check für Memory-Optimierung)
            with open(file_path, 'rb') as f:
                content = f.read()
            encrypted_content = encrypt_data(content)
            file_size = len(content)
            
            metadata = {
                'original_path': str(file_path),
                'needs_review': needs_review,
                'tenant_code': tenant_code,
                'doc_type': doc_type,
                'doc_type_description': description,
                'is_personnel_document': is_personnel,
                'category_code': category,
                'month_folder': month_folder,
            }
            
            if dm_result:
                metadata['datamatrix'] = {
                    'success': dm_result['success'],
                    'codes_found': len(dm_result['codes']),
                    'employee_ids': dm_result['employee_ids'],
                }
            
            # DocumentType aus Sage-Klassifizierung holen oder erstellen
            document_type_obj = None
            if doc_type and doc_type != 'UNBEKANNT':
                document_type_obj = get_or_create_document_type(doc_type, description, category, tenant)
            
            # DB-Operationen in einem Block
            period_year, period_month = parse_month_folder(month_folder)
            document = Document.objects.create(
                tenant=tenant,
                title=file_path.stem,
                original_filename=file_path.name,
                file_extension=file_path.suffix,
                mime_type=mime_type,
                encrypted_content=encrypted_content,
                file_size=file_size,
                employee=employee,
                document_type=document_type_obj,
                status=status,
                source='SAGE',
                sha256_hash=file_hash,
                metadata=metadata,
                period_year=period_year,
                period_month=period_month
            )
            
            ProcessedFile.objects.create(
                tenant=tenant,
                sha256_hash=file_hash,
                original_path=str(file_path),
                document=document
            )
            
            # Auto-Klassifizierung anhand Matching-Regeln
            auto_classify_document(document, tenant=tenant)
            
            # Aufgabe erstellen bei REVIEW_NEEDED
            if status == 'REVIEW_NEEDED':
                create_review_task(document, source='SAGE_ARCHIVE')
            
            # Speicher freigeben
            del content
            del encrypted_content
            
            # Hash zu known_hashes hinzufügen für Duplikat-Check (thread-safe)
            with hashes_lock:
                if tenant_code not in known_hashes_by_tenant:
                    known_hashes_by_tenant[tenant_code] = set()
                known_hashes_by_tenant[tenant_code].add(file_hash)
            
            with counter_lock:
                processed_count += 1
                if is_personnel:
                    personnel_docs += 1
                else:
                    company_docs += 1
            
                return {'success': True, 'is_personnel': is_personnel, 'needs_review': needs_review, 
                        'filename': file_path.name, 'doc_id': str(document.id), 'tenant': tenant_code}
                
            except Exception as e:
                with counter_lock:
                    error_count += 1
                logger.error(f"Fehler bei {file_path}: {e}")
                return {'success': False, 'error': str(e), 'filename': file_path.name}
    
    # Phase 3: Parallele Verarbeitung mit ThreadPoolExecutor
    # PAPERLESS-NGX Style: max 4 Workers, begrenzt durch CPU-Cores
    import os
    max_workers = min(4, max(1, os.cpu_count() or 2))
    
    log_system_event('INFO', 'SageScanner', f"Starte parallele Verarbeitung mit {max_workers} Threads")
    
    try:
        # Progress-Updates alle 10 Dateien statt bei jeder Datei
        update_interval = 10
        files_since_update = 0
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_single_file, f): f for f in new_file_paths}
            
            for future in as_completed(futures):
                result = future.result()
                files_since_update += 1
                
                # Fortschritt nur alle X Dateien aktualisieren (weniger DB-Writes)
                if files_since_update >= update_interval:
                    scan_job.processed_files = processed_count
                    scan_job.error_files = error_count
                    scan_job.skipped_files = already_processed_count
                    if result and result.get('filename'):
                        scan_job.current_file = result['filename'][:100]
                    scan_job.save(update_fields=['processed_files', 'error_files', 'skipped_files', 'current_file'])
                    files_since_update = 0
                
                # Logging für Review-Fälle
                if result and result.get('needs_review'):
                    log_system_event('WARNING', 'SageScanner', 
                        f"File requires review: {result['filename']}",
                        {'document_id': result.get('doc_id'), 'tenant': result.get('tenant')})
        
        scan_job.status = 'COMPLETED'
        scan_job.completed_at = timezone.now()
        scan_job.processed_files = processed_count
        scan_job.error_files = error_count
        scan_job.skipped_files = already_processed_count
        scan_job.current_file = ''
        scan_job.save()
        
        log_system_event('INFO', 'SageScanner', 
            f"Scan abgeschlossen: {processed_count} neu verarbeitet, "
            f"{already_processed_count} bereits vorhanden, {error_count} Fehler")
        
        return {
            'status': 'success',
            'processed': processed_count,
            'personnel_documents': personnel_docs,
            'company_documents': company_docs,
            'already_processed': already_processed_count,
            'errors': error_count
        }
        
    except Exception as e:
        scan_job.status = 'FAILED'
        scan_job.error_message = str(e)
        scan_job.completed_at = timezone.now()
        scan_job.save()
        log_system_event('CRITICAL', 'SageScanner', f"Sage scan failed: {str(e)}")
        raise task_self.retry(exc=e, countdown=60)


# NOTE: scan_manual_input task removed - SaaS uses API ingest instead of local file scanning


def _run_sage_scan_azure(task_self):
    """
    Azure Blob Storage version of Sage archive scan.
    
    Reads documents from Azure Blob Storage container with structure:
    sage-archive/{tenant_code}/{YYYYMM}/{filename}
    
    Downloads each blob to temp file for processing, then cleans up.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    import os as os_module
    import tempfile
    
    from dms.azure_storage import (
        list_sage_archive_blobs, 
        download_blob_to_tempfile, 
        parse_sage_blob_path
    )
    
    scan_job = ScanJob.objects.create(
        source='SAGE',
        status='RUNNING',
        total_files=0
    )
    
    # Phase 1: List all blobs in sage-archive/
    log_system_event('INFO', 'SageScanner', "Liste Azure Blobs in sage-archive/...")
    
    all_blobs = []
    try:
        for blob_name, blob_size in list_sage_archive_blobs():
            all_blobs.append((blob_name, blob_size))
    except Exception as e:
        log_system_event('ERROR', 'SageScanner', f"Fehler beim Lesen von Azure Blob Storage: {e}")
        scan_job.status = 'FAILED'
        scan_job.error_message = str(e)
        scan_job.save()
        return {'status': 'error', 'message': str(e)}
    
    if not all_blobs:
        log_system_event('INFO', 'SageScanner', "Keine Dateien in sage-archive/ gefunden")
        scan_job.status = 'COMPLETED'
        scan_job.completed_at = timezone.now()
        scan_job.save()
        return {'status': 'success', 'processed': 0, 'message': 'No blobs found'}
    
    log_system_event('INFO', 'SageScanner', f"Gefunden: {len(all_blobs)} Blobs in Azure")
    
    supported_extensions = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.jpg', '.jpeg', '.png', '.tiff', '.txt', '.csv'}
    skip_files = {'thumbs.db', 'desktop.ini', '.ds_store'}
    tenant_folder_pattern = re.compile(r'^\d{8}$')
    month_folder_pattern = re.compile(r'^\d{6}$')
    
    # Phase 2: Load known paths and hashes
    known_paths = set(ProcessedFile.objects.values_list('original_path', flat=True))
    known_hashes_by_tenant = {}
    tenant_cache = {}
    
    for tenant in Tenant.objects.filter(is_active=True):
        if tenant.code:
            tenant_cache[tenant.code] = tenant
            known_hashes_by_tenant[tenant.code] = set(
                ProcessedFile.objects.filter(tenant=tenant).values_list('sha256_hash', flat=True)
            )
    
    # Filter and prepare blobs for processing
    new_blobs = []
    already_processed_count = 0
    
    for blob_name, blob_size in all_blobs:
        tenant_code, month_folder, filename = parse_sage_blob_path(blob_name)
        
        if not tenant_code or not filename:
            continue
        
        if not tenant_folder_pattern.match(tenant_code):
            continue
        
        if filename.lower() in skip_files:
            continue
        
        suffix = Path(filename).suffix.lower()
        if suffix not in supported_extensions:
            continue
        
        # Path-based quick check
        if blob_name in known_paths:
            already_processed_count += 1
            continue
        
        # Create tenant if not exists
        if tenant_code not in tenant_cache:
            tenant, created = Tenant.objects.get_or_create(
                code=tenant_code,
                defaults={'name': f'Mandant {tenant_code}', 'is_active': True}
            )
            tenant_cache[tenant_code] = tenant
            known_hashes_by_tenant[tenant_code] = set()
            if created:
                log_system_event('INFO', 'SageScanner', f"Neuer Mandant erstellt: {tenant_code}")
        
        new_blobs.append((blob_name, blob_size, tenant_code, month_folder, filename))
    
    scan_job.total_files = len(new_blobs)
    scan_job.skipped_files = already_processed_count
    scan_job.save(update_fields=['total_files', 'skipped_files'])
    
    log_system_event('INFO', 'SageScanner', 
        f"Zu verarbeiten: {len(new_blobs)} neue Blobs, {already_processed_count} bereits vorhanden")
    
    if not new_blobs:
        scan_job.status = 'COMPLETED'
        scan_job.completed_at = timezone.now()
        scan_job.save()
        return {'status': 'success', 'processed': 0, 'already_processed': already_processed_count}
    
    # Shared counters
    processed_count = 0
    error_count = 0
    personnel_docs = 0
    company_docs = 0
    counter_lock = threading.Lock()
    hashes_lock = threading.Lock()
    
    def process_azure_blob(blob_info):
        """Process a single blob from Azure."""
        nonlocal processed_count, error_count, personnel_docs, company_docs, already_processed_count
        
        blob_name, blob_size, tenant_code, month_folder, filename = blob_info
        tenant = tenant_cache[tenant_code]
        temp_file = None
        
        with tenant_context(tenant):
            try:
                # Download blob to temp file
                suffix = Path(filename).suffix
                temp_file = download_blob_to_tempfile(blob_name, suffix=suffix)
                
                if not temp_file:
                    with counter_lock:
                        error_count += 1
                    return {'success': False, 'error': 'Download failed', 'filename': filename}
                
                file_path = Path(temp_file)
                
                # Calculate hash
                file_hash = calculate_sha256_chunked(str(file_path))
                
                # Thread-safe hash check
                is_known = False
                with hashes_lock:
                    known_hashes = known_hashes_by_tenant.get(tenant_code, set())
                    is_known = file_hash in known_hashes
                
                if is_known:
                    with counter_lock:
                        already_processed_count += 1
                    return None
                
                # DB-level duplicate check
                if ProcessedFile.objects.filter(tenant=tenant, sha256_hash=file_hash).exists():
                    with counter_lock:
                        already_processed_count += 1
                    return None
                
                mime_type = get_mime_type(str(file_path))
                
                # Document classification
                employee = None
                status = 'UNASSIGNED'
                needs_review = False
                is_personnel = False
                doc_type = 'UNBEKANNT'
                category = None
                description = 'Unbekanntes Dokument'
                dm_result = None
                
                if suffix.lower() == '.pdf':
                    dm_result = extract_employee_from_datamatrix(str(file_path))
                    dm_mandant_code = dm_result.get('mandant_code')
                    
                    if dm_result['success'] and dm_result['employee_ids']:
                        is_personnel = True
                        for emp_id in dm_result['employee_ids']:
                            employee = find_employee_by_id(emp_id, tenant=tenant, mandant_code=dm_mandant_code)
                            if employee:
                                status = 'ASSIGNED'
                                break
                        
                        if not employee:
                            needs_review = True
                            status = 'REVIEW_NEEDED'
                        
                        doc_type, _, category, description = classify_sage_document(filename)
                    elif dm_result['success'] and dm_result['codes']:
                        is_personnel = True
                        needs_review = True
                        status = 'REVIEW_NEEDED'
                        doc_type, _, category, description = classify_sage_document(filename)
                    else:
                        doc_type, is_personnel, category, description = classify_sage_document(filename)
                        if is_personnel:
                            needs_review = True
                            status = 'REVIEW_NEEDED'
                        else:
                            status = 'COMPANY'
                else:
                    doc_type, is_personnel, category, description = classify_sage_document(filename)
                    status = 'COMPANY' if not is_personnel else 'UNASSIGNED'
                
                # Read and encrypt content
                with open(file_path, 'rb') as f:
                    content = f.read()
                encrypted_content = encrypt_data(content)
                file_size = len(content)
                
                metadata = {
                    'original_path': blob_name,
                    'azure_blob': True,
                    'needs_review': needs_review,
                    'tenant_code': tenant_code,
                    'doc_type': doc_type,
                    'doc_type_description': description,
                    'is_personnel_document': is_personnel,
                    'category_code': category,
                    'month_folder': month_folder,
                }
                
                if dm_result:
                    metadata['datamatrix'] = {
                        'success': dm_result['success'],
                        'codes_found': len(dm_result['codes']),
                        'employee_ids': dm_result['employee_ids'],
                    }
                
                document_type_obj = None
                if doc_type and doc_type != 'UNBEKANNT':
                    document_type_obj = get_or_create_document_type(doc_type, description, category, tenant)
                
                period_year, period_month = parse_month_folder(month_folder)
                document = Document.objects.create(
                    tenant=tenant,
                    title=Path(filename).stem,
                    original_filename=filename,
                    file_extension=suffix,
                    mime_type=mime_type,
                    encrypted_content=encrypted_content,
                    file_size=file_size,
                    employee=employee,
                    document_type=document_type_obj,
                    status=status,
                    source='SAGE',
                    sha256_hash=file_hash,
                    metadata=metadata,
                    period_year=period_year,
                    period_month=period_month
                )
                
                ProcessedFile.objects.create(
                    tenant=tenant,
                    sha256_hash=file_hash,
                    original_path=blob_name,
                    document=document
                )
                
                auto_classify_document(document, tenant=tenant)
                
                if status == 'REVIEW_NEEDED':
                    create_review_task(document, source='SAGE_ARCHIVE')
                
                del content
                del encrypted_content
                
                with hashes_lock:
                    if tenant_code not in known_hashes_by_tenant:
                        known_hashes_by_tenant[tenant_code] = set()
                    known_hashes_by_tenant[tenant_code].add(file_hash)
                
                with counter_lock:
                    processed_count += 1
                    if is_personnel:
                        personnel_docs += 1
                    else:
                        company_docs += 1
                
                return {'success': True, 'is_personnel': is_personnel, 'needs_review': needs_review,
                        'filename': filename, 'doc_id': str(document.id), 'tenant': tenant_code}
                
            except Exception as e:
                with counter_lock:
                    error_count += 1
                logger.error(f"Fehler bei Azure Blob {blob_name}: {e}")
                return {'success': False, 'error': str(e), 'filename': filename}
            finally:
                # Clean up temp file
                if temp_file and os_module.path.exists(temp_file):
                    try:
                        os_module.unlink(temp_file)
                    except:
                        pass
    
    # Phase 3: Parallel processing
    max_workers = min(4, max(1, os_module.cpu_count() or 2))
    log_system_event('INFO', 'SageScanner', f"Starte Azure-Verarbeitung mit {max_workers} Threads")
    
    try:
        update_interval = 10
        files_since_update = 0
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_azure_blob, b): b for b in new_blobs}
            
            for future in as_completed(futures):
                result = future.result()
                files_since_update += 1
                
                if files_since_update >= update_interval:
                    scan_job.processed_files = processed_count
                    scan_job.error_files = error_count
                    scan_job.skipped_files = already_processed_count
                    if result and result.get('filename'):
                        scan_job.current_file = result['filename'][:100]
                    scan_job.save(update_fields=['processed_files', 'error_files', 'skipped_files', 'current_file'])
                    files_since_update = 0
                
                if result and result.get('needs_review'):
                    log_system_event('WARNING', 'SageScanner',
                        f"File requires review: {result['filename']}",
                        {'document_id': result.get('doc_id'), 'tenant': result.get('tenant')})
        
        scan_job.status = 'COMPLETED'
        scan_job.completed_at = timezone.now()
        scan_job.processed_files = processed_count
        scan_job.error_files = error_count
        scan_job.skipped_files = already_processed_count
        scan_job.current_file = ''
        scan_job.save()
        
        log_system_event('INFO', 'SageScanner',
            f"Azure Scan abgeschlossen: {processed_count} neu verarbeitet, "
            f"{already_processed_count} bereits vorhanden, {error_count} Fehler")
        
        return {
            'status': 'success',
            'source': 'azure',
            'processed': processed_count,
            'personnel_documents': personnel_docs,
            'company_documents': company_docs,
            'already_processed': already_processed_count,
            'errors': error_count
        }
        
    except Exception as e:
        scan_job.status = 'FAILED'
        scan_job.error_message = str(e)
        scan_job.completed_at = timezone.now()
        scan_job.save()
        log_system_event('CRITICAL', 'SageScanner', f"Azure Sage scan failed: {str(e)}")
        raise task_self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=3)
def poll_central_inbox_graph(self):
    """
    Zentraler E-Mail-Ingest über Microsoft Graph API (Client Credentials Flow).
    
    Verwendet ein zentrales Postfach (z.B. ingest@dms.cloud) und routet E-Mails
    basierend auf dem Token in der Empfängeradresse (upload.<token>@dms.cloud).
    
    Konfiguration über Umgebungsvariablen:
    - AZURE_INGEST_CLIENT_ID
    - AZURE_INGEST_CLIENT_SECRET  
    - AZURE_INGEST_TENANT_ID
    - AZURE_INGEST_MAILBOX
    """
    from O365 import Account
    
    client_id = settings.AZURE_INGEST_CLIENT_ID
    client_secret = settings.AZURE_INGEST_CLIENT_SECRET
    azure_tenant_id = settings.AZURE_INGEST_TENANT_ID
    mailbox = settings.AZURE_INGEST_MAILBOX
    
    if not all([client_id, client_secret, azure_tenant_id, mailbox]):
        log_system_event('ERROR', 'CentralIngest', 
            'Azure Ingest-Konfiguration unvollständig. Prüfen Sie AZURE_INGEST_* Umgebungsvariablen.',
            {'missing': [k for k, v in {
                'AZURE_INGEST_CLIENT_ID': client_id,
                'AZURE_INGEST_CLIENT_SECRET': client_secret,
                'AZURE_INGEST_TENANT_ID': azure_tenant_id,
                'AZURE_INGEST_MAILBOX': mailbox
            }.items() if not v]})
        return {'status': 'error', 'message': 'Missing Azure configuration'}
    
    try:
        credentials = (client_id, client_secret)
        account = Account(
            credentials,
            tenant_id=azure_tenant_id,
            auth_flow_type='credentials'
        )
        
        if not account.authenticate():
            log_system_event('ERROR', 'CentralIngest', 
                'Azure Service Principal Authentifizierung fehlgeschlagen.')
            return {'status': 'error', 'message': 'Authentication failed'}
        
        mailbox_obj = account.mailbox(resource=mailbox)
        inbox = mailbox_obj.inbox_folder()
        
        quarantine_folder = None
        try:
            quarantine_folder = mailbox_obj.get_folder(folder_name='Quarantine')
        except Exception:
            try:
                quarantine_folder = mailbox_obj.create_child_folder('Quarantine')
                log_system_event('INFO', 'CentralIngest', 'Quarantine-Ordner erstellt.')
            except Exception as e:
                log_system_event('WARNING', 'CentralIngest', 
                    f'Konnte Quarantine-Ordner nicht erstellen: {str(e)}')
        
        query = inbox.new_query().on_attribute('isRead').equals(False)
        messages = inbox.get_messages(query=query, limit=50)
        
        processed = 0
        quarantined = 0
        
        for message in messages:
            try:
                tenant = extract_tenant_from_recipients(message)
                
                if tenant:
                    with tenant_context(tenant):
                        process_email_message(message, tenant)
                        message.mark_as_read()
                        message.delete()
                        processed += 1
                        
                        log_system_event('INFO', 'CentralIngest', 
                            f'E-Mail verarbeitet für Mandant {tenant.code}: {message.subject}')
                else:
                    if quarantine_folder:
                        message.move(quarantine_folder)
                    message.mark_as_read()
                    quarantined += 1
                    
                    log_system_event('WARNING', 'CentralIngest', 
                        f'Kein gültiges Tenant-Token gefunden, E-Mail in Quarantäne: {message.subject}',
                        {'recipients': [r.address for r in message.to + message.cc]})
                        
            except Exception as e:
                log_system_event('ERROR', 'CentralIngest', 
                    f'Fehler bei E-Mail-Verarbeitung: {message.subject}',
                    {'error': str(e)})
                if quarantine_folder:
                    try:
                        message.move(quarantine_folder)
                        message.mark_as_read()
                    except Exception:
                        pass
                quarantined += 1
        
        log_system_event('INFO', 'CentralIngest', 
            f'E-Mail-Ingest abgeschlossen: {processed} verarbeitet, {quarantined} in Quarantäne')
        
        return {'status': 'success', 'processed': processed, 'quarantined': quarantined}
        
    except Exception as e:
        log_system_event('ERROR', 'CentralIngest', 
            f'Zentraler E-Mail-Ingest fehlgeschlagen: {str(e)}',
            {'error': str(e)})
        return {'status': 'error', 'message': str(e)}


@shared_task(bind=True, max_retries=3)
def poll_email_inbox(self):
    """
    Kompatibilitäts-Wrapper für bestehende Celery Beat Schedules.
    Ruft poll_central_inbox_graph auf.
    
    DEPRECATED: Bitte Celery Beat Schedule auf poll_central_inbox_graph umstellen.
    """
    log_system_event('INFO', 'CentralIngest', 
        'poll_email_inbox aufgerufen (deprecated), leite an poll_central_inbox_graph weiter.')
    return poll_central_inbox_graph()


def extract_tenant_from_recipients(message):
    """
    Extrahiert den Tenant anhand des Tokens in der Empfängeradresse.
    
    Sucht nach dem Pattern: upload.<token>@...
    Prüft alle to_recipients und cc_recipients.
    
    Returns:
        Tenant-Objekt oder None wenn kein gültiges Token gefunden.
    """
    token_pattern = re.compile(r'upload\.([a-f0-9-]+)@', re.IGNORECASE)
    
    all_recipients = list(message.to or []) + list(message.cc or [])
    
    for recipient in all_recipients:
        email_address = recipient.address if hasattr(recipient, 'address') else str(recipient)
        match = token_pattern.search(email_address)
        
        if match:
            token = match.group(1)
            try:
                tenant = Tenant.objects.get(ingest_token=token, is_active=True)
                return tenant
            except Tenant.DoesNotExist:
                log_system_event('WARNING', 'CentralIngest', 
                    f'Unbekanntes Ingest-Token: {token}',
                    {'email': email_address})
                continue
    
    return None


def process_email_message(message, tenant):
    """
    Verarbeitet eine einzelne E-Mail und erstellt Dokumente für den Mandanten.
    
    Args:
        message: O365 Message-Objekt
        tenant: Tenant-Objekt für die Zuordnung
    """
    import pdfkit
    import bleach
    from django.utils.html import escape
    
    email_archive_path = Path(settings.EMAIL_ARCHIVE_PATH)
    email_archive_path.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    subject_safe = "".join(c for c in message.subject if c.isalnum() or c in (' ', '-', '_'))[:50]
    
    recipients = ', '.join([r.address for r in (message.to or [])])
    
    safe_body = escape(message.body or '')
    
    eml_content = f"""From: {message.sender.address}
To: {recipients}
Subject: {message.subject}
Date: {message.received}

{safe_body}
"""
    
    eml_encrypted = encrypt_data(eml_content.encode('utf-8'))
    eml_hash = calculate_sha256(eml_content.encode('utf-8'))
    
    eml_doc = Document.objects.create(
        tenant=tenant,
        title=f"Email: {message.subject}",
        original_filename=f"{timestamp}_{subject_safe}.eml",
        file_extension='.eml',
        mime_type='message/rfc822',
        encrypted_content=eml_encrypted,
        file_size=len(eml_content),
        status='UNASSIGNED',
        source='EMAIL',
        sha256_hash=eml_hash,
        metadata={
            'sender': message.sender.address,
            'received': str(message.received),
            'has_attachments': message.has_attachments,
            'tenant_code': tenant.code
        }
    )
    
    try:
        # SECURITY FIX: HTML-Input sanitisieren um SSRF/LFI/XSS zu verhindern
        # Nur sichere Tags erlauben, keine iframes, scripts, object, embed etc.
        allowed_tags = ['b', 'i', 'u', 'p', 'br', 'strong', 'em', 'h1', 'h2', 'h3', 
                        'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'a', 'blockquote', 'pre', 
                        'code', 'table', 'thead', 'tbody', 'tr', 'td', 'th', 'hr', 'div', 'span']
        allowed_attrs = {
            'a': ['href', 'title'],
            'td': ['colspan', 'rowspan'],
            'th': ['colspan', 'rowspan'],
        }
        
        # Entferne potentiell gefährliche HTML-Elemente
        clean_body = bleach.clean(
            message.body or '', 
            tags=allowed_tags, 
            attributes=allowed_attrs,
            strip=True
        )
        
        # Escape kritische Felder
        safe_subject = escape(message.subject)
        safe_sender = escape(message.sender.address)
        safe_received = escape(str(message.received))
        
        html_content = f"""
        <html>
        <head><style>body {{ font-family: Arial, sans-serif; }}</style></head>
        <body>
        <h2>{safe_subject}</h2>
        <p><strong>From:</strong> {safe_sender}</p>
        <p><strong>Date:</strong> {safe_received}</p>
        <hr>
        {clean_body or 'Kein Inhalt'}
        </body>
        </html>
        """
        
        # SECURITY FIX: wkhtmltopdf Optionen härten gegen LFI und SSRF
        pdfkit_options = {
            'disable-local-file-access': None,
            'disable-javascript': None,
            'no-images': None,
            'disable-external-links': None,
            'quiet': None,
        }
        
        pdf_content = pdfkit.from_string(html_content, False, options=pdfkit_options)
        pdf_encrypted = encrypt_data(pdf_content)
        pdf_hash = calculate_sha256(pdf_content)
        
        Document.objects.create(
            tenant=tenant,
            title=f"Email PDF: {message.subject}",
            original_filename=f"{timestamp}_{subject_safe}.pdf",
            file_extension='.pdf',
            mime_type='application/pdf',
            encrypted_content=pdf_encrypted,
            file_size=len(pdf_content),
            status='UNASSIGNED',
            source='EMAIL',
            sha256_hash=pdf_hash,
            metadata={'parent_email_id': str(eml_doc.id), 'tenant_code': tenant.code}
        )
    except Exception as e:
        log_system_event('WARNING', 'CentralIngest', 
            f"PDF-Konvertierung fehlgeschlagen: {message.subject}",
            {'error': str(e)})
    
    if message.has_attachments:
        for attachment in message.attachments:
            try:
                att_content = attachment.content
                att_encrypted = encrypt_data(att_content)
                att_hash = calculate_sha256(att_content)
                
                Document.objects.create(
                    tenant=tenant,
                    title=f"Attachment: {attachment.name}",
                    original_filename=attachment.name,
                    file_extension=Path(attachment.name).suffix,
                    mime_type=attachment.content_type or 'application/octet-stream',
                    encrypted_content=att_encrypted,
                    file_size=len(att_content),
                    status='UNASSIGNED',
                    source='EMAIL',
                    sha256_hash=att_hash,
                    metadata={'parent_email_id': str(eml_doc.id), 'tenant_code': tenant.code}
                )
            except Exception as e:
                log_system_event('WARNING', 'CentralIngest', 
                    f"Anhang-Verarbeitung fehlgeschlagen: {attachment.name}",
                    {'error': str(e)})
    
    create_review_task(eml_doc, source='EMAIL')
    
    log_system_event('INFO', 'CentralIngest', 
        f"E-Mail verarbeitet: {message.subject}",
        {'document_id': str(eml_doc.id), 'tenant': tenant.code})


@shared_task(bind=True, max_retries=3)
def sync_sage_cloud_employees(self):
    """Sync employees from Sage Cloud and create personnel files"""
    from .connectors.sage_cloud import SageCloudConnector
    
    try:
        connector = SageCloudConnector()
        if connector.connect():
            stats = connector.sync_employees()
            log_system_event('INFO', 'SageCloudSync', 
                'Mitarbeiter-Synchronisation abgeschlossen', stats)
            return {'status': 'success', **stats}
        else:
            log_system_event('WARNING', 'SageCloudSync', 
                'Verbindung zu Sage Cloud nicht möglich')
            return {'status': 'connection_failed'}
    except Exception as e:
        log_system_event('ERROR', 'SageCloudSync', 
            f'Sage Cloud Sync fehlgeschlagen: {str(e)}')
        raise self.retry(exc=e, countdown=300)


@shared_task(bind=True, max_retries=3)
def import_sage_cloud_leave_requests(self):
    """Import approved leave requests from Sage Cloud"""
    from .connectors.sage_cloud import SageCloudConnector
    from datetime import timedelta
    
    try:
        connector = SageCloudConnector()
        since_date = (timezone.now() - timedelta(days=30)).date()
        stats = connector.import_leave_requests(since_date)
        log_system_event('INFO', 'SageCloudImport', 
            'Urlaubsanträge-Import abgeschlossen', stats)
        return {'status': 'success', **stats}
    except Exception as e:
        log_system_event('ERROR', 'SageCloudImport', 
            f'Urlaubsanträge-Import fehlgeschlagen: {str(e)}')
        raise self.retry(exc=e, countdown=300)


@shared_task(bind=True, max_retries=3)
def import_sage_cloud_timesheets(self, year: int = None, month: int = None):
    """Import monthly timesheets from Sage Cloud"""
    from .connectors.sage_cloud import SageCloudConnector
    
    if year is None or month is None:
        now = timezone.now()
        if now.month == 1:
            year = now.year - 1
            month = 12
        else:
            year = now.year
            month = now.month - 1
    
    try:
        connector = SageCloudConnector()
        stats = connector.import_timesheets(year, month)
        log_system_event('INFO', 'SageCloudImport', 
            f'Zeiterfassungs-Import für {month:02d}/{year} abgeschlossen', stats)
        return {'status': 'success', 'year': year, 'month': month, **stats}
    except Exception as e:
        log_system_event('ERROR', 'SageCloudImport', 
            f'Zeiterfassungs-Import fehlgeschlagen: {str(e)}')
        raise self.retry(exc=e, countdown=300)
