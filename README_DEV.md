# DMS - Lokale Entwicklungsumgebung

Es gibt zwei Optionen, um die DMS-Anwendung lokal zu entwickeln:

## Option 1: Mit Docker (Empfohlen) 🐳

**Vorteile:**
- ✅ Identisch zur Produktionsumgebung (PostgreSQL statt SQLite)
- ✅ Celery Worker & Redis für Background Tasks
- ✅ Vollständige Isolation
- ✅ Einfaches Setup für alle Teammitglieder

**Nachteile:**
- ❌ Docker Desktop muss installiert sein
- ❌ Längere Startzeit (~5-10 Min beim ersten Mal)
- ❌ Mehr Ressourcen benötigt

📖 **Anleitung:** [DEV_SETUP.md](DEV_SETUP.md)

### Docker Installation

Falls Docker noch nicht installiert ist:

1. Download Docker Desktop: https://www.docker.com/products/docker-desktop
2. Installieren und starten
3. Terminal neu öffnen
4. Testen: `docker --version`

---

## Option 2: Ohne Docker (Schneller Start) ⚡

**Vorteile:**
- ✅ Sehr schnelles Setup (< 1 Minute)
- ✅ Weniger Ressourcen
- ✅ Einfaches Debugging

**Nachteile:**
- ❌ SQLite statt PostgreSQL (potenzielle Unterschiede)
- ❌ Keine Background Tasks (Celery)
- ❌ Nicht identisch mit Production

📖 **Anleitung:** [DEV_SETUP_NO_DOCKER.md](DEV_SETUP_NO_DOCKER.md)

---

## Schnellstart (Ohne Docker)

```bash
# 1. Virtual Environment
python3 -m venv venv
source venv/bin/activate

# 2. Dependencies
pip install -r requirements.txt

# 3. Environment Setup
cp .env.local.example .env

# 4. Datenbank
python manage.py migrate
python manage.py createsuperuser

# 5. Server starten
python manage.py runserver
```

Öffne: http://localhost:8000

---

## Was wurde geändert?

### Behobene Fehler

1. **`Tenant.save()` Inkonsistenz** ([models.py:275](file:///Users/luhengl/GitHub/SaaS-DMS/dms/models.py#L275))
   - ❌ **Vorher:** `if not self.pk:` (unzuverlässig)
   - ✅ **Jetzt:** `if self._state.adding:` (Django Best Practice)
   - Konsistent mit `TenantUser` und `PersonnelFile`

### Neue Dateien

- [`.env.example`](file:///Users/luhengl/GitHub/SaaS-DMS/.env.example) - Docker Setup
- [`.env.local.example`](file:///Users/luhengl/GitHub/SaaS-DMS/.env.local.example) - Natives Setup
- [`docker-compose.dev.yml`](file:///Users/luhengl/GitHub/SaaS-DMS/docker-compose.dev.yml) - Docker Dev-Config
- [`DEV_SETUP.md`](file:///Users/luhengl/GitHub/SaaS-DMS/DEV_SETUP.md) - Docker Anleitung
- [`DEV_SETUP_NO_DOCKER.md`](file:///Users/luhengl/GitHub/SaaS-DMS/DEV_SETUP_NO_DOCKER.md) - Native Anleitung
- [`.gitignore`](file:///Users/luhengl/GitHub/SaaS-DMS/.gitignore) - Updated (`.env` hinzugefügt)

---

## Empfehlung

| Zweck | Empfohlene Option |
|-------|-------------------|
| **Schnelles Testen** | Ohne Docker ⚡ |
| **Vollständige Tests** | Mit Docker 🐳 |
| **CI/CD Vorbereitung** | Mit Docker 🐳 |
| **Erstmaliges Setup** | Ohne Docker ⚡ (dann später Docker) |

---

## Next Steps

1. **Jetzt:** Starte mit dem Setup ohne Docker (schneller)
2. **Später:** Installiere Docker für vollständige Tests
3. **Vor Push:** Teste mit Docker-Setup

```bash
# Test ausführen
python verify_logic.py

# Bei Erfolg: Committen
git add .
git commit -m "Fix: Tenant.save() uses _state.adding for consistency"
git push origin main
```
