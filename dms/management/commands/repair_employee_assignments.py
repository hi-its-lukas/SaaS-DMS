"""
Management Command: repair_employee_assignments
=================================================
Repariert Dokumente mit Status REVIEW_NEEDED durch erneute Mitarbeiter-Zuordnung.
Nutzt verbesserte find_employee_by_id mit Fallback auf tenant=None Mitarbeiter.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from dms.models import Document, Employee


class Command(BaseCommand):
    help = 'Repariert REVIEW_NEEDED Dokumente durch erneute Mitarbeiter-Zuordnung'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Zeigt Änderungen ohne sie auszuführen',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        
        if dry_run:
            self.stdout.write(self.style.WARNING('=== DRY RUN ===\n'))
        
        from dms.tasks import find_employee_by_id
        
        docs = Document.objects.filter(
            status='REVIEW_NEEDED',
            employee__isnull=True
        ).select_related('tenant')
        
        total = docs.count()
        self.stdout.write(f"Gefunden: {total} Dokumente mit REVIEW_NEEDED und ohne Mitarbeiter\n")
        
        fixed = 0
        failed = 0
        
        for doc in docs:
            emp_id = doc.metadata.get('employee_id_from_datamatrix')
            mandant_code = doc.metadata.get('mandant_code')
            
            if not emp_id:
                continue
            
            employee = find_employee_by_id(
                emp_id, 
                tenant=doc.tenant, 
                mandant_code=mandant_code
            )
            
            if employee:
                old_status = doc.status
                self.stdout.write(
                    f"  {doc.original_filename[:40]}: MA-ID {emp_id} -> "
                    f"{employee.first_name} {employee.last_name} ({employee.employee_id})"
                )
                
                if not dry_run:
                    doc.employee = employee
                    doc.status = 'ASSIGNED'
                    doc.save(update_fields=['employee', 'status'])
                    
                    if hasattr(employee, 'personnel_file') and employee.personnel_file:
                        from dms.models import PersonnelFileEntry
                        if doc.document_type and doc.document_type.file_category:
                            PersonnelFileEntry.objects.get_or_create(
                                personnel_file=employee.personnel_file,
                                document=doc,
                                defaults={
                                    'category': doc.document_type.file_category,
                                    'notes': f'Auto-Reparatur: {doc.document_type.name}'
                                }
                            )
                
                fixed += 1
            else:
                self.stdout.write(
                    self.style.WARNING(f"  {doc.original_filename[:40]}: MA-ID {emp_id} nicht gefunden")
                )
                failed += 1
        
        self.stdout.write(self.style.SUCCESS(
            f"\nErgebnis: {fixed} repariert, {failed} nicht zuordenbar"
        ))
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\n=== DRY RUN - Keine Änderungen gespeichert ==='))
