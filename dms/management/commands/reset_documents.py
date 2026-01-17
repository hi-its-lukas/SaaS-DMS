from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Löscht alle Dokumente und ProcessedFiles für einen sauberen Neustart (behält Stammdaten)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Bestätigt die Löschung (erforderlich)',
        )

    def handle(self, *args, **options):
        from dms.models import Document, ProcessedFile, SystemLog, PersonnelFileEntry
        
        if not options['confirm']:
            self.stdout.write(self.style.WARNING(
                "\nDies löscht ALLE Dokumente und ProcessedFiles!\n"
                "Folgendes bleibt erhalten:\n"
                "  - Mandanten\n"
                "  - Mitarbeiter\n"
                "  - Dokumenttypen\n"
                "  - Aktenplan (FileCategories)\n"
                "  - Personalakten (leer)\n"
                "  - Systemeinstellungen\n"
                "\nZum Bestätigen: --confirm hinzufügen"
            ))
            return
        
        self.stdout.write("Starte Reset...")
        
        entry_count = PersonnelFileEntry.objects.count()
        PersonnelFileEntry.objects.all().delete()
        self.stdout.write(f"  {entry_count} Akteneinträge gelöscht")
        
        doc_count = Document.objects.count()
        Document.objects.all().delete()
        self.stdout.write(f"  {doc_count} Dokumente gelöscht")
        
        pf_count = ProcessedFile.objects.count()
        ProcessedFile.objects.all().delete()
        self.stdout.write(f"  {pf_count} ProcessedFiles gelöscht")
        
        log_count = SystemLog.objects.count()
        SystemLog.objects.all().delete()
        self.stdout.write(f"  {log_count} Systemlogs gelöscht")
        
        self.stdout.write(self.style.SUCCESS(
            f"\nReset abgeschlossen. Sie können jetzt den Sage-Scan neu starten."
        ))
