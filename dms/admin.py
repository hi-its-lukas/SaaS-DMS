from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Department, Employee, DocumentType, Document, 
    ProcessedFile, Task, EmailConfig, SystemLog
)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ['name', 'description', 'created_at']
    search_fields = ['name', 'description']


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ['employee_id', 'full_name', 'email', 'department', 'is_active']
    list_filter = ['is_active', 'department']
    search_fields = ['employee_id', 'first_name', 'last_name', 'email']
    raw_id_fields = ['user']


@admin.register(DocumentType)
class DocumentTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'description', 'retention_days', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'description']


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ['title', 'status', 'source', 'employee', 'document_type', 'file_size_display', 'created_at']
    list_filter = ['status', 'source', 'document_type', 'created_at']
    search_fields = ['title', 'original_filename', 'employee__first_name', 'employee__last_name']
    raw_id_fields = ['employee', 'owner']
    readonly_fields = ['id', 'sha256_hash', 'file_size', 'created_at', 'updated_at']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('id', 'title', 'original_filename', 'file_extension', 'mime_type')
        }),
        ('Classification', {
            'fields': ('document_type', 'employee', 'owner', 'status', 'source')
        }),
        ('Metadata', {
            'fields': ('metadata', 'notes', 'sha256_hash', 'file_size')
        }),
        ('Timestamps', {
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
    file_size_display.short_description = 'Size'
    
    actions = ['mark_as_archived', 'mark_as_review_needed']
    
    def mark_as_archived(self, request, queryset):
        queryset.update(status='ARCHIVED')
    mark_as_archived.short_description = "Mark selected as Archived"
    
    def mark_as_review_needed(self, request, queryset):
        queryset.update(status='REVIEW_NEEDED')
    mark_as_review_needed.short_description = "Mark selected as Review Needed"


@admin.register(ProcessedFile)
class ProcessedFileAdmin(admin.ModelAdmin):
    list_display = ['sha256_hash_short', 'original_path', 'processed_at', 'document']
    list_filter = ['processed_at']
    search_fields = ['sha256_hash', 'original_path']
    raw_id_fields = ['document']
    readonly_fields = ['sha256_hash', 'original_path', 'processed_at']
    
    def sha256_hash_short(self, obj):
        return f"{obj.sha256_hash[:16]}..."
    sha256_hash_short.short_description = 'SHA-256'


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['title', 'status', 'priority', 'assigned_to', 'due_date', 'created_at']
    list_filter = ['status', 'priority', 'created_at']
    search_fields = ['title', 'description']
    raw_id_fields = ['document', 'assigned_to', 'created_by']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Task Info', {
            'fields': ('title', 'description', 'document')
        }),
        ('Assignment', {
            'fields': ('assigned_to', 'created_by', 'priority', 'status')
        }),
        ('Dates', {
            'fields': ('due_date', 'completed_at', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ['created_at', 'updated_at', 'completed_at']
    
    actions = ['mark_as_completed', 'mark_as_open']
    
    def mark_as_completed(self, request, queryset):
        from django.utils import timezone
        queryset.update(status='COMPLETED', completed_at=timezone.now())
    mark_as_completed.short_description = "Mark selected as Completed"
    
    def mark_as_open(self, request, queryset):
        queryset.update(status='OPEN', completed_at=None)
    mark_as_open.short_description = "Mark selected as Open"


@admin.register(EmailConfig)
class EmailConfigAdmin(admin.ModelAdmin):
    list_display = ['name', 'target_mailbox', 'target_folder', 'is_active', 'last_sync']
    list_filter = ['is_active']
    search_fields = ['name', 'target_mailbox']
    readonly_fields = ['last_sync']
    
    fieldsets = (
        ('Configuration', {
            'fields': ('name', 'tenant_id', 'client_id', 'is_active')
        }),
        ('Mailbox Settings', {
            'fields': ('target_mailbox', 'target_folder')
        }),
        ('Status', {
            'fields': ('last_sync',),
            'classes': ('collapse',)
        }),
    )


@admin.register(SystemLog)
class SystemLogAdmin(admin.ModelAdmin):
    list_display = ['timestamp', 'level_colored', 'source', 'message_short']
    list_filter = ['level', 'source', 'timestamp']
    search_fields = ['message', 'source']
    readonly_fields = ['timestamp', 'level', 'source', 'message', 'details']
    date_hierarchy = 'timestamp'
    
    def level_colored(self, obj):
        colors = {
            'DEBUG': 'gray',
            'INFO': 'blue',
            'WARNING': 'orange',
            'ERROR': 'red',
            'CRITICAL': 'darkred',
        }
        color = colors.get(obj.level, 'black')
        return format_html('<span style="color: {};">{}</span>', color, obj.level)
    level_colored.short_description = 'Level'
    
    def message_short(self, obj):
        return obj.message[:100] + '...' if len(obj.message) > 100 else obj.message
    message_short.short_description = 'Message'
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False


admin.site.site_header = 'DMS Administration'
admin.site.site_title = 'Document Management System'
admin.site.index_title = 'Administration Dashboard'
