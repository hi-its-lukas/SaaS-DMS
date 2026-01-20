# Dokumentenmanagementsystem (DMS) - SaaS Edition

## Overview

This project is a production-ready, Django-based Document Management System (DMS) designed for HR and general business operations. It functions as a multi-tenant SaaS solution, integrating with Sage HR Cloud and Microsoft 365, utilizing Azure Blob Storage for secure document storage. Key capabilities include multi-channel input processing, robust document management with features inspired by d.3 one and Paperless-ngx, and a focus on security and scalability. The system aims to streamline HR and administrative workflows by providing a centralized, secure, and automated document handling platform.

## User Preferences

I prefer iterative development where features are released incrementally. I want detailed explanations of complex architectural decisions and technical implementations. Before making any major changes to the database schema or core architecture, please ask for my approval. I expect the agent to prioritize secure and scalable solutions. I prefer that the agent communicates using clear and direct language.

## System Architecture

The DMS is built as a multi-tenant SaaS application using Django.

### Multi-Tenancy

- **Single URL Architecture**: All tenants access the system via a single URL (e.g., `app.dms.cloud`).
- **Tenant Isolation**: Achieved through `TenantMiddleware` (identifies tenant from logged-in user) and `TenantAwareManager` (automatically filters QuerySets by tenant). Thread-local storage maintains tenant context across requests.
- **Role-Based Access Control** (Blind Root-Admin Pattern):
    - **Root-Admin**: Sees ONLY tenant overview (Tenant, TenantInvite, TenantUser) and system settings. Cannot access documents, employees, or other tenant-specific data. Dashboard shows tenant counts and pending invites only.
    - **Tenant-Admin**: Manages data only for their specific tenant. Full access to documents, employees, and personnel files within their tenant.
    - **User**: Accesses documents within their assigned tenant only.
- **Data Security**: All core models include a `tenant` field. `TenantAwareManager` ensures automatic filtering of all database queries.

### Document Storage

- **Azure Blob Storage**: Documents are stored in Azure Blob Storage with a structured path: `documents/{tenant_code}/{year}/{month}/{uuid}_{filename}`.
- **Encryption**: Fernet encryption is used for all stored files, with API keys securely stored in the database.

### Admin Interface (django-unfold)

- **Modernized UI**: Utilizes `django-unfold` with a Sage-green theme (Primary color: #007e45).
- **Enhanced Features**: Includes status badges for relevant fields, dropdown filters with date range support, and a dashboard for KPI overview.

### Core Functionality

- **Input Channels**:
    - **Sage HR Archive**: Idempotent import with SHA-256 hash checks.
    - **Manual Input**: Consume-and-move mechanism for scanned documents.
    - **Web Upload**: Drag-and-drop interface.
    - **Email Ingest**: Centralized processing via Microsoft Graph API using tenant-specific tokens (e.g., `upload.<token>@dms.cloud`).
- **Sage Cloud Integration**: Connects to Sage HR Cloud REST API for importing leave requests, generating timesheet PDFs, and synchronizing employee data.
- **Automated PDF Generation**: Generates professional PDF documents for items like leave requests and monthly timesheets.
- **GUI Configuration**: All system settings, including API credentials and Celery Beat schedules, are configurable via the Django Admin interface.
- **Security**:
    - Fernet encryption for files and encrypted API keys in the database.
    - Password protection and role-based access control.
    - **Multi-Factor Authentication (MFA)**: Supports FIDO2/WebAuthn (Passkeys), TOTP (Authenticator apps), and recovery codes. MFA is enforced for all users.
- **GDPR-Compliant Tenant Onboarding**:
    - **Secure Invitations**: `TenantInvite` model with SHA-256 token hashing, 7-day expiration, single-use enforcement with atomic transactions.
    - **Consent Tracking**: Records consent version, timestamp, IP address, and consent text in AuditLog for GDPR audit trail.
    - **Onboarding Status**: Tenants track status (CREATED -> INVITED -> ACTIVE) with automatic transitions.
    - **Previous Invite Revocation**: New invitations automatically revoke pending invites for the same tenant/email.
    - **Email Flow**: `send_invite_action` in TenantAdmin sends tokenized invitation links (`/einladung/<token>/`).
- **Document Management Features (d.3 one & Paperless-ngx inspired)**:
    - **File Logic**: Hierarchical file plans (`FileCategory`) with retention periods (based on creation, termination, or document date). Supports `PersonnelFile` and `PersonnelFileEntry` for structured HR document management.
    - **Tags and Matching Rules**: Hierarchical tags with color-coding, and automated document classification via `MatchingRule` (ANY, ALL, EXACT, REGEX, FUZZY algorithms).
    - **Bulk Editing**: Mass operations for documents (status, employee assignment, document type, deletion).
    - **Full-Text Search**: PostgreSQL Full-Text Search with ranking and highlighting, supporting AJAX auto-complete.

### Performance Optimizations

- Parallel document processing (ThreadPoolExecutor).
- Chunked hash calculation for large files.
- Path-based deduplication cache.
- Batched database updates.
- Thread-safe counters.

### Project Structure

The project follows a standard Django structure, with `dms_project` for global settings and `dms` as the main application containing models, views, tasks, middleware, and connectors.

## External Dependencies

- **Azure Blob Storage**: For scalable and secure document storage.
- **Sage HR Cloud (REST API)**: For HR data synchronization and document imports.
- **Microsoft Graph API**: For centralized email ingest functionality.
- **PostgreSQL**: As the primary database, utilizing its Full-Text Search capabilities.
- **Celery**: For asynchronous task processing and scheduled jobs (Celery Beat).
- **django-unfold**: For the modernized Django Admin interface.
- **django-mfa3**: For Multi-Factor Authentication (MFA) implementation.
- **Docker/Docker Compose**: For containerization and environment management.