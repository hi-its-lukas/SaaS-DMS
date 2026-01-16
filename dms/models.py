import uuid
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class Employee(models.Model):
    employee_id = models.CharField(max_length=50, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True)
    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='employee_profile')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.employee_id} - {self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    class Meta:
        ordering = ['last_name', 'first_name']


class DocumentType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    required_fields = models.JSONField(default=dict, blank=True, help_text="JSON schema for required metadata fields")
    retention_days = models.PositiveIntegerField(default=0, help_text="Days to retain document (0 = forever)")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class Document(models.Model):
    STATUS_CHOICES = [
        ('UNASSIGNED', 'Unassigned/Inbox'),
        ('ASSIGNED', 'Assigned'),
        ('ARCHIVED', 'Archived'),
        ('REVIEW_NEEDED', 'Review Needed'),
    ]

    SOURCE_CHOICES = [
        ('SAGE', 'Sage HR Archive'),
        ('MANUAL', 'Manual Input'),
        ('WEB', 'Web Upload'),
        ('EMAIL', 'Email Import'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    original_filename = models.CharField(max_length=255)
    file_extension = models.CharField(max_length=20)
    mime_type = models.CharField(max_length=100, blank=True)
    encrypted_content = models.BinaryField(help_text="Fernet-encrypted file content")
    file_size = models.PositiveIntegerField(default=0)
    
    document_type = models.ForeignKey(DocumentType, on_delete=models.SET_NULL, null=True, blank=True)
    employee = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='documents')
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_documents')
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='UNASSIGNED')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='WEB')
    
    metadata = models.JSONField(default=dict, blank=True, help_text="Additional document metadata")
    notes = models.TextField(blank=True)
    
    sha256_hash = models.CharField(max_length=64, db_index=True, help_text="SHA-256 hash of original file")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.title} ({self.status})"

    def archive(self):
        self.status = 'ARCHIVED'
        self.archived_at = timezone.now()
        self.save()

    class Meta:
        ordering = ['-created_at']
        permissions = [
            ("view_all_documents", "Can view all documents"),
            ("manage_documents", "Can manage all documents"),
        ]


class ProcessedFile(models.Model):
    sha256_hash = models.CharField(max_length=64, unique=True, db_index=True)
    original_path = models.CharField(max_length=500)
    processed_at = models.DateTimeField(auto_now_add=True)
    document = models.ForeignKey(Document, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.sha256_hash[:16]}... - {self.original_path}"

    class Meta:
        ordering = ['-processed_at']


class Task(models.Model):
    PRIORITY_CHOICES = [
        (1, 'Low'),
        (2, 'Medium'),
        (3, 'High'),
        (4, 'Urgent'),
    ]

    STATUS_CHOICES = [
        ('OPEN', 'Open'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='tasks')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_tasks')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_tasks')
    
    priority = models.IntegerField(choices=PRIORITY_CHOICES, default=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN')
    
    due_date = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} - {self.get_status_display()}"

    def complete(self):
        self.status = 'COMPLETED'
        self.completed_at = timezone.now()
        self.save()

    class Meta:
        ordering = ['-priority', 'due_date', '-created_at']


class EmailConfig(models.Model):
    name = models.CharField(max_length=100, unique=True)
    tenant_id = models.CharField(max_length=100)
    client_id = models.CharField(max_length=100)
    encrypted_client_secret = models.BinaryField(help_text="Fernet-encrypted client secret")
    target_mailbox = models.EmailField(help_text="Email address to monitor")
    target_folder = models.CharField(max_length=100, default='Inbox')
    is_active = models.BooleanField(default=True)
    last_sync = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.target_mailbox}"

    class Meta:
        verbose_name = "Email Configuration"
        verbose_name_plural = "Email Configurations"


class SystemLog(models.Model):
    LEVEL_CHOICES = [
        ('DEBUG', 'Debug'),
        ('INFO', 'Info'),
        ('WARNING', 'Warning'),
        ('ERROR', 'Error'),
        ('CRITICAL', 'Critical'),
    ]

    timestamp = models.DateTimeField(auto_now_add=True)
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default='INFO')
    source = models.CharField(max_length=100)
    message = models.TextField()
    details = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"[{self.level}] {self.timestamp} - {self.source}"

    class Meta:
        ordering = ['-timestamp']
