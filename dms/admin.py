from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Count
from django import forms
from unfold.admin import ModelAdmin, TabularInline, StackedInline
from unfold.decorators import display
from unfold.contrib.filters.admin import RangeDateFilter, DropdownFilter, ChoicesDropdownFilter
from .models import (
    Tenant, TenantUser,
    Department, CostCenter, Employee, DocumentType, Document, 
    ProcessedFile, Task, SystemLog, SystemSettings,
    ImportedLeaveRequest, ImportedTimesheet,
    FileCategory, PersonnelFile, PersonnelFileEntry, DocumentVersion,
    AccessPermission, AuditLog, ScanJob, Tag, DocumentTag, MatchingRule,
    Reminder
)
from .encryption import encrypt_data, decrypt_data


def dashboard_callback(request, context):
    """
    Dashboard callback for Unfold admin.
    Provides statistics and recent activity for the dashboard.
    """
    from django.db.models import Count, Q
    from django.utils import timezone
    from datetime import timedelta
    
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    
    if request.user.is_superuser:
        total_documents = Document.all_objects.count()
        total_employees = Employee.all_objects.count()
        total_tenants = Tenant.objects.count()
        inbox_count = Document.all_objects.filter(status='UNASSIGNED').count()
        recent_docs = Document.all_objects.filter(created_at__date__gte=week_ago).count()
    else:
        total_documents = Document.objects.count()
        total_employees = Employee.objects.count()
        total_tenants = 1
        inbox_count = Document.objects.filter(status='UNASSIGNED').count()
        recent_docs = Document.objects.filter(created_at__date__gte=week_ago).count()
    
    context.update({
        "kpi": [
            {"title": "Dokumente", "metric": total_documents, "icon": "description"},
            {"title": "Mitarbeiter", "metric": total_employees, "icon": "badge"},
            {"title": "Mandanten", "metric": total_tenants, "icon": "domain"},
            {"title": "Inbox", "metric": inbox_count, "icon": "inbox"},
        ],
        "recent_documents_count": recent_docs,
    })
    
    return context


class TenantFilterMixin:
    """
    Mixin for admin classes to filter querysets by tenant.
    Superusers see all data; regular users see only their tenant's data.
    """
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        tenant = getattr(request, 'tenant', None)
        if tenant and hasattr(self.model, 'tenant'):
            return qs.filter(tenant=tenant)
        return qs
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'tenant' and not request.user.is_superuser:
            kwargs['queryset'] = Tenant.objects.filter(
                id=getattr(request, 'tenant', None).id if getattr(request, 'tenant', None) else None
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class TenantUserInline(TabularInline):
    model = TenantUser
    extra = 1


@admin.register(Tenant)
class TenantAdmin(ModelAdmin):
    list_display = ['code', 'name', 'ingest_email', 'is_active_badge', 'user_count', 'created_at']
    list_filter = ['is_active']
    search_fields = ['code', 'name', 'ingest_token']
    inlines = [TenantUserInline]
    readonly_fields = ['ingest_token', 'ingest_email_display']
    
    fieldsets = (
        ('Mandant', {
            'fields': ('code', 'name', 'description', 'is_active')
        }),
        ('E-Mail-Ingest', {
            'fields': ('ingest_token', 'ingest_email_display'),
            'description': 'Dokumente an diese E-Mail-Adresse senden, um sie automatisch diesem Mandanten zuzuordnen.'
        }),
    )
    
    @display(description="Status", label={"Aktiv": "success", "Inaktiv": "danger"})
    def is_active_badge(self, obj):
        return "Aktiv" if obj.is_active else "Inaktiv"
    
    @display(description="Ingest-E-Mail")
    def ingest_email(self, obj):
        if obj.ingest_token:
            return f"upload.{obj.ingest_token}@dms.cloud"
        return "-"
    
    @display(description="Ingest-E-Mail-Adresse")
    def ingest_email_display(self, obj):
        if obj.ingest_token:
            return f"upload.{obj.ingest_token}@dms.cloud"
        return "Token wird beim Speichern automatisch generiert"
    
    def user_count(self, obj):
        return obj.users.count()
    user_count.short_description = 'Benutzer'
    
    def has_module_permission(self, request):
        return request.user.is_superuser
    
    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser
    
    def has_add_permission(self, request):
        return request.user.is_superuser


@admin.register(TenantUser)
class TenantUserAdmin(TenantFilterMixin, ModelAdmin):
    list_display = ['user', 'tenant', 'is_admin_badge', 'created_at']
    list_filter = ['tenant', 'is_admin']
    search_fields = ['user__username', 'tenant__name']
    raw_id_fields = ['user']
    
    @display(description="Admin", label={"Ja": "success", "Nein": "info"})
    def is_admin_badge(self, obj):
        return "Ja" if obj.is_admin else "Nein"


@admin.register(Department)
class DepartmentAdmin(TenantFilterMixin, ModelAdmin):
    list_display = ['name', 'tenant', 'description', 'created_at']
    list_filter = ['tenant']
    search_fields = ['name', 'description']


@admin.register(CostCenter)
class CostCenterAdmin(TenantFilterMixin, ModelAdmin):
    list_display = ['code', 'name', 'tenant', 'is_active_badge', 'created_at']
    list_filter = ['tenant', 'is_active']
    search_fields = ['code', 'name']
    
    @display(description="Status", label={"Aktiv": "success", "Inaktiv": "danger"})
    def is_active_badge(self, obj):
        return "Aktiv" if obj.is_active else "Inaktiv"


@admin.register(Employee)
class EmployeeAdmin(TenantFilterMixin, ModelAdmin):
    list_display = ['employee_id', 'full_name', 'tenant', 'sage_cloud_id', 'department', 'cost_center', 'is_active_badge']
    list_filter = ['tenant', 'is_active', 'department', 'cost_center']
    search_fields = ['employee_id', 'first_name', 'last_name', 'email', 'sage_cloud_id']
    raw_id_fields = ['user']
    
    @display(description="Status", label={"Aktiv": "success", "Inaktiv": "danger"})
    def is_active_badge(self, obj):
        return "Aktiv" if obj.is_active else "Inaktiv"
    
    fieldsets = (
        ('Stammdaten', {
            'fields': ('employee_id', 'first_name', 'last_name', 'email', 'tenant')
        }),
        ('Sage Cloud-Verknüpfung', {
            'fields': ('sage_cloud_id',),
            'classes': ('collapse',)
        }),
        ('Organisation', {
            'fields': ('department', 'cost_center', 'entry_date', 'exit_date')
        }),
        ('Benutzer', {
            'fields': ('user', 'is_active')
        }),
    )


@admin.register(DocumentType)
class DocumentTypeAdmin(TenantFilterMixin, ModelAdmin):
    list_display = ['name', 'file_category', 'tenant', 'doc_count', 'retention_days', 'is_active_badge']
    list_filter = ['is_active', 'tenant', 'file_category']
    search_fields = ['name', 'description']
    autocomplete_fields = ['file_category']
    
    @display(description="Status", label={"Aktiv": "success", "Inaktiv": "danger"})
    def is_active_badge(self, obj):
        return "Aktiv" if obj.is_active else "Inaktiv"
    
    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'tenant')
        }),
        ('Aktenplan-Zuordnung', {
            'fields': ('file_category',),
            'description': 'Dokumente dieses Typs werden automatisch in diese Unterakte der Personalakte einsortiert.'
        }),
        ('Einstellungen', {
            'fields': ('retention_days', 'is_active', 'required_fields'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['apply_category_to_documents']
    
    def doc_count(self, obj):
        return obj.document_set.count()
    doc_count.short_description = 'Dokumente'
    
    def apply_category_to_documents(self, request, queryset):
        from .models import Document, PersonnelFile, PersonnelFileEntry
        
        total_created = 0
        total_skipped = 0
        
        for doc_type in queryset:
            if not doc_type.file_category:
                self.message_user(request, f"'{doc_type.name}' hat keine Aktenkategorie zugeordnet.", level='warning')
                continue
            
            documents = Document.all_objects.filter(
                document_type=doc_type,
                employee__isnull=False
            ).select_related('employee', 'tenant')
            
            for doc in documents:
                personnel_file, _ = PersonnelFile.all_objects.get_or_create(
                    employee=doc.employee,
                    defaults={
                        'tenant': doc.tenant,
                        'file_number': f"PA-{doc.employee.employee_id}",
                        'status': 'ACTIVE'
                    }
                )
                
                entry, created = PersonnelFileEntry.objects.get_or_create(
                    personnel_file=personnel_file,
                    document=doc,
                    defaults={
                        'category': doc_type.file_category,
                        'document_date': getattr(doc, 'document_date', None) or doc.created_at.date(),
                        'created_by': request.user
                    }
                )
                
                if created:
                    total_created += 1
                else:
                    total_skipped += 1
        
        self.message_user(
            request, 
            f"{total_created} Akteneinträge erstellt, {total_skipped} bereits vorhanden."
        )
    apply_category_to_documents.short_description = "Auf bestehende Dokumente anwenden"


@admin.register(Document)
class DocumentAdmin(TenantFilterMixin, ModelAdmin):
    list_display = ['title', 'tenant', 'status_badge', 'source_badge', 'employee', 'document_type', 'file_size_display', 'created_at']
    list_filter = [
        'tenant', 
        ('status', ChoicesDropdownFilter),
        ('source', ChoicesDropdownFilter),
        'document_type',
        ('created_at', RangeDateFilter),
    ]
    search_fields = ['title', 'original_filename', 'employee__first_name', 'employee__last_name']
    raw_id_fields = ['employee', 'owner']
    readonly_fields = ['id', 'sha256_hash', 'file_size', 'created_at', 'updated_at']
    date_hierarchy = 'created_at'
    
    @display(
        description="Status",
        label={
            "Inbox": "warning",
            "Zugewiesen": "info", 
            "Archiviert": "success",
            "Prüfung": "danger",
        }
    )
    def status_badge(self, obj):
        status_map = {
            'UNASSIGNED': 'Inbox',
            'ASSIGNED': 'Zugewiesen',
            'ARCHIVED': 'Archiviert',
            'REVIEW_NEEDED': 'Prüfung',
        }
        return status_map.get(obj.status, obj.status)
    
    @display(
        description="Quelle",
        label={
            "Sage": "primary",
            "Manuell": "secondary",
            "Web": "info",
            "E-Mail": "warning",
        }
    )
    def source_badge(self, obj):
        source_map = {
            'SAGE': 'Sage',
            'MANUAL': 'Manuell',
            'WEB': 'Web',
            'EMAIL': 'E-Mail',
        }
        return source_map.get(obj.source, obj.source)
    
    fieldsets = (
        ('Dokumentinfo', {
            'fields': ('id', 'title', 'original_filename', 'file_extension', 'mime_type', 'file')
        }),
        ('Klassifizierung', {
            'fields': ('document_type', 'employee', 'owner', 'status', 'source', 'tenant')
        }),
        ('Periode', {
            'fields': ('period_year', 'period_month'),
        }),
        ('Metadaten', {
            'fields': ('metadata', 'notes', 'sha256_hash', 'file_size')
        }),
        ('Zeitstempel', {
            'fields': ('created_at', 'updated_at', 'archived_at'),
            'classes': ('collapse',)
        }),
    )
    
    def file_size_display(self, obj):
        if obj.file_size < 1024:
            return f"{obj.file_size} B"
        elif obj.file_size < 1024 * 1024:
            return f"{obj.file_size / 1024:.1f} KB"
        else:
            return f"{obj.file_size / (1024 * 1024):.1f} MB"
    file_size_display.short_description = 'Größe'
    
    actions = ['mark_as_archived', 'mark_as_review_needed']
    
    def mark_as_archived(self, request, queryset):
        queryset.update(status='ARCHIVED')
    mark_as_archived.short_description = "Als archiviert markieren"
    
    def mark_as_review_needed(self, request, queryset):
        queryset.update(status='REVIEW_NEEDED')
    mark_as_review_needed.short_description = "Prüfung erforderlich markieren"


@admin.register(ProcessedFile)
class ProcessedFileAdmin(TenantFilterMixin, ModelAdmin):
    list_display = ['sha256_hash_short', 'original_path', 'processed_at', 'document']
    list_filter = ['processed_at']
    search_fields = ['sha256_hash', 'original_path']
    raw_id_fields = ['document']
    readonly_fields = ['sha256_hash', 'original_path', 'processed_at']
    
    def sha256_hash_short(self, obj):
        return f"{obj.sha256_hash[:16]}..."
    sha256_hash_short.short_description = 'SHA-256'


@admin.register(Task)
class TaskAdmin(ModelAdmin):
    list_display = ['title', 'status_badge', 'priority_badge', 'assigned_to', 'due_date', 'created_at']
    list_filter = [
        ('status', ChoicesDropdownFilter),
        ('priority', ChoicesDropdownFilter),
        ('created_at', RangeDateFilter),
    ]
    search_fields = ['title', 'description']
    raw_id_fields = ['document', 'assigned_to', 'created_by']
    date_hierarchy = 'created_at'
    
    @display(
        description="Status",
        label={
            "Offen": "warning",
            "In Bearbeitung": "info",
            "Erledigt": "success",
            "Abgebrochen": "danger",
        }
    )
    def status_badge(self, obj):
        status_map = {
            'OPEN': 'Offen',
            'IN_PROGRESS': 'In Bearbeitung',
            'COMPLETED': 'Erledigt',
            'CANCELLED': 'Abgebrochen',
        }
        return status_map.get(obj.status, obj.status)
    
    @display(
        description="Priorität",
        label={
            "Niedrig": "secondary",
            "Mittel": "info",
            "Hoch": "warning",
            "Dringend": "danger",
        }
    )
    def priority_badge(self, obj):
        priority_map = {
            1: 'Niedrig',
            2: 'Mittel',
            3: 'Hoch',
            4: 'Dringend',
        }
        return priority_map.get(obj.priority, str(obj.priority))
    
    fieldsets = (
        ('Aufgabeninfo', {
            'fields': ('title', 'description', 'document')
        }),
        ('Zuweisung', {
            'fields': ('assigned_to', 'created_by', 'priority', 'status')
        }),
        ('Termine', {
            'fields': ('due_date', 'completed_at', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ['created_at', 'updated_at', 'completed_at']
    
    actions = ['mark_as_completed', 'mark_as_open']
    
    def mark_as_completed(self, request, queryset):
        from django.utils import timezone
        queryset.update(status='COMPLETED', completed_at=timezone.now())
    mark_as_completed.short_description = "Als erledigt markieren"
    
    def mark_as_open(self, request, queryset):
        queryset.update(status='OPEN', completed_at=None)
    mark_as_open.short_description = "Als offen markieren"


@admin.register(SystemLog)
class SystemLogAdmin(ModelAdmin):
    list_display = ['timestamp', 'level_badge', 'source', 'message_short']
    list_filter = [
        ('level', ChoicesDropdownFilter),
        'source',
        ('timestamp', RangeDateFilter),
    ]
    search_fields = ['message', 'source']
    readonly_fields = ['timestamp', 'level', 'source', 'message', 'details']
    date_hierarchy = 'timestamp'
    
    @display(
        description="Level",
        label={
            "DEBUG": "secondary",
            "INFO": "info",
            "WARNING": "warning",
            "ERROR": "danger",
            "CRITICAL": "danger",
        }
    )
    def level_badge(self, obj):
        return obj.level
    
    def message_short(self, obj):
        return obj.message[:100] + '...' if len(obj.message) > 100 else obj.message
    message_short.short_description = 'Nachricht'
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_module_permission(self, request):
        return request.user.is_superuser


class SystemSettingsAdminForm(forms.ModelForm):
    sage_cloud_api_key = forms.CharField(
        widget=forms.PasswordInput(render_value=True),
        required=False,
        label="Sage Cloud API-Schlüssel"
    )
    ms_graph_secret = forms.CharField(
        widget=forms.PasswordInput(render_value=True),
        required=False,
        label="MS Graph Secret"
    )
    samba_password = forms.CharField(
        widget=forms.PasswordInput(render_value=True),
        required=False,
        label="Samba Passwort",
        help_text="Passwort für Netzwerkfreigaben (Sage_Archiv, Manueller_Scan)"
    )
    
    class Meta:
        model = SystemSettings
        exclude = ['encrypted_sage_cloud_api_key', 'encrypted_ms_graph_secret', 'encrypted_samba_password']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            if self.instance.encrypted_sage_cloud_api_key:
                try:
                    self.fields['sage_cloud_api_key'].initial = decrypt_data(bytes(self.instance.encrypted_sage_cloud_api_key)).decode()
                except Exception:
                    pass
            if self.instance.encrypted_ms_graph_secret:
                try:
                    self.fields['ms_graph_secret'].initial = decrypt_data(bytes(self.instance.encrypted_ms_graph_secret)).decode()
                except Exception:
                    pass
            if self.instance.encrypted_samba_password:
                try:
                    self.fields['samba_password'].initial = decrypt_data(bytes(self.instance.encrypted_samba_password)).decode()
                except Exception:
                    pass
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        
        sage_cloud_key = self.cleaned_data.get('sage_cloud_api_key')
        if sage_cloud_key:
            instance.encrypted_sage_cloud_api_key = encrypt_data(sage_cloud_key.encode())
        
        ms_graph = self.cleaned_data.get('ms_graph_secret')
        if ms_graph:
            instance.encrypted_ms_graph_secret = encrypt_data(ms_graph.encode())
        
        samba_pw = self.cleaned_data.get('samba_password')
        if samba_pw:
            instance.encrypted_samba_password = encrypt_data(samba_pw.encode())
        
        if commit:
            instance.save()
            self._update_samba_config(instance)
        return instance
    
    def _update_samba_config(self, instance):
        import os
        from pathlib import Path
        
        if not instance.encrypted_samba_password:
            return
        
        try:
            samba_password = decrypt_data(bytes(instance.encrypted_samba_password)).decode()
            config_dir = Path('/data/runtime')
            config_dir.mkdir(parents=True, exist_ok=True)
            
            env_file = config_dir / '.env.samba'
            with open(env_file, 'w') as f:
                f.write(f"SAMBA_USER={instance.samba_username}\n")
                f.write(f"SAMBA_PASSWORD={samba_password}\n")
            
            os.chmod(env_file, 0o600)
        except Exception:
            pass


@admin.register(SystemSettings)
class SystemSettingsAdmin(ModelAdmin):
    form = SystemSettingsAdminForm
    list_display = ('__str__', 'sage_cloud_api_url', 'ms_graph_tenant_id', 'samba_username')
    
    fieldsets = (
        ('Sage Cloud (REST)', {
            'fields': ('sage_cloud_api_url', 'sage_cloud_api_key'),
            'description': 'Verbindungseinstellungen für Sage HR Cloud'
        }),
        ('Microsoft Graph', {
            'fields': ('ms_graph_tenant_id', 'ms_graph_client_id', 'ms_graph_secret'),
            'description': 'Verbindungseinstellungen für Microsoft 365'
        }),
        ('Netzwerkfreigaben (Samba)', {
            'fields': ('samba_username', 'samba_password'),
            'description': 'Zugangsdaten für Windows-Netzwerkfreigaben'
        }),
    )
    
    def has_add_permission(self, request):
        return not SystemSettings.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    def has_module_permission(self, request):
        return request.user.is_superuser
    
    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(ImportedLeaveRequest)
class ImportedLeaveRequestAdmin(TenantFilterMixin, ModelAdmin):
    list_display = ['sage_request_id', 'employee', 'leave_type', 'start_date', 'end_date', 'days_count', 'imported_at']
    list_filter = ['leave_type', ('start_date', RangeDateFilter), ('imported_at', RangeDateFilter)]
    search_fields = ['sage_request_id', 'employee__first_name', 'employee__last_name']
    raw_id_fields = ['employee', 'document']
    readonly_fields = ['sage_request_id', 'raw_data', 'imported_at']
    date_hierarchy = 'start_date'


@admin.register(ImportedTimesheet)
class ImportedTimesheetAdmin(TenantFilterMixin, ModelAdmin):
    list_display = ['employee', 'year', 'month', 'total_hours', 'overtime_hours', 'imported_at']
    list_filter = ['year', 'month', ('imported_at', RangeDateFilter)]
    search_fields = ['employee__first_name', 'employee__last_name']
    raw_id_fields = ['employee', 'document']
    readonly_fields = ['raw_data', 'imported_at']


@admin.register(FileCategory)
class FileCategoryAdmin(TenantFilterMixin, ModelAdmin):
    list_display = ['code', 'name', 'parent', 'retention_years', 'retention_trigger', 'is_mandatory_badge', 'sort_order', 'is_active_badge']
    list_filter = ['is_active', 'is_mandatory', 'retention_trigger', 'parent', 'tenant']
    search_fields = ['code', 'name', 'description']
    list_editable = ['sort_order']
    ordering = ['sort_order', 'code']
    
    @display(description="Pflicht", label={"Ja": "warning", "Nein": "secondary"})
    def is_mandatory_badge(self, obj):
        return "Ja" if obj.is_mandatory else "Nein"
    
    @display(description="Status", label={"Aktiv": "success", "Inaktiv": "danger"})
    def is_active_badge(self, obj):
        return "Aktiv" if obj.is_active else "Inaktiv"
    
    fieldsets = (
        ('Aktenzeichen', {
            'fields': ('code', 'name', 'description', 'parent', 'tenant')
        }),
        ('Aufbewahrung', {
            'fields': ('retention_years', 'retention_trigger'),
            'description': 'Aufbewahrungsfristen gemäß Aktenplan'
        }),
        ('Einstellungen', {
            'fields': ('is_mandatory', 'sort_order', 'is_active')
        }),
    )


class PersonnelFileEntryInline(TabularInline):
    model = PersonnelFileEntry
    extra = 0
    readonly_fields = ['entry_number', 'created_at', 'created_by']
    raw_id_fields = ['document']
    fields = ['entry_number', 'category', 'document', 'document_date', 'notes', 'created_by', 'created_at']


@admin.register(PersonnelFile)
class PersonnelFileAdmin(TenantFilterMixin, ModelAdmin):
    list_display = ['file_number', 'employee', 'status_badge', 'document_count', 'opened_at', 'closed_at']
    list_filter = [('status', ChoicesDropdownFilter), ('opened_at', RangeDateFilter), 'tenant']
    search_fields = ['file_number', 'employee__first_name', 'employee__last_name', 'employee__employee_id']
    raw_id_fields = ['employee']
    readonly_fields = ['id', 'opened_at', 'created_at', 'updated_at', 'document_count']
    inlines = [PersonnelFileEntryInline]
    
    @display(
        description="Status",
        label={
            "Aktiv": "success",
            "Inaktiv": "warning",
            "Archiviert": "info",
            "Löschen": "danger",
        }
    )
    def status_badge(self, obj):
        status_map = {
            'ACTIVE': 'Aktiv',
            'INACTIVE': 'Inaktiv',
            'ARCHIVED': 'Archiviert',
            'DELETED': 'Löschen',
        }
        return status_map.get(obj.status, obj.status)
    
    fieldsets = (
        ('Akte', {
            'fields': ('id', 'file_number', 'employee', 'status', 'tenant')
        }),
        ('Zeitraum', {
            'fields': ('opened_at', 'closed_at', 'retention_until')
        }),
        ('Bemerkungen', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['close_files', 'archive_files']
    
    def close_files(self, request, queryset):
        from django.utils import timezone
        queryset.update(status='INACTIVE', closed_at=timezone.now().date())
    close_files.short_description = "Akten schließen (MA ausgeschieden)"
    
    def archive_files(self, request, queryset):
        queryset.update(status='ARCHIVED')
    archive_files.short_description = "Als archiviert markieren"


@admin.register(PersonnelFileEntry)
class PersonnelFileEntryAdmin(ModelAdmin):
    list_display = ['personnel_file', 'entry_number', 'category', 'document', 'document_date', 'created_at']
    list_filter = ['category', ('created_at', RangeDateFilter)]
    search_fields = ['personnel_file__file_number', 'document__title', 'notes']
    raw_id_fields = ['personnel_file', 'document', 'created_by']
    readonly_fields = ['entry_number', 'created_at']
    date_hierarchy = 'created_at'


@admin.register(DocumentVersion)
class DocumentVersionAdmin(ModelAdmin):
    list_display = ['document', 'version_number', 'file_size_display', 'created_by', 'created_at']
    list_filter = [('created_at', RangeDateFilter)]
    search_fields = ['document__title', 'change_reason']
    raw_id_fields = ['document', 'created_by']
    readonly_fields = ['id', 'version_number', 'sha256_hash', 'file_size', 'created_at']
    
    def file_size_display(self, obj):
        if obj.file_size < 1024:
            return f"{obj.file_size} B"
        elif obj.file_size < 1024 * 1024:
            return f"{obj.file_size / 1024:.1f} KB"
        else:
            return f"{obj.file_size / (1024 * 1024):.1f} MB"
    file_size_display.short_description = 'Größe'


@admin.register(AccessPermission)
class AccessPermissionAdmin(TenantFilterMixin, ModelAdmin):
    list_display = ['get_target', 'get_object', 'permission_level', 'inherit_to_children', 'valid_from', 'valid_until']
    list_filter = ['target_type', 'permission_level', 'inherit_to_children', 'tenant']
    search_fields = ['user__username', 'group__name']
    raw_id_fields = ['user', 'category', 'personnel_file', 'department', 'created_by']
    
    fieldsets = (
        ('Berechtigter', {
            'fields': ('user', 'group', 'tenant'),
            'description': 'Entweder Benutzer ODER Gruppe auswählen'
        }),
        ('Ziel', {
            'fields': ('target_type', 'category', 'personnel_file', 'department')
        }),
        ('Berechtigung', {
            'fields': ('permission_level', 'inherit_to_children')
        }),
        ('Gültigkeit', {
            'fields': ('valid_from', 'valid_until'),
            'classes': ('collapse',)
        }),
    )
    
    def get_target(self, obj):
        return obj.user or obj.group
    get_target.short_description = 'Berechtigter'
    
    def get_object(self, obj):
        return obj.category or obj.personnel_file or obj.department
    get_object.short_description = 'Ziel'


@admin.register(AuditLog)
class AuditLogAdmin(ModelAdmin):
    list_display = ['timestamp', 'user', 'action_badge', 'document', 'personnel_file', 'ip_address']
    list_filter = [('action', ChoicesDropdownFilter), ('timestamp', RangeDateFilter), 'tenant']
    search_fields = ['user__username', 'document__title', 'personnel_file__file_number']
    readonly_fields = ['id', 'timestamp', 'user', 'ip_address', 'user_agent', 'action', 
                       'document', 'personnel_file', 'details', 'old_value', 'new_value', 'tenant']
    date_hierarchy = 'timestamp'
    
    @display(
        description="Aktion",
        label={
            "Erstellt": "success",
            "Angesehen": "info",
            "Heruntergeladen": "info",
            "Bearbeitet": "warning",
            "Gelöscht": "danger",
            "Archiviert": "secondary",
        }
    )
    def action_badge(self, obj):
        action_map = {
            'CREATE': 'Erstellt',
            'VIEW': 'Angesehen',
            'DOWNLOAD': 'Heruntergeladen',
            'EDIT': 'Bearbeitet',
            'DELETE': 'Gelöscht',
            'ARCHIVE': 'Archiviert',
            'RESTORE': 'Wiederhergestellt',
            'PERMISSION_CHANGE': 'Berechtigung geändert',
            'VERSION_CREATE': 'Version erstellt',
        }
        return action_map.get(obj.action, obj.action)
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ScanJob)
class ScanJobAdmin(ModelAdmin):
    list_display = ['id', 'source_badge', 'status_badge', 'progress_display', 'processed_files', 'total_files', 'started_at', 'completed_at']
    list_filter = [('status', ChoicesDropdownFilter), ('source', ChoicesDropdownFilter), ('started_at', RangeDateFilter)]
    readonly_fields = ['id', 'started_at', 'completed_at', 'progress_display']
    
    @display(
        description="Status",
        label={
            "Wartend": "secondary",
            "Läuft": "info",
            "Abgeschlossen": "success",
            "Fehlgeschlagen": "danger",
        }
    )
    def status_badge(self, obj):
        status_map = {
            'PENDING': 'Wartend',
            'RUNNING': 'Läuft',
            'COMPLETED': 'Abgeschlossen',
            'FAILED': 'Fehlgeschlagen',
        }
        return status_map.get(obj.status, obj.status)
    
    @display(
        description="Quelle",
        label={
            "Sage": "primary",
            "Manuell": "secondary",
            "E-Mail": "warning",
        }
    )
    def source_badge(self, obj):
        source_map = {
            'SAGE': 'Sage',
            'MANUAL': 'Manuell',
            'EMAIL': 'E-Mail',
        }
        return source_map.get(obj.source, obj.source)
    
    def progress_display(self, obj):
        return f"{obj.progress_percent}%"
    progress_display.short_description = 'Fortschritt'


@admin.register(Tag)
class TagAdmin(TenantFilterMixin, ModelAdmin):
    list_display = ['name', 'color_preview', 'parent', 'tenant', 'is_inbox_tag_badge', 'document_count']
    list_filter = ['tenant', 'is_inbox_tag']
    search_fields = ['name']
    
    @display(description="Inbox-Tag", label={"Ja": "warning", "Nein": "secondary"})
    def is_inbox_tag_badge(self, obj):
        return "Ja" if obj.is_inbox_tag else "Nein"
    
    def color_preview(self, obj):
        return format_html(
            '<span style="background-color: {}; padding: 2px 10px; border-radius: 3px;">&nbsp;</span> {}',
            obj.color, obj.color
        )
    color_preview.short_description = 'Farbe'
    
    def document_count(self, obj):
        return obj.tagged_documents.count()
    document_count.short_description = 'Dokumente'


@admin.register(DocumentTag)
class DocumentTagAdmin(ModelAdmin):
    list_display = ['document', 'tag', 'added_at', 'added_by']
    list_filter = ['tag', ('added_at', RangeDateFilter)]
    search_fields = ['document__title', 'tag__name']
    raw_id_fields = ['document', 'tag', 'added_by']


@admin.register(MatchingRule)
class MatchingRuleAdmin(TenantFilterMixin, ModelAdmin):
    list_display = ['name', 'algorithm_badge', 'is_active_badge', 'priority', 'match_count', 'last_matched_at', 'tenant']
    list_filter = ['tenant', 'is_active', ('algorithm', ChoicesDropdownFilter)]
    search_fields = ['name', 'match_pattern']
    
    @display(description="Status", label={"Aktiv": "success", "Inaktiv": "danger"})
    def is_active_badge(self, obj):
        return "Aktiv" if obj.is_active else "Inaktiv"
    
    @display(
        description="Algorithmus",
        label={
            "Keine": "secondary",
            "Beliebig": "info",
            "Alle": "primary",
            "Exakt": "success",
            "Regex": "warning",
            "Fuzzy": "danger",
        }
    )
    def algorithm_badge(self, obj):
        algo_map = {
            'NONE': 'Keine',
            'ANY': 'Beliebig',
            'ALL': 'Alle',
            'EXACT': 'Exakt',
            'REGEX': 'Regex',
            'FUZZY': 'Fuzzy',
        }
        return algo_map.get(obj.algorithm, obj.algorithm)
    
    fieldsets = (
        ('Regel', {
            'fields': ('name', 'is_active', 'priority', 'tenant')
        }),
        ('Matching', {
            'fields': ('algorithm', 'match_pattern', 'is_case_sensitive')
        }),
        ('Zuweisungen', {
            'fields': ('assign_document_type', 'assign_employee', 'assign_tags', 'assign_status')
        }),
        ('Statistik', {
            'fields': ('match_count', 'last_matched_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ['match_count', 'last_matched_at']


@admin.register(Reminder)
class ReminderAdmin(TenantFilterMixin, ModelAdmin):
    list_display = ['title', 'reminder_type_badge', 'due_date', 'status_badge', 'employee', 'days_display', 'tenant']
    list_filter = [
        ('status', ChoicesDropdownFilter),
        ('reminder_type', ChoicesDropdownFilter),
        'tenant',
        ('due_date', RangeDateFilter),
    ]
    search_fields = ['title', 'description', 'employee__first_name', 'employee__last_name']
    date_hierarchy = 'due_date'
    raw_id_fields = ['employee', 'document', 'assigned_to', 'completed_by', 'created_by']
    
    @display(description="Status", label={"Ausstehend": "warning", "Erledigt": "success", "Verworfen": "secondary"})
    def status_badge(self, obj):
        return obj.get_status_display()
    
    @display(
        description="Typ",
        label={
            "Vertragsablauf": "danger",
            "Probezeit-Ende": "warning",
            "Prüfung fällig": "info",
            "Zertifikat-Ablauf": "warning",
            "Aufbewahrungsfrist": "secondary",
            "Benutzerdefiniert": "primary",
        }
    )
    def reminder_type_badge(self, obj):
        return obj.get_reminder_type_display()
    
    @display(description="Verbleibend")
    def days_display(self, obj):
        if obj.status != 'PENDING':
            return "-"
        days = obj.days_until_due
        if days is None:
            return "-"
        if days < 0:
            return f"{abs(days)} Tage überfällig"
        elif days == 0:
            return "Heute"
        else:
            return f"in {days} Tagen"
    
    fieldsets = (
        ('Wiedervorlage', {
            'fields': ('title', 'description', 'reminder_type', 'tenant')
        }),
        ('Verknüpfung', {
            'fields': ('employee', 'document')
        }),
        ('Termin', {
            'fields': ('due_date', 'remind_days_before')
        }),
        ('Status', {
            'fields': ('status', 'completed_at', 'completed_by', 'assigned_to')
        }),
    )
