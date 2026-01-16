"""
Sage Local WCF/SOAP Connector
Connects to local Sage HR Suite via WSDL/SOAP
"""
import logging
from typing import Optional, List, Dict, Any
from zeep import Client
from zeep.transports import Transport
from zeep.exceptions import Fault, TransportError
from requests import Session
from requests.exceptions import RequestException, Timeout

from ..models import SystemSettings, Employee, Department, CostCenter, SystemLog
from ..encryption import decrypt_data

logger = logging.getLogger(__name__)


class SageLocalConnector:
    """SOAP client for Sage Local WCF service"""
    
    def __init__(self):
        self.settings = SystemSettings.load()
        self.client: Optional[Client] = None
        self._connected = False
    
    def _log(self, level: str, message: str, details: dict = None):
        """Log to both logger and database"""
        getattr(logger, level.lower())(message)
        SystemLog.objects.create(
            level=level.upper(),
            source='SageLocalConnector',
            message=message,
            details=details or {}
        )
    
    def connect(self) -> bool:
        """Establish connection to Sage Local WCF service"""
        if not self.settings.sage_local_wsdl_url:
            self._log('WARNING', 'Sage Local WSDL URL nicht konfiguriert')
            return False
        
        try:
            session = Session()
            session.timeout = self.settings.sage_local_timeout
            
            if self.settings.encrypted_sage_local_api_key:
                api_key = decrypt_data(bytes(self.settings.encrypted_sage_local_api_key)).decode()
                session.headers.update({
                    'X-API-User': self.settings.sage_local_api_user,
                    'X-API-Key': api_key
                })
            
            transport = Transport(session=session, timeout=self.settings.sage_local_timeout)
            self.client = Client(self.settings.sage_local_wsdl_url, transport=transport)
            self._connected = True
            self._log('INFO', 'Verbindung zu Sage Local hergestellt', {'wsdl': self.settings.sage_local_wsdl_url})
            return True
            
        except Timeout:
            self._log('ERROR', 'Timeout bei Verbindung zu Sage Local', 
                     {'url': self.settings.sage_local_wsdl_url, 'timeout': self.settings.sage_local_timeout})
            return False
        except (TransportError, RequestException) as e:
            self._log('ERROR', f'Verbindungsfehler zu Sage Local: {str(e)}',
                     {'url': self.settings.sage_local_wsdl_url})
            return False
        except Exception as e:
            self._log('ERROR', f'Unerwarteter Fehler bei Sage Local Verbindung: {str(e)}')
            return False
    
    def is_connected(self) -> bool:
        return self._connected and self.client is not None
    
    def fetch_employees(self) -> List[Dict[str, Any]]:
        """Fetch all employees from Sage Local"""
        if not self.is_connected():
            if not self.connect():
                return []
        
        try:
            result = self.client.service.GetAllEmployees()
            employees = []
            
            for emp in result:
                employees.append({
                    'sage_local_id': str(emp.ID),
                    'employee_id': emp.PersonalNummer or str(emp.ID),
                    'first_name': emp.Vorname or '',
                    'last_name': emp.Nachname or '',
                    'email': getattr(emp, 'Email', ''),
                    'department_name': getattr(emp, 'Abteilung', ''),
                    'cost_center_code': getattr(emp, 'Kostenstelle', ''),
                    'entry_date': getattr(emp, 'Eintrittsdatum', None),
                    'is_active': getattr(emp, 'Aktiv', True),
                })
            
            self._log('INFO', f'{len(employees)} Mitarbeiter von Sage Local abgerufen')
            return employees
            
        except Fault as e:
            self._log('ERROR', f'SOAP Fault bei Mitarbeiterabruf: {e.message}')
            return []
        except Exception as e:
            self._log('ERROR', f'Fehler beim Abrufen der Mitarbeiter: {str(e)}')
            return []
    
    def sync_employees(self) -> Dict[str, int]:
        """Sync employees from Sage Local to database"""
        employees_data = self.fetch_employees()
        
        stats = {'created': 0, 'updated': 0, 'errors': 0}
        
        for emp_data in employees_data:
            try:
                department = None
                if emp_data.get('department_name'):
                    department, _ = Department.objects.get_or_create(
                        name=emp_data['department_name']
                    )
                
                cost_center = None
                if emp_data.get('cost_center_code'):
                    cost_center, _ = CostCenter.objects.get_or_create(
                        code=emp_data['cost_center_code'],
                        defaults={'name': emp_data['cost_center_code']}
                    )
                
                employee, created = Employee.objects.update_or_create(
                    sage_local_id=emp_data['sage_local_id'],
                    defaults={
                        'employee_id': emp_data['employee_id'],
                        'first_name': emp_data['first_name'],
                        'last_name': emp_data['last_name'],
                        'email': emp_data.get('email', ''),
                        'department': department,
                        'cost_center': cost_center,
                        'entry_date': emp_data.get('entry_date'),
                        'is_active': emp_data.get('is_active', True),
                    }
                )
                
                if created:
                    stats['created'] += 1
                else:
                    stats['updated'] += 1
                    
            except Exception as e:
                stats['errors'] += 1
                self._log('ERROR', f'Fehler bei Mitarbeiter-Sync: {str(e)}', {'data': emp_data})
        
        self._log('INFO', 'Mitarbeiter-Sync abgeschlossen', stats)
        return stats
