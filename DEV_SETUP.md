# Lokale Entwicklungsumgebung

Dieses Dokument beschreibt, wie du die DMS-Anwendung lokal mit Docker Compose ausführst.

## Voraussetzungen

- Docker Desktop installiert ([Download](https://www.docker.com/products/docker-desktop))
- Docker Compose (normalerweise in Docker Desktop enthalten)
- Git

## Schnellstart

### 1. Repository klonen (falls noch nicht geschehen)

```bash
git clone <repository-url>
cd SaaS-DMS
```

### 2. Umgebungsvariablen konfigurieren

Kopiere die `.env.example` Datei zu `.env`:

```bash
cp .env.example .env
```

**Wichtig:** Generiere einen `ENCRYPTION_KEY`:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Füge den generierten Schlüssel in die `.env` Datei ein:

```
ENCRYPTION_KEY=<dein-generierter-schlüssel>
```

### 3. Container starten

```bash
docker-compose -f docker-compose.dev.yml up -d
```

Beim ersten Start werden die Images gebaut und alle Services gestartet:
- **web** - Django Entwicklungsserver (Port 8000)
- **db** - PostgreSQL Datenbank (Port 5432)
- **redis** - Redis für Celery (Port 6379)
- **celery_worker** - Celery Worker für Background Tasks
- **celery_beat** - Celery Beat Scheduler

### 4. Datenbank initialisieren

Führe die Migrationen aus:

```bash
docker-compose -f docker-compose.dev.yml exec web python manage.py migrate
```

Erstelle einen Superuser:

```bash
docker-compose -f docker-compose.dev.yml exec web python manage.py createsuperuser
```

### 5. Static Files sammeln

```bash
docker-compose -f docker-compose.dev.yml exec web python manage.py collectstatic --noinput
```

### 6. Anwendung öffnen

Öffne deinen Browser und gehe zu:
- **Frontend:** http://localhost:8000
- **Admin:** http://localhost:8000/admin

## Entwicklung

### Live-Reloading

Der Django Development Server läuft mit Auto-Reload. Änderungen am Code werden automatisch erkannt und der Server neugestartet.

### Logs anzeigen

Alle Container:
```bash
docker-compose -f docker-compose.dev.yml logs -f
```

Nur Web-Container:
```bash
docker-compose -f docker-compose.dev.yml logs -f web
```

Nur Celery Worker:
```bash
docker-compose -f docker-compose.dev.yml logs -f celery_worker
```

### Django Management Commands ausführen

```bash
docker-compose -f docker-compose.dev.yml exec web python manage.py <command>
```

Beispiele:
```bash
# Shell öffnen
docker-compose -f docker-compose.dev.yml exec web python manage.py shell

# Neue Migration erstellen
docker-compose -f docker-compose.dev.yml exec web python manage.py makemigrations

# Tests ausführen
docker-compose -f docker-compose.dev.yml exec web python manage.py test

# Datenbank zurücksetzen
docker-compose -f docker-compose.dev.yml exec web python manage.py flush
```

### Container neustarten

Einzelner Service:
```bash
docker-compose -f docker-compose.dev.yml restart web
```

Alle Services:
```bash
docker-compose -f docker-compose.dev.yml restart
```

### Container stoppen

```bash
docker-compose -f docker-compose.dev.yml down
```

Mit Volumes löschen (Datenbank wird zurückgesetzt):
```bash
docker-compose -f docker-compose.dev.yml down -v
```

## Datenbank-Zugriff

### Direkter Zugriff auf PostgreSQL

```bash
docker-compose -f docker-compose.dev.yml exec db psql -U dms_user -d dms_db
```

### Backup erstellen

```bash
docker-compose -f docker-compose.dev.yml exec db pg_dump -U dms_user dms_db > backup.sql
```

### Backup wiederherstellen

```bash
cat backup.sql | docker-compose -f docker-compose.dev.yml exec -T db psql -U dms_user -d dms_db
```

## Tests ausführen

### Unit Tests

```bash
docker-compose -f docker-compose.dev.yml exec web python manage.py test
```

### Verifikationsskript (Lizenz-Logik)

```bash
docker-compose -f docker-compose.dev.yml exec web python verify_logic.py
```

## Troubleshooting

### Port bereits belegt

Falls ein Port bereits belegt ist, ändere die Ports in der `docker-compose.dev.yml`:

```yaml
ports:
  - "8001:8000"  # Statt 8000:8000
```

### Datenbank-Connection-Fehler

Stelle sicher, dass der DB-Container läuft:
```bash
docker-compose -f docker-compose.dev.yml ps
```

Falls nicht, starte ihn neu:
```bash
docker-compose -f docker-compose.dev.yml up -d db
```

### Packages fehlen nach Update

Rebuild den Container:
```bash
docker-compose -f docker-compose.dev.yml build web
docker-compose -f docker-compose.dev.yml up -d
```

### Volumes komplett zurücksetzen

```bash
docker-compose -f docker-compose.dev.yml down -v
docker volume prune
docker-compose -f docker-compose.dev.yml up -d
```

## Unterschiede zur Produktionsumgebung

| Feature | Development | Production |
|---------|-------------|------------|
| **Datenbank** | Lokale PostgreSQL via Docker | Azure PostgreSQL |
| **Storage** | Lokales Filesystem (`/app/media`) | Azure Blob Storage |
| **Debug Mode** | `DEBUG=True` | `DEBUG=False` |
| **SSL** | Nicht aktiviert | HSTS, SSL Redirect |
| **Static Files** | Django Development Server | Nginx + WhiteNoise |
| **Secrets** | `.env` Datei | Azure Secrets/Umgebungsvariablen |

## Workflow: Änderungen testen

1. **Code ändern** - Änderungen werden automatisch geladen
2. **Migration erstellen** (falls Models geändert):
   ```bash
   docker-compose -f docker-compose.dev.yml exec web python manage.py makemigrations
   docker-compose -f docker-compose.dev.yml exec web python manage.py migrate
   ```
3. **Testen**:
   ```bash
   docker-compose -f docker-compose.dev.yml exec web python manage.py test
   docker-compose -f docker-compose.dev.yml exec web python verify_logic.py
   ```
4. **Committen & Pushen**:
   ```bash
   git add .
   git commit -m "Description"
   git push origin main
   ```

## Nützliche Aliase (Optional)

Füge diese zu deiner `~/.zshrc` oder `~/.bashrc` hinzu:

```bash
alias ddev='docker-compose -f docker-compose.dev.yml'
alias dmng='docker-compose -f docker-compose.dev.yml exec web python manage.py'
```

Dann kannst du verwenden:
```bash
ddev up -d
dmng migrate
dmng createsuperuser
ddev logs -f web
```
