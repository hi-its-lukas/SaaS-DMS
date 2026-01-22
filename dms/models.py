import uuid
from django.db import models
from django.contrib.auth.models import User, Group
from django.utils import timezone
from dms.managers import TenantAwareManager, TenantAwareManagerAllowNull


def document_upload_path(instance, filename):
    """
    Generate storage path for documents: tenant_code/year/month/uuid_filename
    Ensures tenant isolation and organized structure for Azure Blob Storage.
    """
    import datetime
    now = datetime.datetime.now()
    tenant_code = instance.tenant.code if instance.tenant else 'global'
    return f"documents/{tenant_code}/{now.year}/{now.month:02d}/{instance.id}_{filename}"


def version_upload_path(instance, filename):
    """
    Generate storage path for document versions.
    """
    import datetime
    now = datetime.datetime.now()
    doc = instance.document
    tenant_code = doc.tenant.code if doc.tenant else 'global'
    return f"versions/{tenant_code}/{now.year}/{now.month:02d}/{instance.id}_{filename}"


class Company(models.Model):
    """
    Represents a customer organization (Kunde/Unternehmen).
    Root-Admin creates companies and assigns license limits.
    Company admins can then create their own Tenants (Mandanten).
    """
    ONBOARDING_STATUS_CHOICES = [
        ('CREATED', 'Erstellt'),
        ('INVITED', 'Einladung gesendet'),
        ('ACTIVE', 'Aktiv'),
        ('SUSPENDED', 'Gesperrt'),
    ]
    
    # System-generated unique identifier
    system_id = models.UUIDField(
        default=uuid.uuid4, 
        editable=False, 
        unique=True,
        verbose_name="System-ID",
        help_text="Automatisch generierter eindeutiger Identifier"
    )
    
    name = models.CharField(max_length=200, verbose_name="Firmenname")
    description = models.TextField(blank=True, verbose_name="Beschreibung")
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")
    
    # License limits (for billing/pricing)
    license_max_mandanten = models.PositiveIntegerField(
        default=1,
        verbose_name="Max. Mandanten",
        help_text="Maximale Anzahl an Mandanten für diesen Kunden"
    )
    license_max_users = models.PositiveIntegerField(
        default=5,
        verbose_name="Max. Benutzer",
        help_text="Maximale Anzahl an Benutzern für diesen Kunden"
    )
    license_max_personnel_files = models.PositiveIntegerField(
        default=100,
        verbose_name="Max. Personalakten",
        help_text="Maximale Anzahl an Personalakten für diesen Kunden"
    )
    
    # Onboarding
    onboarding_status = models.CharField(
        max_length=20,
        choices=ONBOARDING_STATUS_CHOICES,
        default='CREATED',
        verbose_name="Onboarding-Status"
    )
    contact_email = models.EmailField(
        blank=True,
        verbose_name="Kontakt-E-Mail",
        help_text="E-Mail des Unternehmens-Administrators"
    )
    contact_name = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Kontaktperson"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_companies',
        verbose_name="Erstellt von"
    )
    
    class Meta:
        ordering = ['name']
        verbose_name = "Unternehmen"
        verbose_name_plural = "Unternehmen"
    
    def __str__(self):
        return self.name
    
    @property
    def current_mandanten_count(self):
        """Returns the current number of Mandanten for this company."""
        return self.tenants.filter(is_active=True).count()
    
    @property
    def current_users_count(self):
        """Returns the current number of Users across all Mandanten."""
        from django.db.models import Count
        return TenantUser.objects.filter(
            tenant__company=self,
            tenant__is_active=True
        ).values('user').distinct().count()
    
    @property
    def current_personnel_files_count(self):
        """Returns the current number of PersonnelFiles across all Mandanten."""
        return PersonnelFile.objects.filter(
            tenant__company=self,
            tenant__is_active=True
        ).count()
    
    @property
    def license_mandanten_remaining(self):
        return max(0, self.license_max_mandanten - self.current_mandanten_count)
    
    @property
    def license_users_remaining(self):
        return max(0, self.license_max_users - self.current_users_count)
    
    @property
    def license_personnel_files_remaining(self):
        return max(0, self.license_max_personnel_files - self.current_personnel_files_count)


class Tenant(models.Model):
    """
    Represents a Mandant within a Company.
    Company admins can create multiple Tenants under their company.
    The code field is optional and only used for Sage document import.
    """
    
    # Link to Company (the parent organization)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='tenants',
        verbose_name="Unternehmen",
        null=True,  # Temporarily nullable for migration
        blank=True
    )
    
    # Sage-Code is now OPTIONAL - only needed for Sage import
    code = models.CharField(
        max_length=20, 
        unique=True, 
        null=True,
        blank=True,
        verbose_name="Sage-Mandanten-Code",
        help_text="Optional: Sage-Ordnername für Import (z.B. 0000001)"
    )
    name = models.CharField(max_length=200, verbose_name="Mandantenname")
    description = models.TextField(blank=True, verbose_name="Beschreibung")
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")
    
    ingest_token = models.CharField(
        max_length=12, 
        unique=True, 
        db_index=True,
        null=True,
        blank=True,
        verbose_name="Ingest-Token",
        help_text="Token für E-Mail-Routing (upload.<token>@dms.cloud)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='created_tenants',
        verbose_name="Erstellt von"
    )

    def __str__(self):
        if self.code:
            return f"{self.code} - {self.name}"
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.ingest_token:
            import secrets
            self.ingest_token = secrets.token_hex(6)
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['code']
        verbose_name = "Mandant"
        verbose_name_plural = "Mandanten"


class TenantInvite(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Ausstehend'),
        ('ACCEPTED', 'Angenommen'),
        ('EXPIRED', 'Abgelaufen'),
        ('REVOKED', 'Widerrufen'),
    ]
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='invites')
    email = models.EmailField(verbose_name="E-Mail-Adresse")
    name = models.CharField(max_length=200, blank=True, verbose_name="Name")
    
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    expires_at = models.DateTimeField(verbose_name="Gültig bis")
    
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True,
        related_name='sent_invites',
        verbose_name="Erstellt von"
    )
    
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='accepted_invites',
        verbose_name="Angenommen von"
    )
    
    class Meta:
        verbose_name = "Mandanten-Einladung"
        verbose_name_plural = "Mandanten-Einladungen"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Einladung für {self.email} @ {self.tenant.code}"
    
    @property
    def is_valid(self):
        from django.utils import timezone
        return self.status == 'PENDING' and self.expires_at > timezone.now()
    
    @classmethod
    def create_invite(cls, tenant, email, name, created_by, expires_days=7):
        import secrets
        import hashlib
        from django.utils import timezone
        from datetime import timedelta
        
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        
        invite = cls.objects.create(
            tenant=tenant,
            email=email,
            name=name,
            token_hash=token_hash,
            expires_at=timezone.now() + timedelta(days=expires_days),
            created_by=created_by,
        )
        return invite, raw_token
    
    @classmethod
    def validate_token(cls, raw_token):
        import hashlib
        from django.utils import timezone
        
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        try:
            invite = cls.objects.get(token_hash=token_hash)
            if invite.status != 'PENDING':
                return None, "Einladung wurde bereits verwendet oder widerrufen."
            if invite.expires_at < timezone.now():
                invite.status = 'EXPIRED'
                invite.save(update_fields=['status'])
                return None, "Einladung ist abgelaufen."
            return invite, None
        except cls.DoesNotExist:
            return None, "Ungültiger Einladungslink."


class TenantUser(models.Model):
    ROLE_CHOICES = [
        ('ADMIN', 'Administrator'),
        ('USER', 'Benutzer'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tenant_memberships')
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='users')
    is_admin = models.BooleanField(default=False, verbose_name="Mandanten-Admin")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='USER', verbose_name="Rolle")
    
    consent_given_at = models.DateTimeField(null=True, blank=True, verbose_name="Einwilligung erteilt am")
    consent_version = models.CharField(max_length=20, blank=True, verbose_name="Einwilligungsversion")
    consent_ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP bei Einwilligung")
    
    invited_via = models.ForeignKey(
        TenantInvite, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        verbose_name="Eingeladen über"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'tenant']
        verbose_name = "Mandanten-Benutzer"
        verbose_name_plural = "Mandanten-Benutzer"

    def __str__(self):
        return f"{self.user.username} @ {self.tenant.code}"


class Department(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='departments', null=True, blank=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantAwareManagerAllowNull()
    all_objects = models.Manager()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'name'], name='unique_department_per_tenant')
        ]


class CostCenter(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='cost_centers', null=True, blank=True)
    code = models.CharField(max_length=50)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantAwareManagerAllowNull()
    all_objects = models.Manager()

    def __str__(self):
        return f"{self.code} - {self.name}"

    class Meta:
        ordering = ['code']
        verbose_name = "Kostenstelle"
        verbose_name_plural = "Kostenstellen"
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'code'], name='unique_costcenter_per_tenant')
        ]


class Employee(models.Model):
    STATUS_CHOICES = [
        ('ACTIVE', 'Aktiv'),
        ('ONBOARDING', 'Onboarding'),
        ('OFFBOARDING', 'Offboarding'),
        ('ARCHIVED', 'Archiviert'),
    ]
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='employees', null=True, blank=True)
    employee_id = models.CharField(max_length=50, verbose_name="Mitarbeiter-ID")
    sage_cloud_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="Sage Cloud ID")
    first_name = models.CharField(max_length=100, verbose_name="Vorname")
    last_name = models.CharField(max_length=100, verbose_name="Nachname")
    email = models.EmailField(blank=True)
    job_title = models.CharField(max_length=200, blank=True, verbose_name="Position/Jobtitel")
    photo = models.ImageField(upload_to='employee_photos/', blank=True, null=True, verbose_name="Foto")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Abteilung")
    cost_center = models.ForeignKey(CostCenter, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Kostenstelle")
    entry_date = models.DateField(null=True, blank=True, verbose_name="Eintrittsdatum")
    exit_date = models.DateField(null=True, blank=True, verbose_name="Austrittsdatum")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE', verbose_name="Status")
    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='employee_profile')
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantAwareManager()
    all_objects = models.Manager()

    def __str__(self):
        return f"{self.employee_id} - {self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    @property
    def status_display(self):
        return dict(self.STATUS_CHOICES).get(self.status, self.status)

    class Meta:
        ordering = ['last_name', 'first_name']
        verbose_name = "Mitarbeiter"
        verbose_name_plural = "Mitarbeiter"
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'employee_id'], name='unique_employee_per_tenant')
        ]


class DocumentType(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='document_types', null=True, blank=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    required_fields = models.JSONField(default=dict, blank=True, help_text="JSON schema for required metadata fields")
    retention_days = models.PositiveIntegerField(default=0, help_text="Days to retain document (0 = forever)")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    file_category = models.ForeignKey(
        'FileCategory', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='document_types',
        verbose_name="Aktenkategorie",
        help_text="Zuordnung zum Aktenplan - Dokumente dieses Typs werden automatisch in diese Unterakte einsortiert"
    )

    objects = TenantAwareManagerAllowNull()
    all_objects = models.Manager()

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'name'], name='unique_documenttype_per_tenant')
        ]


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
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='documents', null=True, blank=True)
    title = models.CharField(max_length=255)
    original_filename = models.CharField(max_length=255)
    file_extension = models.CharField(max_length=20)
    mime_type = models.CharField(max_length=100, blank=True)
    file = models.FileField(
        upload_to=document_upload_path,
        blank=True,
        null=True,
        verbose_name="Datei",
        help_text="Dokument-Datei (Azure Blob Storage in Production)"
    )
    file_size = models.PositiveIntegerField(default=0)
    
    document_type = models.ForeignKey(DocumentType, on_delete=models.SET_NULL, null=True, blank=True)
    employee = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='documents')
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_documents')
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='UNASSIGNED')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='WEB')
    
    metadata = models.JSONField(default=dict, blank=True, help_text="Additional document metadata")
    notes = models.TextField(blank=True)
    
    sha256_hash = models.CharField(max_length=64, db_index=True, help_text="SHA-256 hash of original file")
    
    period_year = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True,
                                                   verbose_name="Periode Jahr",
                                                   help_text="Jahr der Periode (z.B. 2025)")
    period_month = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True,
                                                    verbose_name="Periode Monat",
                                                    help_text="Monat der Periode (1-12)")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.title} ({self.status})"

    def archive(self):
        self.status = 'ARCHIVED'
        self.archived_at = timezone.now()
        self.save()

    @property
    def file_size_display(self):
        """Human-readable file size."""
        if not self.file_size:
            return "0 B"
        size = self.file_size
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.2f} MB"

    @property
    def period_display(self):
        """Formatted period display (e.g., '01/2025')."""
        if self.period_month and self.period_year:
            return f"{self.period_month:02d}/{self.period_year}"
        return "-"

    objects = TenantAwareManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ['-created_at']
        permissions = [
            ("view_all_documents", "Can view all documents"),
            ("manage_documents", "Can manage all documents"),
        ]


class ProcessedFile(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='processed_files', null=True, blank=True)
    sha256_hash = models.CharField(max_length=64, db_index=True)
    original_path = models.CharField(max_length=500)
    processed_at = models.DateTimeField(auto_now_add=True)
    document = models.ForeignKey(Document, on_delete=models.SET_NULL, null=True, blank=True)

    objects = TenantAwareManager()
    all_objects = models.Manager()

    def __str__(self):
        return f"{self.sha256_hash[:16]}... - {self.original_path}"

    class Meta:
        ordering = ['-processed_at']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'sha256_hash'], name='unique_processed_file_per_tenant')
        ]


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
        verbose_name = "Systemprotokoll"
        verbose_name_plural = "Systemprotokolle"


class ScanJob(models.Model):
    """Tracks scan job progress for dashboard display"""
    STATUS_CHOICES = [
        ('PENDING', 'Wartend'),
        ('RUNNING', 'Läuft'),
        ('COMPLETED', 'Abgeschlossen'),
        ('FAILED', 'Fehlgeschlagen'),
    ]
    
    SOURCE_CHOICES = [
        ('SAGE', 'Sage Archiv'),
        ('MANUAL', 'Manuelle Eingabe'),
        ('EMAIL', 'E-Mail'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    
    total_files = models.PositiveIntegerField(default=0)
    processed_files = models.PositiveIntegerField(default=0)
    skipped_files = models.PositiveIntegerField(default=0)
    error_files = models.PositiveIntegerField(default=0)
    
    current_file = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)
    
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    @property
    def progress_percent(self):
        if self.total_files == 0:
            return 0
        percent = int((self.processed_files + self.error_files) / self.total_files * 100)
        return min(percent, 100)
    
    @property
    def is_running(self):
        return self.status == 'RUNNING'
    
    @property
    def duration_seconds(self):
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
    
    def __str__(self):
        return f"{self.get_source_display()} - {self.get_status_display()} ({self.progress_percent}%)"
    
    class Meta:
        ordering = ['-started_at']
        verbose_name = "Scan-Auftrag"
        verbose_name_plural = "Scan-Aufträge"


class SystemSettings(models.Model):
    """Singleton model for system-wide configuration - editable via Django Admin"""
    
    sage_cloud_api_url = models.URLField(
        blank=True, 
        verbose_name="Sage Cloud API URL",
        help_text="z.B. https://mycompany.sage.hr/api"
    )
    encrypted_sage_cloud_api_key = models.BinaryField(blank=True, null=True, verbose_name="Sage Cloud API-Schlüssel (verschlüsselt)")
    
    ms_graph_tenant_id = models.CharField(max_length=100, blank=True, verbose_name="MS Graph Tenant ID")
    ms_graph_client_id = models.CharField(max_length=100, blank=True, verbose_name="MS Graph Client ID")
    encrypted_ms_graph_secret = models.BinaryField(blank=True, null=True, verbose_name="MS Graph Secret (verschlüsselt)")
    
    samba_username = models.CharField(
        max_length=50, 
        default="dmsuser",
        verbose_name="Samba Benutzername",
        help_text="Benutzername für Netzwerkfreigaben"
    )
    encrypted_samba_password = models.BinaryField(
        blank=True, 
        null=True, 
        verbose_name="Samba Passwort (verschlüsselt)"
    )
    
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def load(cls):
        """
        Lädt die Singleton-Instanz thread-safe.
        Verwendet get_or_create mit atomarem Lock.
        """
        from django.db import transaction
        
        try:
            return cls.objects.get(pk=1)
        except cls.DoesNotExist:
            with transaction.atomic():
                obj, _ = cls.objects.select_for_update().get_or_create(pk=1)
                return obj
    
    @classmethod
    def load_for_update(cls):
        """
        Lädt die Singleton-Instanz mit exklusivem Lock für Änderungen.
        Muss innerhalb einer transaction.atomic() Block verwendet werden.
        """
        from django.db import transaction
        
        with transaction.atomic():
            obj, _ = cls.objects.select_for_update().get_or_create(pk=1)
            return obj

    def __str__(self):
        return "Systemeinstellungen"

    class Meta:
        verbose_name = "Systemeinstellung"
        verbose_name_plural = "Systemeinstellungen"


class ImportedLeaveRequest(models.Model):
    """Tracks imported leave requests from Sage Cloud to prevent duplicates"""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='leave_requests', null=True, blank=True)
    sage_request_id = models.CharField(max_length=100, verbose_name="Sage Anfrage-ID")
    
    objects = TenantAwareManager()
    all_objects = models.Manager()
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_requests')
    document = models.ForeignKey('Document', on_delete=models.SET_NULL, null=True, blank=True)
    
    leave_type = models.CharField(max_length=100, verbose_name="Urlaubsart")
    start_date = models.DateField(verbose_name="Startdatum")
    end_date = models.DateField(verbose_name="Enddatum")
    days_count = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Anzahl Tage")
    approval_date = models.DateField(null=True, blank=True, verbose_name="Genehmigungsdatum")
    approved_by = models.CharField(max_length=200, blank=True, verbose_name="Genehmigt von")
    
    raw_data = models.JSONField(default=dict, verbose_name="Rohdaten")
    imported_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.employee} - {self.leave_type} ({self.start_date} - {self.end_date})"

    class Meta:
        ordering = ['-start_date']
        verbose_name = "Importierter Urlaubsantrag"
        verbose_name_plural = "Importierte Urlaubsanträge"
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'sage_request_id'], name='unique_leaverequest_per_tenant')
        ]


class ImportedTimesheet(models.Model):
    """Tracks imported monthly timesheets from Sage Cloud"""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='timesheets', null=True, blank=True)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='timesheets')
    
    objects = TenantAwareManager()
    all_objects = models.Manager()
    document = models.ForeignKey('Document', on_delete=models.SET_NULL, null=True, blank=True)
    
    year = models.PositiveIntegerField(verbose_name="Jahr")
    month = models.PositiveIntegerField(verbose_name="Monat")
    
    total_hours = models.DecimalField(max_digits=6, decimal_places=2, default=0, verbose_name="Gesamtstunden")
    overtime_hours = models.DecimalField(max_digits=6, decimal_places=2, default=0, verbose_name="Überstunden")
    
    raw_data = models.JSONField(default=dict, verbose_name="Rohdaten")
    imported_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.employee} - {self.month:02d}/{self.year}"

    class Meta:
        ordering = ['-year', '-month']
        unique_together = ['employee', 'year', 'month']
        verbose_name = "Importierte Zeiterfassung"
        verbose_name_plural = "Importierte Zeiterfassungen"


class FileCategory(models.Model):
    """Aktenplan - Kategorien mit Aufbewahrungsfristen (wie d.3 one)"""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='file_categories', null=True, blank=True)
    code = models.CharField(max_length=20, verbose_name="Aktenzeichen")
    
    objects = TenantAwareManagerAllowNull()
    all_objects = models.Manager()
    name = models.CharField(max_length=200, verbose_name="Bezeichnung")
    description = models.TextField(blank=True, verbose_name="Beschreibung")
    parent = models.ForeignKey(
        'self', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='subcategories',
        verbose_name="Übergeordnete Kategorie"
    )
    
    retention_years = models.PositiveIntegerField(
        default=10, 
        verbose_name="Aufbewahrungsfrist (Jahre)",
        help_text="0 = unbegrenzt"
    )
    retention_trigger = models.CharField(
        max_length=50,
        choices=[
            ('CREATION', 'Ab Erstellung'),
            ('EXIT', 'Ab Austritt'),
            ('DOCUMENT_DATE', 'Ab Dokumentdatum'),
        ],
        default='EXIT',
        verbose_name="Fristbeginn"
    )
    
    is_mandatory = models.BooleanField(default=False, verbose_name="Pflichtakte")
    sort_order = models.PositiveIntegerField(default=0, verbose_name="Sortierung")
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.code} - {self.name}"
    
    def get_full_path(self):
        if self.parent:
            return f"{self.parent.get_full_path()} / {self.name}"
        return self.name

    class Meta:
        ordering = ['sort_order', 'code']
        verbose_name = "Aktenkategorie"
        verbose_name_plural = "Aktenkategorien (Aktenplan)"
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'code'], name='unique_filecategory_per_tenant')
        ]


class PersonnelFile(models.Model):
    """Personalakte - Container für alle Dokumente eines Mitarbeiters"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='personnel_files', null=True, blank=True)
    
    objects = TenantAwareManager()
    all_objects = models.Manager()
    
    employee = models.OneToOneField(
        Employee, 
        on_delete=models.CASCADE, 
        related_name='personnel_file',
        verbose_name="Mitarbeiter"
    )
    
    file_number = models.CharField(
        max_length=50, 
        verbose_name="Aktenzeichen",
        help_text="Eindeutige Aktennummer"
    )
    
    STATUS_CHOICES = [
        ('ACTIVE', 'Aktiv'),
        ('INACTIVE', 'Inaktiv (ausgeschieden)'),
        ('ARCHIVED', 'Archiviert'),
        ('DELETED', 'Zur Löschung vorgemerkt'),
    ]
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='ACTIVE',
        verbose_name="Status"
    )
    
    opened_at = models.DateField(auto_now_add=True, verbose_name="Eröffnungsdatum")
    closed_at = models.DateField(null=True, blank=True, verbose_name="Schließungsdatum")
    retention_until = models.DateField(null=True, blank=True, verbose_name="Aufbewahren bis")
    
    notes = models.TextField(blank=True, verbose_name="Bemerkungen")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.file_number} - {self.employee.full_name}"
    
    def document_count(self):
        return self.file_entries.count()
    document_count.short_description = "Dokumente"

    class Meta:
        ordering = ['file_number']
        verbose_name = "Personalakte"
        verbose_name_plural = "Personalakten"
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'file_number'], name='unique_personnelfile_per_tenant')
        ]


class PersonnelFileEntry(models.Model):
    """Eintrag in einer Personalakte - verknüpft Dokument mit Akte und Kategorie"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    personnel_file = models.ForeignKey(
        PersonnelFile, 
        on_delete=models.CASCADE, 
        related_name='file_entries',
        verbose_name="Personalakte"
    )
    document = models.ForeignKey(
        Document, 
        on_delete=models.CASCADE, 
        related_name='file_entries',
        verbose_name="Dokument"
    )
    category = models.ForeignKey(
        FileCategory, 
        on_delete=models.PROTECT, 
        related_name='file_entries',
        verbose_name="Kategorie"
    )
    
    entry_number = models.PositiveIntegerField(verbose_name="Laufende Nr.")
    entry_date = models.DateField(default=timezone.now, verbose_name="Eintragsdatum")
    document_date = models.DateField(null=True, blank=True, verbose_name="Dokumentdatum")
    
    notes = models.TextField(blank=True, verbose_name="Bemerkungen")
    
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='created_file_entries',
        verbose_name="Erstellt von"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.personnel_file.file_number}/{self.entry_number} - {self.document.title}"

    def save(self, *args, **kwargs):
        if not self.entry_number:
            last_entry = PersonnelFileEntry.objects.filter(
                personnel_file=self.personnel_file
            ).order_by('-entry_number').first()
            self.entry_number = (last_entry.entry_number + 1) if last_entry else 1
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['personnel_file', '-entry_number']
        unique_together = ['personnel_file', 'entry_number']
        verbose_name = "Akteneintrag"
        verbose_name_plural = "Akteneinträge"


class DocumentVersion(models.Model):
    """Dokumentenversion - speichert alle Versionen eines Dokuments"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        Document, 
        on_delete=models.CASCADE, 
        related_name='versions',
        verbose_name="Dokument"
    )
    
    version_number = models.PositiveIntegerField(verbose_name="Versionsnummer")
    file = models.FileField(
        upload_to=version_upload_path,
        blank=True,
        null=True,
        verbose_name="Datei"
    )
    file_size = models.PositiveIntegerField(default=0, verbose_name="Dateigröße")
    sha256_hash = models.CharField(max_length=64, verbose_name="SHA-256 Hash")
    
    change_reason = models.CharField(max_length=500, blank=True, verbose_name="Änderungsgrund")
    
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True,
        verbose_name="Erstellt von"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.document.title} v{self.version_number}"

    class Meta:
        ordering = ['document', '-version_number']
        unique_together = ['document', 'version_number']
        verbose_name = "Dokumentenversion"
        verbose_name_plural = "Dokumentenversionen"


class AccessPermission(models.Model):
    """Zugriffsrechte auf Akten und Kategorien"""
    PERMISSION_CHOICES = [
        ('VIEW', 'Ansehen'),
        ('EDIT', 'Bearbeiten'),
        ('DELETE', 'Löschen'),
        ('ADMIN', 'Vollzugriff'),
    ]
    
    TARGET_TYPE_CHOICES = [
        ('CATEGORY', 'Kategorie'),
        ('PERSONNEL_FILE', 'Personalakte'),
        ('DEPARTMENT', 'Abteilung'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='access_permissions', null=True, blank=True)
    
    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='dms_permissions',
        verbose_name="Benutzer"
    )
    group = models.ForeignKey(
        'auth.Group', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='dms_permissions',
        verbose_name="Gruppe"
    )
    
    target_type = models.CharField(
        max_length=20, 
        choices=TARGET_TYPE_CHOICES,
        verbose_name="Zieltyp"
    )
    
    category = models.ForeignKey(
        FileCategory, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='permissions',
        verbose_name="Kategorie"
    )
    personnel_file = models.ForeignKey(
        PersonnelFile, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='permissions',
        verbose_name="Personalakte"
    )
    department = models.ForeignKey(
        Department, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='permissions',
        verbose_name="Abteilung"
    )
    
    permission_level = models.CharField(
        max_length=20, 
        choices=PERMISSION_CHOICES, 
        default='VIEW',
        verbose_name="Berechtigungsstufe"
    )
    
    inherit_to_children = models.BooleanField(
        default=True, 
        verbose_name="Auf Unterordner vererben"
    )
    
    valid_from = models.DateField(null=True, blank=True, verbose_name="Gültig ab")
    valid_until = models.DateField(null=True, blank=True, verbose_name="Gültig bis")
    
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True,
        related_name='created_permissions',
        verbose_name="Erstellt von"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        target = self.user or self.group
        obj = self.category or self.personnel_file or self.department
        return f"{target} → {obj}: {self.get_permission_level_display()}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if not self.user and not self.group:
            raise ValidationError("Entweder Benutzer oder Gruppe muss angegeben werden.")
        if self.user and self.group:
            raise ValidationError("Nur Benutzer ODER Gruppe angeben, nicht beides.")

    class Meta:
        ordering = ['target_type', 'permission_level']
        verbose_name = "Zugriffsberechtigung"
        verbose_name_plural = "Zugriffsberechtigungen"


class AuditLog(models.Model):
    """Revisionssichere Protokollierung aller Aktionen"""
    ACTION_CHOICES = [
        ('CREATE', 'Erstellt'),
        ('VIEW', 'Angesehen'),
        ('DOWNLOAD', 'Heruntergeladen'),
        ('EDIT', 'Bearbeitet'),
        ('DELETE', 'Gelöscht'),
        ('ARCHIVE', 'Archiviert'),
        ('RESTORE', 'Wiederhergestellt'),
        ('PERMISSION_CHANGE', 'Berechtigung geändert'),
        ('VERSION_CREATE', 'Version erstellt'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='audit_logs', null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="Zeitstempel")
    
    user = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True,
        verbose_name="Benutzer"
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP-Adresse")
    user_agent = models.CharField(max_length=500, blank=True, verbose_name="User-Agent")
    
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, verbose_name="Aktion")
    
    document = models.ForeignKey(
        Document, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='audit_logs',
        verbose_name="Dokument"
    )
    personnel_file = models.ForeignKey(
        PersonnelFile, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='audit_logs',
        verbose_name="Personalakte"
    )
    
    details = models.JSONField(default=dict, blank=True, verbose_name="Details")
    old_value = models.TextField(blank=True, verbose_name="Alter Wert")
    new_value = models.TextField(blank=True, verbose_name="Neuer Wert")

    def __str__(self):
        return f"{self.timestamp} - {self.user} - {self.get_action_display()}"

    class Meta:
        ordering = ['-timestamp']
        verbose_name = "Audit-Protokoll"
        verbose_name_plural = "Audit-Protokolle"


class Tag(models.Model):
    """Paperless-ngx-style Tags für Dokumentenkategorisierung"""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='tags', null=True, blank=True)
    
    objects = TenantAwareManagerAllowNull()
    all_objects = models.Manager()
    
    name = models.CharField(max_length=100, verbose_name="Name")
    color = models.CharField(max_length=7, default="#3B82F6", verbose_name="Farbe",
                            help_text="Hex-Farbcode (z.B. #3B82F6)")
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True,
                               related_name='children', verbose_name="Übergeordneter Tag")
    is_inbox_tag = models.BooleanField(default=False, verbose_name="Inbox-Tag",
                                       help_text="Wird automatisch bei neuen Dokumenten gesetzt")
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        if self.parent:
            return f"{self.parent.name} > {self.name}"
        return self.name
    
    class Meta:
        ordering = ['name']
        verbose_name = "Tag"
        verbose_name_plural = "Tags"
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'name'], name='unique_tag_per_tenant')
        ]


class DocumentTag(models.Model):
    """Many-to-Many Verknüpfung zwischen Dokumenten und Tags"""
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='document_tags')
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name='tagged_documents')
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        unique_together = ['document', 'tag']
        verbose_name = "Dokument-Tag"
        verbose_name_plural = "Dokument-Tags"


class MatchingRule(models.Model):
    """Paperless-ngx-style Matching-Regeln für automatische Klassifizierung"""
    
    ALGORITHM_CHOICES = [
        ('NONE', 'Keine Zuordnung'),
        ('ANY', 'Beliebiges Wort'),
        ('ALL', 'Alle Wörter'),
        ('EXACT', 'Exakte Phrase'),
        ('REGEX', 'Regulärer Ausdruck'),
        ('FUZZY', 'Ähnlichkeitssuche'),
    ]
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='matching_rules', null=True, blank=True)
    
    objects = TenantAwareManager()
    all_objects = models.Manager()
    
    name = models.CharField(max_length=200, verbose_name="Regelname")
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")
    priority = models.IntegerField(default=0, verbose_name="Priorität",
                                   help_text="Höhere Werte = höhere Priorität")
    
    algorithm = models.CharField(max_length=20, choices=ALGORITHM_CHOICES, default='ANY',
                                 verbose_name="Algorithmus")
    match_pattern = models.TextField(verbose_name="Suchmuster",
                                    help_text="Suchbegriffe oder Regex-Pattern")
    is_case_sensitive = models.BooleanField(default=False, verbose_name="Groß-/Kleinschreibung beachten")
    
    # Was soll zugewiesen werden?
    assign_document_type = models.ForeignKey(DocumentType, on_delete=models.SET_NULL, 
                                             null=True, blank=True, verbose_name="Dokumenttyp zuweisen")
    assign_employee = models.ForeignKey(Employee, on_delete=models.SET_NULL,
                                        null=True, blank=True, verbose_name="Mitarbeiter zuweisen")
    assign_tags = models.ManyToManyField(Tag, blank=True, verbose_name="Tags zuweisen")
    assign_status = models.CharField(max_length=20, blank=True, verbose_name="Status setzen")
    
    # Statistik
    match_count = models.IntegerField(default=0, verbose_name="Anzahl Treffer")
    last_matched_at = models.DateTimeField(null=True, blank=True, verbose_name="Letzter Treffer")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.name} ({self.get_algorithm_display()})"
    
    def matches(self, text):
        """Prüft, ob der Text zur Regel passt"""
        import re
        
        if not text or not self.match_pattern:
            return False
        
        if not self.is_case_sensitive:
            text = text.lower()
            pattern = self.match_pattern.lower()
        else:
            pattern = self.match_pattern
        
        if self.algorithm == 'NONE':
            return False
        elif self.algorithm == 'EXACT':
            return pattern in text
        elif self.algorithm == 'ANY':
            words = pattern.split()
            return any(word in text for word in words)
        elif self.algorithm == 'ALL':
            words = pattern.split()
            return all(word in text for word in words)
        elif self.algorithm == 'REGEX':
            try:
                flags = 0 if self.is_case_sensitive else re.IGNORECASE
                return bool(re.search(self.match_pattern, text, flags))
            except re.error:
                return False
        elif self.algorithm == 'FUZZY':
            # Einfache Fuzzy-Suche: mindestens 80% der Wörter müssen vorkommen
            words = pattern.split()
            if not words:
                return False
            matches = sum(1 for word in words if word in text)
            return (matches / len(words)) >= 0.8
        
        return False
    
    class Meta:
        ordering = ['-priority', 'name']
        verbose_name = "Matching-Regel"
        verbose_name_plural = "Matching-Regeln"


class Reminder(models.Model):
    """Wiedervorlagen und Fristen für Dokumente und Mitarbeiter"""
    
    TYPE_CHOICES = [
        ('CONTRACT_EXPIRY', 'Vertragsablauf'),
        ('PROBATION_END', 'Probezeit-Ende'),
        ('REVIEW_DUE', 'Prüfung fällig'),
        ('CERTIFICATE_EXPIRY', 'Zertifikat-Ablauf'),
        ('RETENTION_EXPIRY', 'Aufbewahrungsfrist'),
        ('CUSTOM', 'Benutzerdefiniert'),
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Ausstehend'),
        ('COMPLETED', 'Erledigt'),
        ('DISMISSED', 'Verworfen'),
    ]
    
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='reminders', null=True, blank=True)
    
    objects = TenantAwareManagerAllowNull()
    all_objects = models.Manager()
    
    title = models.CharField(max_length=200, verbose_name="Titel")
    description = models.TextField(blank=True, verbose_name="Beschreibung")
    reminder_type = models.CharField(max_length=30, choices=TYPE_CHOICES, default='CUSTOM', verbose_name="Typ")
    
    employee = models.ForeignKey(
        Employee, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='reminders',
        verbose_name="Mitarbeiter"
    )
    document = models.ForeignKey(
        Document, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='reminders',
        verbose_name="Dokument"
    )
    
    due_date = models.DateField(verbose_name="Fälligkeitsdatum")
    remind_days_before = models.PositiveIntegerField(default=14, verbose_name="Tage vorher erinnern")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', verbose_name="Status")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="Erledigt am")
    completed_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='completed_reminders',
        verbose_name="Erledigt von"
    )
    
    assigned_to = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='assigned_reminders',
        verbose_name="Zugewiesen an"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='created_reminders',
        verbose_name="Erstellt von"
    )
    
    def __str__(self):
        return f"{self.title} - {self.due_date}"
    
    @property
    def is_overdue(self):
        from django.utils import timezone
        return self.status == 'PENDING' and self.due_date < timezone.now().date()
    
    @property
    def days_until_due(self):
        from django.utils import timezone
        if self.status != 'PENDING':
            return None
        return (self.due_date - timezone.now().date()).days
    
    class Meta:
        ordering = ['due_date', '-created_at']
        verbose_name = "Wiedervorlage"
        verbose_name_plural = "Wiedervorlagen"
