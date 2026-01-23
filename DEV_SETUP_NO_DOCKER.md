# Lokale Entwicklung ohne Docker (SQLite)

Diese Anleitung zeigt, wie du die DMS-Anwendung **ohne Docker** lokal mit SQLite ausführst.

## Voraussetzungen

- Python 3.9+
- pip
- Git

## Setup

### 1. Virtual Environment erstellen

```bash
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
```

### 2. Dependencies installieren

```bash
pip install -r requirements.txt
```

### 3. Umgebungsvariablen konfigurieren

Kopiere `.env.local.example` zu `.env`:

```bash
cp .env.local.example .env
```

Die `.env` Datei ist bereits mit einem `ENCRYPTION_KEY` vorkonfiguriert.

### 4. Datenbank initialisieren

```bash
python manage.py migrate
```

### 5. Superuser erstellen

```bash
python manage.py createsuperuser
```

### 6. Server starten

```bash
python manage.py runserver
```

Öffne im Browser: http://localhost:8000

## Entwicklung

### Tests ausführen

```bash
python manage.py test
```

### Verifikationsskript

```bash
python verify_logic.py
```

### Neue Migrationen erstellen

```bash
python manage.py makemigrations
python manage.py migrate
```

### Django Shell

```bash
python manage.py shell
```

## Unterschiede zu Docker-Setup

| Feature | Lokal (SQLite) | Docker (PostgreSQL) |
|---------|----------------|---------------------|
| **Datenbank** | SQLite (Datei) | PostgreSQL (Container) |
| **Celery** | Nicht verfügbar | Läuft im Container |
| **Redis** | Nicht verfügbar | Läuft im Container |
| **Setup-Zeit** | < 1 Minute | 5-10 Minuten |
| **Isolation** | Keine | Vollständig isoliert |

## Limitierungen

- ⚠️ **Keine Background Tasks**: Celery funktioniert nicht ohne Redis
- ⚠️ **SQLite statt PostgreSQL**: Unterschiede in DB-Features möglich
- ⚠️ **Concurrent Access**: SQLite ist nicht für Multi-User geeignet

## Empfehlung

Für umfassende Tests solltest du Docker verwenden (siehe `DEV_SETUP.md`).
Für schnelles Testen von Code-Änderungen ist SQLite ausreichend.
