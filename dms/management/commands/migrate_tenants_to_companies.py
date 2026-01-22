"""
Management command to migrate existing Tenants to the new Company structure.

This creates a Company for each existing Tenant without a company, and assigns
the Tenant to that Company. This is a one-time migration for upgrading from
the old single-tenant model to the new hierarchical Company → Tenant model.

Usage:
    python manage.py migrate_tenants_to_companies
    python manage.py migrate_tenants_to_companies --dry-run
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from dms.models import Company, Tenant


class Command(BaseCommand):
    help = 'Migrate existing Tenants to the new Company structure'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes'
        )
    
    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - No changes will be made'))
        
        orphan_tenants = Tenant.objects.filter(company__isnull=True)
        count = orphan_tenants.count()
        
        if count == 0:
            self.stdout.write(self.style.SUCCESS('No orphan tenants found. All tenants are already assigned to companies.'))
            return
        
        self.stdout.write(f'Found {count} tenant(s) without a company.')
        
        created_count = 0
        updated_count = 0
        
        for tenant in orphan_tenants:
            company_name = tenant.name
            
            self.stdout.write(f'  Processing: {tenant.name} (Code: {tenant.code or "N/A"})')
            
            if dry_run:
                self.stdout.write(f'    [DRY RUN] Would create Company: {company_name}')
                self.stdout.write(f'    [DRY RUN] Would assign Tenant to Company')
                created_count += 1
                updated_count += 1
            else:
                with transaction.atomic():
                    company = Company.objects.create(
                        name=company_name,
                        is_active=tenant.is_active,
                        license_max_mandanten=5,
                        license_max_users=50,
                        license_max_personnel_files=1000,
                    )
                    created_count += 1
                    self.stdout.write(self.style.SUCCESS(f'    Created Company: {company.name} (ID: {company.system_id})'))
                    
                    tenant.company = company
                    tenant.save(update_fields=['company'])
                    updated_count += 1
                    self.stdout.write(self.style.SUCCESS(f'    Assigned Tenant to Company'))
        
        self.stdout.write('')
        if dry_run:
            self.stdout.write(self.style.WARNING(f'DRY RUN COMPLETE: Would create {created_count} companies and update {updated_count} tenants.'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Migration complete: Created {created_count} companies, updated {updated_count} tenants.'))
