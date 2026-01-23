# DMS Local Docker Development Guide

This guide describes how to run the DMS application locally using Docker Desktop, including 2FA setup.

## Prerequisites
- Docker Desktop installed and running.
- Git.
- `nc` (netcat) - useful for connectivity checks (optional).

## 1. Environment Setup

Ensure you have a `.env` file. You can copy it from `.env.local.example`:

```bash
cp .env.local.example .env
```

**Important**: For local 2FA to work, ensure `.env` (or the docker-compose override) has:
```bash
MFA_DOMAIN=localhost
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
```
(Note: `docker-compose.dev.yml` forces `MFA_DOMAIN=localhost` automatically).

## 2. Start Application

Run the development compose file:

```bash
docker compose -f docker-compose.dev.yml up --build
```

- **Host**: `http://localhost:8000`
- **MailHog/Console**: Emails are printed to console in Dev.

## 3. Create Admin User

Open a new terminal window:

```bash
docker compose -f docker-compose.dev.yml exec web python manage.py createsuperuser
```

Follow the prompts to create your admin user.

## 4. Setup 2FA (MFA)

1.  **Login**: Go to `http://localhost:8000/admin/` and login with your new superuser.
2.  **Navigate**: Go to **User Settings** (top right) or `http://localhost:8000/admin/password_change/` (Django Admin password change usually contains links if customized) or simply use the dedicated MFA views if available.
    *   *Note*: In this project, go to `/admin/` -> **MFA** -> **Keys**.
3.  **Add Key**:
    *   Click "Add MFA Key".
    *   **TOTP (Authenticator App)**: Scan the QR code with Google Authenticator or Authy. Enter the code to verify.
    *   **FIDO2 (TouchID/YubiKey)**: Select FIDO2. Your browser should prompt for TouchID or Security Key. *This works because we are on `localhost`.*

## 5. Verification

To verify the environment configuration from within the container:

```bash
docker compose -f docker-compose.dev.yml exec web python scripts/verify_env.py
```

## Troubleshooting

-   **Database connection failed**: Ensure `db` container is healthy.
-   **Static files missing**: Run `docker compose -f docker-compose.dev.yml exec web python manage.py collectstatic --noinput`.
-   **CSRF Verification Failed**: Ensure you are accessing via `http://localhost:8000` and not `127.0.0.1` unless both are in `CSRF_TRUSTED_ORIGINS`.

## Production (Azure)

For Azure, the standard `docker-compose.yml` is used as a reference, but usually, images are pushed to ACR.
Ensure `MFA_DOMAIN` is set to the real domain (e.g., `dms.custom-domain.com`) in Azure Container Apps environment variables.
