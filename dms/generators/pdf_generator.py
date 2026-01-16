"""
PDF Document Generator
Generates PDF documents from templates for leave requests, timesheets, etc.
"""
import logging
import os
from datetime import date
from io import BytesIO
from typing import Optional, List, Dict, Any
from django.template import Template, Context
from django.utils import timezone

from ..models import (
    Document, Employee, ImportedLeaveRequest, ImportedTimesheet,
    DocumentType, SystemSettings, SystemLog
)
from ..encryption import encrypt_data, calculate_sha256

logger = logging.getLogger(__name__)

LEAVE_REQUEST_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; color: #333; }
        .header { text-align: center; margin-bottom: 30px; border-bottom: 2px solid #2c3e50; padding-bottom: 20px; }
        .header h1 { color: #2c3e50; margin: 0; }
        .header p { color: #666; margin: 5px 0 0 0; }
        .content { margin: 20px 0; }
        .field { margin: 15px 0; }
        .field-label { font-weight: bold; color: #2c3e50; display: inline-block; width: 200px; }
        .field-value { display: inline-block; }
        .approval { margin-top: 40px; padding: 20px; background: #e8f5e9; border-radius: 5px; }
        .approval h3 { color: #27ae60; margin: 0 0 10px 0; }
        .footer { margin-top: 50px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Urlaubsantrag</h1>
        <p>Genehmigt</p>
    </div>
    
    <div class="content">
        <div class="field">
            <span class="field-label">Mitarbeiter:</span>
            <span class="field-value">{{ employee_name }}</span>
        </div>
        <div class="field">
            <span class="field-label">Personalnummer:</span>
            <span class="field-value">{{ employee_id }}</span>
        </div>
        <div class="field">
            <span class="field-label">Urlaubsart:</span>
            <span class="field-value">{{ leave_type }}</span>
        </div>
        <div class="field">
            <span class="field-label">Zeitraum:</span>
            <span class="field-value">{{ start_date }} - {{ end_date }}</span>
        </div>
        <div class="field">
            <span class="field-label">Anzahl Tage:</span>
            <span class="field-value">{{ days_count }}</span>
        </div>
    </div>
    
    <div class="approval">
        <h3>Genehmigung</h3>
        <div class="field">
            <span class="field-label">Genehmigt am:</span>
            <span class="field-value">{{ approval_date }}</span>
        </div>
        <div class="field">
            <span class="field-label">Genehmigt von:</span>
            <span class="field-value">{{ approved_by }}</span>
        </div>
    </div>
    
    <div class="footer">
        <p>Dokument generiert am {{ generated_date }} | Referenz: {{ reference_id }}</p>
    </div>
</body>
</html>
"""

TIMESHEET_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; color: #333; }
        .header { text-align: center; margin-bottom: 30px; border-bottom: 2px solid #2c3e50; padding-bottom: 20px; }
        .header h1 { color: #2c3e50; margin: 0; }
        .header h2 { color: #666; margin: 10px 0 0 0; font-weight: normal; }
        .summary { display: flex; justify-content: space-around; margin: 30px 0; }
        .summary-box { text-align: center; padding: 20px; background: #f8f9fa; border-radius: 5px; min-width: 150px; }
        .summary-box h3 { margin: 0; font-size: 24px; color: #3498db; }
        .summary-box p { margin: 5px 0 0 0; color: #666; }
        table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background: #2c3e50; color: white; }
        tr:nth-child(even) { background: #f8f9fa; }
        .footer { margin-top: 50px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Arbeitszeitnachweis</h1>
        <h2>{{ month_name }} {{ year }}</h2>
    </div>
    
    <div class="content">
        <p><strong>Mitarbeiter:</strong> {{ employee_name }} ({{ employee_id }})</p>
        
        <div class="summary">
            <div class="summary-box">
                <h3>{{ total_hours }}</h3>
                <p>Gesamtstunden</p>
            </div>
            <div class="summary-box">
                <h3>{{ overtime_hours }}</h3>
                <p>Überstunden</p>
            </div>
        </div>
        
        {% if entries %}
        <table>
            <thead>
                <tr>
                    <th>Datum</th>
                    <th>Arbeitsbeginn</th>
                    <th>Arbeitsende</th>
                    <th>Pause</th>
                    <th>Stunden</th>
                </tr>
            </thead>
            <tbody>
                {% for entry in entries %}
                <tr>
                    <td>{{ entry.date }}</td>
                    <td>{{ entry.start_time }}</td>
                    <td>{{ entry.end_time }}</td>
                    <td>{{ entry.break_minutes }} min</td>
                    <td>{{ entry.hours }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% endif %}
    </div>
    
    <div class="footer">
        <p>Dokument generiert am {{ generated_date }}</p>
    </div>
</body>
</html>
"""

MONTH_NAMES_DE = {
    1: 'Januar', 2: 'Februar', 3: 'März', 4: 'April',
    5: 'Mai', 6: 'Juni', 7: 'Juli', 8: 'August',
    9: 'September', 10: 'Oktober', 11: 'November', 12: 'Dezember'
}


class PDFGenerator:
    """Generates PDF documents from data using HTML templates"""
    
    def __init__(self):
        self.settings = SystemSettings.load()
    
    def _log(self, level: str, message: str, details: dict = None):
        """Log to database"""
        SystemLog.objects.create(
            level=level.upper(),
            source='PDFGenerator',
            message=message,
            details=details or {}
        )
    
    def _render_html(self, template_str: str, context: dict) -> str:
        """Render HTML template with context"""
        template = Template(template_str)
        return template.render(Context(context))
    
    def _html_to_pdf(self, html_content: str) -> bytes:
        """Convert HTML to PDF using weasyprint"""
        try:
            from weasyprint import HTML
            pdf_bytes = HTML(string=html_content).write_pdf()
            return pdf_bytes
        except ImportError:
            try:
                import pdfkit
                pdf_bytes = pdfkit.from_string(html_content, False)
                return pdf_bytes
            except Exception as e:
                self._log('ERROR', f'PDF-Generierung fehlgeschlagen: {str(e)}')
                return html_content.encode('utf-8')
    
    def _create_document(
        self, 
        pdf_content: bytes, 
        title: str, 
        filename: str,
        employee: Employee,
        doc_type_name: str,
        source: str = 'SAGE'
    ) -> Optional[Document]:
        """Create encrypted document in database"""
        try:
            doc_type, _ = DocumentType.objects.get_or_create(
                name=doc_type_name,
                defaults={'description': f'Automatisch generierte {doc_type_name}'}
            )
            
            sha256_hash = calculate_sha256(pdf_content)
            
            if Document.objects.filter(sha256_hash=sha256_hash).exists():
                self._log('INFO', f'Dokument bereits vorhanden: {filename}')
                return Document.objects.filter(sha256_hash=sha256_hash).first()
            
            encrypted_content = encrypt_data(pdf_content)
            
            document = Document.objects.create(
                title=title,
                original_filename=filename,
                file_extension='.pdf',
                mime_type='application/pdf',
                encrypted_content=encrypted_content,
                file_size=len(pdf_content),
                document_type=doc_type,
                employee=employee,
                status='ASSIGNED',
                source=source,
                sha256_hash=sha256_hash
            )
            
            self._log('INFO', f'Dokument erstellt: {title}', {'document_id': str(document.id)})
            return document
            
        except Exception as e:
            self._log('ERROR', f'Fehler beim Erstellen des Dokuments: {str(e)}')
            return None
    
    def generate_leave_request_pdf(self, leave_request: ImportedLeaveRequest) -> Optional[Document]:
        """Generate PDF for a leave request"""
        employee = leave_request.employee
        
        context = {
            'employee_name': employee.full_name,
            'employee_id': employee.employee_id,
            'leave_type': leave_request.leave_type,
            'start_date': leave_request.start_date.strftime('%d.%m.%Y'),
            'end_date': leave_request.end_date.strftime('%d.%m.%Y'),
            'days_count': leave_request.days_count,
            'approval_date': leave_request.approval_date.strftime('%d.%m.%Y') if leave_request.approval_date else '-',
            'approved_by': leave_request.approved_by or '-',
            'generated_date': timezone.now().strftime('%d.%m.%Y %H:%M'),
            'reference_id': leave_request.sage_request_id
        }
        
        html_content = self._render_html(LEAVE_REQUEST_TEMPLATE, context)
        pdf_content = self._html_to_pdf(html_content)
        
        year = leave_request.start_date.year
        title = f"Urlaubsantrag {leave_request.start_date.strftime('%d.%m.%Y')} - {leave_request.end_date.strftime('%d.%m.%Y')}"
        filename = f"Urlaubsantrag_{leave_request.sage_request_id}.pdf"
        
        return self._create_document(
            pdf_content,
            title,
            filename,
            employee,
            'Urlaubsantrag'
        )
    
    def generate_timesheet_pdf(
        self, 
        timesheet: ImportedTimesheet, 
        entries: List[Dict[str, Any]] = None
    ) -> Optional[Document]:
        """Generate PDF for a monthly timesheet"""
        employee = timesheet.employee
        
        context = {
            'employee_name': employee.full_name,
            'employee_id': employee.employee_id,
            'month_name': MONTH_NAMES_DE.get(timesheet.month, str(timesheet.month)),
            'year': timesheet.year,
            'total_hours': timesheet.total_hours,
            'overtime_hours': timesheet.overtime_hours,
            'entries': entries or [],
            'generated_date': timezone.now().strftime('%d.%m.%Y %H:%M')
        }
        
        html_content = self._render_html(TIMESHEET_TEMPLATE, context)
        pdf_content = self._html_to_pdf(html_content)
        
        title = f"Arbeitszeitnachweis {MONTH_NAMES_DE.get(timesheet.month)} {timesheet.year}"
        filename = f"Zeitnachweis_{timesheet.year}_{timesheet.month:02d}.pdf"
        
        return self._create_document(
            pdf_content,
            title,
            filename,
            employee,
            'Arbeitszeitnachweis'
        )
