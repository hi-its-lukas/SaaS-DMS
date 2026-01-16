# Document Management System (DMS)

A production-ready Django-based Document Management System designed for HR and Corporate workflows.

## Overview

This DMS provides encrypted document storage, multi-channel input processing, and Microsoft 365 email integration. All documents are encrypted using Fernet symmetric encryption before storage.

## Project Structure

```
dms_project/           # Django project settings
  ├── settings.py      # Main configuration
  ├── celery.py        # Celery async task configuration
  └── urls.py          # URL routing

dms/                   # Main application
  ├── models.py        # Database models (Document, Employee, Task, etc.)
  ├── views.py         # Web views for upload, listing, download
  ├── tasks.py         # Celery background tasks
  ├── encryption.py    # Fernet encryption utilities
  ├── admin.py         # Django Admin configuration
  └── urls.py          # App URL patterns

templates/dms/         # HTML templates
data/                  # Data directories
  ├── sage_archive/    # Read-only Sage HR archive
  ├── manual_input/    # Manual scan input folder
  └── email_archive/   # Email storage
```

## Key Features

### Input Channels

1. **Sage HR Archive (Channel A)**: Idempotent import from read-only folder with SHA-256 hash checking
2. **Manual Input (Channel B)**: Consume-and-move pattern for scanner/user uploads
3. **Web Upload (Channel C)**: Drag-and-drop interface with AJAX upload

### Security

- All files encrypted with Fernet before database storage
- SHA-256 hash tracking to prevent duplicate imports
- Role-based permissions via Django Groups

### Document Workflow

- Status: UNASSIGNED, ASSIGNED, ARCHIVED, REVIEW_NEEDED
- DataMatrix barcode scanning for automatic employee assignment
- Task creation for review items

### Email Integration

- Microsoft Graph API via O365 library
- Automatic email-to-PDF conversion
- Attachment extraction and storage

## Environment Variables

- `DATABASE_URL`: PostgreSQL connection string
- `ENCRYPTION_KEY`: Fernet encryption key (generate with `Fernet.generate_key()`)
- `REDIS_URL`: Redis connection for Celery (optional in Replit)
- `SAGE_ARCHIVE_PATH`: Path to Sage HR archive folder
- `MANUAL_INPUT_PATH`: Path to manual input folder
- `EMAIL_ARCHIVE_PATH`: Path to email archive folder

## Admin Access

- URL: `/admin/`
- Username: `admin`
- Password: `admin123`

## Running Celery Tasks

For background processing, run Celery worker and beat:

```bash
celery -A dms_project worker -l INFO
celery -A dms_project beat -l INFO
```

## Docker Deployment

See `docker-compose.yml` for full containerized deployment including:
- Django web server
- PostgreSQL database
- Redis message broker
- Celery worker and beat
- Samba file shares
- Nginx reverse proxy

## Recent Changes

- Initial implementation with all core features
- Django 5.2 with Celery integration
- Full encryption implementation
- Admin interface configured
