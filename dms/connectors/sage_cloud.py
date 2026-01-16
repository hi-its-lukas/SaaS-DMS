"""
Sage Cloud REST API Connector
Connects to Sage HR Cloud for leave requests and timesheets
"""
import logging
from typing import Optional, List, Dict, Any
from datetime import date, datetime, timedelta
from decimal import Decimal
import requests
from requests.exceptions import RequestException, Timeout

from ..models import (
    SystemSettings, Employee, ImportedLeaveRequest, 
    ImportedTimesheet, SystemLog
)
from ..encryption import decrypt_data

logger = logging.getLogger(__name__)


class SageCloudConnector:
    """REST API client for Sage Cloud"""
    
    def __init__(self):
        self.settings = SystemSettings.load()
        self.session: Optional[requests.Session] = None
        self._authenticated = False
    
    def _log(self, level: str, message: str, details: dict = None):
        """Log to both logger and database"""
        getattr(logger, level.lower())(message)
        SystemLog.objects.create(
            level=level.upper(),
            source='SageCloudConnector',
            message=message,
            details=details or {}
        )
    
    def _get_api_key(self) -> Optional[str]:
        """Decrypt and return the API key"""
        if not self.settings.encrypted_sage_cloud_api_key:
            return None
        try:
            return decrypt_data(bytes(self.settings.encrypted_sage_cloud_api_key)).decode()
        except Exception:
            return None
    
    def connect(self) -> bool:
        """Initialize authenticated session"""
        if not self.settings.sage_cloud_api_url:
            self._log('WARNING', 'Sage Cloud API URL nicht konfiguriert')
            return False
        
        api_key = self._get_api_key()
        if not api_key:
            self._log('WARNING', 'Sage Cloud API-Schlüssel nicht konfiguriert')
            return False
        
        try:
            self.session = requests.Session()
            self.session.headers.update({
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            })
            
            response = self.session.get(
                f"{self.settings.sage_cloud_api_url.rstrip('/')}/health",
                timeout=10
            )
            
            if response.status_code in [200, 401, 403, 404]:
                self._authenticated = True
                self._log('INFO', 'Verbindung zu Sage Cloud hergestellt')
                return True
            else:
                self._log('ERROR', f'Sage Cloud Verbindung fehlgeschlagen: HTTP {response.status_code}')
                return False
                
        except Timeout:
            self._log('ERROR', 'Timeout bei Verbindung zu Sage Cloud')
            return False
        except RequestException as e:
            self._log('ERROR', f'Verbindungsfehler zu Sage Cloud: {str(e)}')
            return False
    
    def is_connected(self) -> bool:
        return self._authenticated and self.session is not None
    
    def _api_request(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """Make authenticated API request"""
        if not self.is_connected():
            if not self.connect():
                return None
        
        try:
            url = f"{self.settings.sage_cloud_api_url.rstrip('/')}/{endpoint.lstrip('/')}"
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self._log('ERROR', f'API-Anfrage fehlgeschlagen: {endpoint}', {'error': str(e)})
            return None
    
    def fetch_leave_requests(self, since_date: date = None) -> List[Dict[str, Any]]:
        """Fetch approved leave requests from Sage Cloud"""
        params = {'status': 'approved'}
        if since_date:
            params['from_date'] = since_date.isoformat()
        
        data = self._api_request('/leave-management/requests', params)
        if not data:
            return []
        
        requests_list = data.get('data', data) if isinstance(data, dict) else data
        
        leave_requests = []
        for req in requests_list:
            leave_requests.append({
                'sage_request_id': str(req.get('id', '')),
                'employee_id': str(req.get('employee_id', '')),
                'sage_cloud_id': str(req.get('employee_id', '')),
                'leave_type': req.get('type', req.get('leave_type', 'Urlaub')),
                'start_date': req.get('start_date', req.get('from_date')),
                'end_date': req.get('end_date', req.get('to_date')),
                'days_count': req.get('days', req.get('duration', 1)),
                'approval_date': req.get('approved_at', req.get('approval_date')),
                'approved_by': req.get('approved_by', req.get('approver_name', '')),
                'raw_data': req
            })
        
        self._log('INFO', f'{len(leave_requests)} Urlaubsanträge abgerufen')
        return leave_requests
    
    def import_leave_requests(self, since_date: date = None) -> Dict[str, int]:
        """Import new leave requests and trigger PDF generation"""
        from ..generators.pdf_generator import PDFGenerator
        
        requests_data = self.fetch_leave_requests(since_date)
        stats = {'imported': 0, 'skipped': 0, 'errors': 0}
        
        for req_data in requests_data:
            sage_id = req_data['sage_request_id']
            
            if ImportedLeaveRequest.objects.filter(sage_request_id=sage_id).exists():
                stats['skipped'] += 1
                continue
            
            try:
                employee = Employee.objects.filter(
                    sage_cloud_id=req_data['sage_cloud_id']
                ).first()
                
                if not employee:
                    employee = Employee.objects.filter(
                        employee_id=req_data['employee_id']
                    ).first()
                
                if not employee:
                    self._log('WARNING', f'Mitarbeiter nicht gefunden für Urlaubsantrag {sage_id}',
                             {'employee_id': req_data['employee_id']})
                    stats['errors'] += 1
                    continue
                
                start_date = req_data['start_date']
                if isinstance(start_date, str):
                    start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00')).date()
                
                end_date = req_data['end_date']
                if isinstance(end_date, str):
                    end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00')).date()
                
                approval_date = req_data.get('approval_date')
                if approval_date and isinstance(approval_date, str):
                    approval_date = datetime.fromisoformat(approval_date.replace('Z', '+00:00')).date()
                
                leave_request = ImportedLeaveRequest.objects.create(
                    sage_request_id=sage_id,
                    employee=employee,
                    leave_type=req_data['leave_type'],
                    start_date=start_date,
                    end_date=end_date,
                    days_count=Decimal(str(req_data['days_count'])),
                    approval_date=approval_date,
                    approved_by=req_data.get('approved_by', ''),
                    raw_data=req_data['raw_data']
                )
                
                generator = PDFGenerator()
                document = generator.generate_leave_request_pdf(leave_request)
                if document:
                    leave_request.document = document
                    leave_request.save()
                
                stats['imported'] += 1
                
            except Exception as e:
                stats['errors'] += 1
                self._log('ERROR', f'Fehler beim Import von Urlaubsantrag {sage_id}: {str(e)}')
        
        self._log('INFO', 'Urlaubsanträge-Import abgeschlossen', stats)
        return stats
    
    def fetch_timesheets(self, year: int, month: int) -> List[Dict[str, Any]]:
        """Fetch monthly timesheet data"""
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)
        
        params = {
            'from_date': start_date.isoformat(),
            'to_date': end_date.isoformat()
        }
        
        data = self._api_request('/timesheets', params)
        if not data:
            return []
        
        timesheets_list = data.get('data', data) if isinstance(data, dict) else data
        
        timesheets = []
        for ts in timesheets_list:
            timesheets.append({
                'employee_id': str(ts.get('employee_id', '')),
                'sage_cloud_id': str(ts.get('employee_id', '')),
                'total_hours': ts.get('total_hours', 0),
                'overtime_hours': ts.get('overtime', ts.get('overtime_hours', 0)),
                'entries': ts.get('entries', []),
                'raw_data': ts
            })
        
        self._log('INFO', f'{len(timesheets)} Zeiterfassungen für {month:02d}/{year} abgerufen')
        return timesheets
    
    def import_timesheets(self, year: int, month: int) -> Dict[str, int]:
        """Import monthly timesheets and generate PDF reports"""
        from ..generators.pdf_generator import PDFGenerator
        
        timesheets_data = self.fetch_timesheets(year, month)
        stats = {'imported': 0, 'skipped': 0, 'errors': 0}
        
        for ts_data in timesheets_data:
            try:
                employee = Employee.objects.filter(
                    sage_cloud_id=ts_data['sage_cloud_id']
                ).first()
                
                if not employee:
                    employee = Employee.objects.filter(
                        employee_id=ts_data['employee_id']
                    ).first()
                
                if not employee:
                    self._log('WARNING', f'Mitarbeiter nicht gefunden für Zeiterfassung',
                             {'employee_id': ts_data['employee_id']})
                    stats['errors'] += 1
                    continue
                
                existing = ImportedTimesheet.objects.filter(
                    employee=employee, year=year, month=month
                ).first()
                
                if existing:
                    stats['skipped'] += 1
                    continue
                
                timesheet = ImportedTimesheet.objects.create(
                    employee=employee,
                    year=year,
                    month=month,
                    total_hours=Decimal(str(ts_data['total_hours'])),
                    overtime_hours=Decimal(str(ts_data['overtime_hours'])),
                    raw_data=ts_data['raw_data']
                )
                
                generator = PDFGenerator()
                document = generator.generate_timesheet_pdf(timesheet, ts_data.get('entries', []))
                if document:
                    timesheet.document = document
                    timesheet.save()
                
                stats['imported'] += 1
                
            except Exception as e:
                stats['errors'] += 1
                self._log('ERROR', f'Fehler beim Import von Zeiterfassung: {str(e)}')
        
        self._log('INFO', f'Zeiterfassungs-Import für {month:02d}/{year} abgeschlossen', stats)
        return stats
