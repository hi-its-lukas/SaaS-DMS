#!/usr/bin/env python
"""
DMS Setup-Skript
Generiert automatisch alle notwendigen Schlüssel und Konfigurationen.
"""
import os
import sys
import secrets
import string
from pathlib import Path

def generate_secret_key(length=50):
    """Generiert einen sicheren Django Secret Key."""
    chars = string.ascii_letters + string.digits + '!@#$%^&*(-_=+)'
    return ''.join(secrets.choice(chars) for _ in range(length))

def generate_fernet_key():
    """Generiert einen Fernet-Verschlüsselungsschlüssel."""
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()

def generate_password(length=16):
    """Generiert ein sicheres Passwort."""
    chars = string.ascii_letters + string.digits + '!@#$%^&*()'
    return ''.join(secrets.choice(chars) for _ in range(length))

def create_env_file():
    """Erstellt die .env Datei mit allen notwendigen Konfigurationen."""
    env_path = Path('.env')
    
    if env_path.exists():
        print("WARNUNG: .env Datei existiert bereits!")
        response = input("Überschreiben? (j/n): ").lower()
        if response != 'j':
            print("Setup abgebrochen.")
            return False
    
    django_secret = generate_secret_key()
    encryption_key = generate_fernet_key()
    db_password = generate_password(20)
    samba_password = generate_password(12)
    admin_password = generate_password(12)
    
    env_content = f"""# DMS Konfiguration - Automatisch generiert
# WICHTIG: Diese Datei sicher aufbewahren!

# Django Einstellungen
DJANGO_SECRET_KEY={django_secret}
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1

# Datenbank
POSTGRES_DB=dms
POSTGRES_USER=dms_user
POSTGRES_PASSWORD={db_password}
DATABASE_URL=postgresql://dms_user:{db_password}@db:5432/dms

# Verschlüsselung
ENCRYPTION_KEY={encryption_key}

# Redis
REDIS_URL=redis://redis:6379/0

# Samba
SAMBA_PASSWORD={samba_password}

# Admin-Benutzer (wird beim ersten Start erstellt)
ADMIN_USERNAME=admin
ADMIN_PASSWORD={admin_password}
ADMIN_EMAIL=admin@example.com

# Pfade
SAGE_ARCHIVE_PATH=/data/sage_archive
MANUAL_INPUT_PATH=/data/manual_input
EMAIL_ARCHIVE_PATH=/data/email_archive
"""
    
    with open(env_path, 'w') as f:
        f.write(env_content)
    
    print("\n" + "="*60)
    print("DMS SETUP ABGESCHLOSSEN")
    print("="*60)
    print(f"\n.env Datei wurde erstellt mit folgenden Zugangsdaten:\n")
    print(f"  Admin-Benutzername: admin")
    print(f"  Admin-Passwort:     {admin_password}")
    print(f"  Samba-Passwort:     {samba_password}")
    print(f"\nDatenbank-Passwort und Verschlüsselungsschlüssel wurden")
    print("automatisch generiert und in .env gespeichert.")
    print("\nWICHTIG: Notieren Sie sich das Admin-Passwort!")
    print("="*60)
    
    return True

def create_directories():
    """Erstellt die notwendigen Verzeichnisse."""
    dirs = [
        'data/sage_archive',
        'data/manual_input',
        'data/manual_input/processed',
        'data/email_archive',
    ]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)
    print("Verzeichnisse erstellt.")

def main():
    print("\n" + "="*60)
    print("DMS - Document Management System Setup")
    print("="*60 + "\n")
    
    create_directories()
    
    if create_env_file():
        print("\nNächste Schritte:")
        print("1. docker-compose up -d")
        print("2. Öffnen Sie http://localhost im Browser")
        print("3. Melden Sie sich mit den Admin-Zugangsdaten an")

if __name__ == '__main__':
    main()
