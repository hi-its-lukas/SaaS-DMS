from django.core.management.base import BaseCommand
from django.db import transaction
from dms.models import DocumentType, Document


class Command(BaseCommand):
    help = 'Merge duplicate DocumentTypes (UPPERCASE -> Normal case)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        all_types = DocumentType.objects.all()
        
        name_groups = {}
        for dt in all_types:
            key = dt.name.lower().replace('_', ' ').replace('-', ' ')
            if key not in name_groups:
                name_groups[key] = []
            name_groups[key].append(dt)
        
        duplicates_found = 0
        docs_moved = 0
        types_deleted = 0
        
        for key, types in name_groups.items():
            if len(types) <= 1:
                continue
            
            duplicates_found += 1
            
            normal_case = None
            uppercase = []
            
            for dt in types:
                if dt.name.isupper() or '_' in dt.name:
                    uppercase.append(dt)
                else:
                    normal_case = dt
            
            if not normal_case and uppercase:
                best = uppercase[0]
                normal_name = best.name.replace('_', ' ').title()
                if dry_run:
                    self.stdout.write(f"  Would rename: {best.name} -> {normal_name}")
                else:
                    best.name = normal_name
                    best.save()
                normal_case = best
                uppercase = uppercase[1:]
            
            if not normal_case:
                continue
            
            for uc in uppercase:
                doc_count = Document.objects.filter(document_type=uc).count()
                
                if dry_run:
                    self.stdout.write(
                        f"  Would merge: {uc.name} ({doc_count} docs) -> {normal_case.name}"
                    )
                else:
                    Document.objects.filter(document_type=uc).update(document_type=normal_case)
                    uc.delete()
                    self.stdout.write(
                        self.style.SUCCESS(f"  Merged: {uc.name} ({doc_count} docs) -> {normal_case.name}")
                    )
                
                docs_moved += doc_count
                types_deleted += 1
        
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"\n[DRY RUN] Would merge {duplicates_found} duplicate groups, "
                f"move {docs_moved} documents, delete {types_deleted} types"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\nMerged {duplicates_found} duplicate groups, "
                f"moved {docs_moved} documents, deleted {types_deleted} types"
            ))
