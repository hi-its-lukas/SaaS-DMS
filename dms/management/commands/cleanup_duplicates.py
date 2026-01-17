from django.core.management.base import BaseCommand
from django.db.models import Count
from dms.models import Document, ProcessedFile


class Command(BaseCommand):
    help = 'Findet und entfernt doppelte Dokumente basierend auf SHA-256 Hash'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Zeigt nur an, was gelöscht würde, ohne tatsächlich zu löschen',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        self.stdout.write('Suche nach doppelten Dokumenten...\n')
        
        duplicates = (
            Document.objects
            .values('tenant_id', 'sha256_hash')
            .annotate(count=Count('id'))
            .filter(count__gt=1)
        )
        
        total_duplicates = 0
        deleted_count = 0
        
        for dup in duplicates:
            tenant_id = dup['tenant_id']
            sha256_hash = dup['sha256_hash']
            count = dup['count']
            
            docs = Document.objects.filter(
                tenant_id=tenant_id,
                sha256_hash=sha256_hash
            ).order_by('created_at')
            
            original = docs.first()
            to_delete = docs[1:]
            
            self.stdout.write(f'\nDuplikat gefunden: {original.title}')
            self.stdout.write(f'  Original: {original.id} ({original.created_at})')
            self.stdout.write(f'  Duplikate: {count - 1}')
            
            for doc in to_delete:
                total_duplicates += 1
                self.stdout.write(f'    - {doc.id} ({doc.created_at})')
                
                if not dry_run:
                    ProcessedFile.objects.filter(document=doc).delete()
                    doc.delete()
                    deleted_count += 1
        
        self.stdout.write('\n' + '=' * 50)
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'DRY RUN: {total_duplicates} Duplikate gefunden, die gelöscht würden.'
            ))
            self.stdout.write('Führen Sie ohne --dry-run aus, um tatsächlich zu löschen.')
        else:
            self.stdout.write(self.style.SUCCESS(
                f'{deleted_count} Duplikate gelöscht.'
            ))
