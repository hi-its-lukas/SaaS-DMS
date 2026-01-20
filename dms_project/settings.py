import os
import sys
from pathlib import Path
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

_secret_key = os.environ.get('DJANGO_SECRET_KEY', '')
if not _secret_key:
    if os.environ.get('DEBUG', 'False').lower() == 'true':
        _secret_key = 'dev-only-insecure-key-not-for-production'
    else:
        print("FEHLER: DJANGO_SECRET_KEY muss in Production gesetzt sein!")
        print("Generieren mit: python -c \"from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())\"")
        sys.exit(1)
SECRET_KEY = _secret_key

DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'

_allowed_hosts = os.environ.get('ALLOWED_HOSTS', '')
if _allowed_hosts:
    ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts.split(',') if h.strip()]
elif DEBUG:
    ALLOWED_HOSTS = ['localhost', '127.0.0.1', '.replit.dev', '.repl.co', '*']
else:
    print("FEHLER: ALLOWED_HOSTS muss in Production gesetzt sein!")
    sys.exit(1)

_csrf_origins = [
    'https://*.replit.dev', 
    'https://*.repl.co',
    'https://*.azurecontainerapps.io',
    'https://*.westeurope.azurecontainerapps.io',
]
if os.environ.get('CSRF_TRUSTED_ORIGINS'):
    _csrf_origins.extend([o.strip() for o in os.environ.get('CSRF_TRUSTED_ORIGINS').split(',') if o.strip()])
CSRF_TRUSTED_ORIGINS = _csrf_origins

X_FRAME_OPTIONS = 'SAMEORIGIN'

INSTALLED_APPS = [
    'unfold',
    'unfold.contrib.filters',
    'unfold.contrib.forms',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_celery_beat',
    'storages',
    'mfa',
    'dms',
]

UNFOLD = {
    "SITE_TITLE": "DMS",
    "SITE_HEADER": "Dokumentenmanagementsystem",
    "SITE_SYMBOL": "description",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
    "ENVIRONMENT": "dms_project.settings.environment_callback",
    "DASHBOARD_CALLBACK": "dms.admin.dashboard_callback",
    "COLORS": {
        "primary": {
            "50": "#e6f5ed",
            "100": "#b3e0c9",
            "200": "#80cba6",
            "300": "#4db682",
            "400": "#26a66a",
            "500": "#007e45",
            "600": "#00713e",
            "700": "#006236",
            "800": "#00532e",
            "900": "#003d22",
            "950": "#002915",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": True,
        "navigation": [
            {
                "title": "Dashboard",
                "separator": False,
                "items": [
                    {
                        "title": "Dashboard",
                        "icon": "dashboard",
                        "link": "/",
                    },
                ],
            },
            {
                "title": "Dokumentenverwaltung",
                "separator": True,
                "items": [
                    {
                        "title": "Dokumente",
                        "icon": "description",
                        "link": "/admin/dms/document/",
                    },
                    {
                        "title": "Personalakten",
                        "icon": "folder_shared",
                        "link": "/admin/dms/personnelfile/",
                    },
                    {
                        "title": "Mitarbeiter",
                        "icon": "badge",
                        "link": "/admin/dms/employee/",
                    },
                ],
            },
            {
                "title": "Stammdaten",
                "separator": True,
                "items": [
                    {
                        "title": "Mandanten",
                        "icon": "domain",
                        "link": "/admin/dms/tenant/",
                        "permission": lambda request: request.user.is_superuser,
                    },
                    {
                        "title": "Abteilungen",
                        "icon": "apartment",
                        "link": "/admin/dms/department/",
                    },
                    {
                        "title": "Kostenstellen",
                        "icon": "account_balance",
                        "link": "/admin/dms/costcenter/",
                    },
                    {
                        "title": "Dokumenttypen",
                        "icon": "category",
                        "link": "/admin/dms/documenttype/",
                    },
                    {
                        "title": "Aktenkategorien",
                        "icon": "folder",
                        "link": "/admin/dms/filecategory/",
                    },
                ],
            },
            {
                "title": "System",
                "separator": True,
                "items": [
                    {
                        "title": "Benutzer",
                        "icon": "person",
                        "link": "/admin/auth/user/",
                    },
                    {
                        "title": "Gruppen",
                        "icon": "group",
                        "link": "/admin/auth/group/",
                    },
                    {
                        "title": "Systemeinstellungen",
                        "icon": "settings",
                        "link": "/admin/dms/systemsettings/",
                        "permission": lambda request: request.user.is_superuser,
                    },
                    {
                        "title": "Systemprotokolle",
                        "icon": "list_alt",
                        "link": "/admin/dms/systemlog/",
                        "permission": lambda request: request.user.is_superuser,
                    },
                    {
                        "title": "Scan-Aufträge",
                        "icon": "sync",
                        "link": "/admin/dms/scanjob/",
                    },
                ],
            },
        ],
    },
    "TABS": [
        {
            "models": ["dms.document"],
            "items": [
                {
                    "title": "Alle Dokumente",
                    "link": "/admin/dms/document/",
                },
                {
                    "title": "Inbox",
                    "link": "/admin/dms/document/?status__exact=UNASSIGNED",
                },
                {
                    "title": "Archiviert",
                    "link": "/admin/dms/document/?status__exact=ARCHIVED",
                },
            ],
        },
    ],
}


def environment_callback(request):
    """
    Callback to display environment badge in admin header.
    """
    if DEBUG:
        return ["Development", "warning"]
    return ["Production", "success"]


MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'dms.middleware.TenantMiddleware',
    'mfa.middleware.MFAEnforceMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'dms_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'dms_project.wsgi.application'

_database_url = os.environ.get('DATABASE_URL', '')
_use_azure_db = os.environ.get('DB_HOST') or (not _database_url) or ('://db:' in _database_url) or ('://db/' in _database_url)

if _use_azure_db:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'personalmappe'),
            'USER': os.environ.get('DB_USER', 'dmssaas'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', 'psql-personalmappe.postgres.database.azure.com'),
            'PORT': os.environ.get('DB_PORT', '5432'),
            'OPTIONS': {
                'sslmode': 'require',
            },
        }
    }
else:
    DATABASES = {
        'default': dj_database_url.config(default=_database_url)
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'de-de'
TIME_ZONE = 'Europe/Berlin'
USE_I18N = True
USE_TZ = True

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

AZURE_STORAGE_ENABLED = os.environ.get('AZURE_STORAGE_ACCOUNT_NAME') is not None

if AZURE_STORAGE_ENABLED:
    AZURE_ACCOUNT_NAME = os.environ.get('AZURE_STORAGE_ACCOUNT_NAME')
    AZURE_ACCOUNT_KEY = os.environ.get('AZURE_STORAGE_ACCOUNT_KEY')
    AZURE_CONTAINER = os.environ.get('AZURE_STORAGE_CONTAINER', 'documents')
    AZURE_CUSTOM_DOMAIN = os.environ.get('AZURE_STORAGE_CUSTOM_DOMAIN', None)
    
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.azure_storage.AzureStorage",
            "OPTIONS": {
                "account_name": AZURE_ACCOUNT_NAME,
                "account_key": AZURE_ACCOUNT_KEY,
                "azure_container": AZURE_CONTAINER,
                "custom_domain": AZURE_CUSTOM_DOMAIN,
                "expiration_secs": 3600,
            },
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }
else:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }
    MEDIA_URL = '/media/'
    MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CELERY_BROKER_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

AZURE_INGEST_CLIENT_ID = os.environ.get('AZURE_INGEST_CLIENT_ID')
AZURE_INGEST_CLIENT_SECRET = os.environ.get('AZURE_INGEST_CLIENT_SECRET')
AZURE_INGEST_TENANT_ID = os.environ.get('AZURE_INGEST_TENANT_ID')
AZURE_INGEST_MAILBOX = os.environ.get('AZURE_INGEST_MAILBOX', 'ingest@dms.cloud')

SAGE_ARCHIVE_PATH = os.environ.get('SAGE_ARCHIVE_PATH', str(BASE_DIR / 'data' / 'sage_archive'))
MANUAL_INPUT_PATH = os.environ.get('MANUAL_INPUT_PATH', str(BASE_DIR / 'data' / 'manual_input'))
EMAIL_ARCHIVE_PATH = os.environ.get('EMAIL_ARCHIVE_PATH', str(BASE_DIR / 'data' / 'email_archive'))

ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY', None)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'dms': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}

MFA_DOMAIN = os.environ.get('MFA_DOMAIN', os.environ.get('REPLIT_DEV_DOMAIN', 'localhost'))
MFA_SITE_TITLE = "DMS - Dokumentenmanagementsystem"
MFA_METHODS = ["FIDO2", "TOTP", "recovery"]
MFA_FIDO2_USER_VERIFICATION = "preferred"

SITE_URL = os.environ.get('SITE_URL', f"https://{os.environ.get('REPLIT_DEV_DOMAIN', 'localhost:5000')}")

EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.office365.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True').lower() == 'true'
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@dms.cloud')

GDPR_CONSENT_VERSION = os.environ.get('GDPR_CONSENT_VERSION', '1.0')
MFA_MAX_KEYS_PER_ACCOUNT = 5
