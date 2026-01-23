# 🚀 Lokale Dev-Umgebung erfolgreich eingerichtet!

## ✅ Status

Die Docker-basierte Entwicklungsumgebung läuft erfolgreich:

- **Web Server**: http://localhost:8000 ✅
- **PostgreSQL**: localhost:5432 ✅
- **Redis**: localhost:6379 ✅
- **Celery Worker**: Läuft ✅
- **Celery Beat**: Läuft ✅

## 📝 Nützliche Befehle

### Docker Alias (empfohlen)

Füge zu `~/.zshrc` hinzu:
```bash
alias ddev='/Applications/Docker.app/Contents/Resources/bin/docker compose -f docker-compose.dev.yml'
```

Dann Terminal neu laden:
```bash
source ~/.zshrc
```

Jetzt kannst du verwenden:
```bash
ddev ps                    # Status anzeigen
ddev logs web -f           # Logs folgen
ddev exec web python manage.py shell
ddev restart web           # Web-Container neu starten
ddev down                  # Alles stoppen
ddev up -d                 # Alles starten
```

### Ohne Alias

```bash
# Container-Status
/Applications/Docker.app/Contents/Resources/bin/docker compose -f docker-compose.dev.yml ps

# Logs anzeigen
/Applications/Docker.app/Contents/Resources/bin/docker compose -f docker-compose.dev.yml logs web -f

# Django Shell
/Applications/Docker.app/Contents/Resources/bin/docker compose -f docker-compose.dev.yml exec web python manage.py shell

# Migrationen
/Applications/Docker.app/Contents/Resources/bin/docker compose -f docker-compose.dev.yml exec web python manage.py makemigrations
/Applications/Docker.app/Contents/Resources/bin/docker compose -f docker-compose.dev.yml exec web python manage.py migrate

# Superuser erstellen
/Applications/Docker.app/Contents/Resources/bin/docker compose -f docker-compose.dev.yml exec web python manage.py createsuperuser

# Container neu starten
/Applications/Docker.app/Contents/Resources/bin/docker compose -f docker-compose.dev.yml restart web

# Alles stoppen
/Applications/Docker.app/Contents/Resources/bin/docker compose -f docker-compose.dev.yml down

# Alles starten
/Applications/Docker.app/Contents/Resources/bin/docker compose -f docker-compose.dev.yml up -d
```

## 🧪 Tests ausführen

```bash
# Django Tests
/Applications/Docker.app/Contents/Resources/bin/docker compose -f docker-compose.dev.yml exec web python manage.py test

# Verifikations-Skript (Lizenz-Logik)
# Das Skript ist lokal, nicht im Container - kopiere es erst rein:
/Applications/Docker.app/Contents/Resources/bin/docker compose -f docker-compose.dev.yml cp verify_logic.py web:/app/
/Applications/Docker.app/Contents/Resources/bin/docker compose -f docker-compose.dev.yml exec web python verify_logic.py
```

## 🌐 Anwendung öffnen

1. **Frontend**: http://localhost:8000
2. **Admin**: http://localhost:8000/admin

## 📊 Nächste Schritte

1. **Superuser erstellen**:
   ```bash
   /Applications/Docker.app/Contents/Resources/bin/docker compose -f docker-compose.dev.yml exec web python manage.py createsuperuser
   ```

2. **Browser öffnen**: http://localhost:8000/admin

3. **Code ändern** - Die Änderungen werden automatisch geladen (Live-Reload)

4. **Testen & Committen**:
   ```bash
   git add .
   git commit -m "Your message"
   git push origin main
   ```

## 🛠️ Wartung

### Container neu bauen (nach requirements.txt Änderung)

```bash
/Applications/Docker.app/Contents/Resources/bin/docker compose -f docker-compose.dev.yml build
/Applications/Docker.app/Contents/Resources/bin/docker compose -f docker-compose.dev.yml up -d
```

### Datenbank zurücksetzen

```bash
/Applications/Docker.app/Contents/Resources/bin/docker compose -f docker-compose.dev.yml down -v
/Applications/Docker.app/Contents/Resources/bin/docker compose -f docker-compose.dev.yml up -d
/Applications/Docker.app/Contents/Resources/bin/docker compose -f docker-compose.dev.yml exec web python manage.py migrate
```

## ⚠️ Bekannte Probleme

- **Celery restart loops**: Normal beim ersten Start - nach Migrationen sollte es stabil laufen
- **Port bereits belegt**: Ändere die Ports in `docker-compose.dev.yml`
- **Live-Reload funktioniert nicht**: Container neu starten

## 📚 Weitere Dokumentation

- [DEV_SETUP.md](file:///Users/luhengl/GitHub/SaaS-DMS/DEV_SETUP.md) - Vollständige Anleitung
- [README_DEV.md](file:///Users/luhengl/GitHub/SaaS-DMS/README_DEV.md) - Übersicht
