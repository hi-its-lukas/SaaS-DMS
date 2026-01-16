# Dokumentenmanagementsystem (DMS)

Ein produktionsreifes Django-basiertes Dokumentenmanagementsystem für HR- und Unternehmensabläufe.

## Übersicht

Dieses DMS bietet verschlüsselte Dokumentenspeicherung, Multi-Kanal-Eingabeverarbeitung und Microsoft 365 E-Mail-Integration. Alle Dokumente werden mit Fernet-Verschlüsselung vor der Speicherung verschlüsselt.

## Projektstruktur

```
dms_project/           # Django-Projekteinstellungen
  ├── settings.py      # Hauptkonfiguration
  ├── celery.py        # Celery-Async-Task-Konfiguration
  └── urls.py          # URL-Routing

dms/                   # Hauptanwendung
  ├── models.py        # Datenbankmodelle (Dokument, Mitarbeiter, Aufgabe, etc.)
  ├── views.py         # Web-Views für Upload, Auflistung, Download
  ├── tasks.py         # Celery-Hintergrundaufgaben
  ├── encryption.py    # Fernet-Verschlüsselungstools
  ├── admin.py         # Django-Admin-Konfiguration
  └── urls.py          # App-URL-Muster

templates/dms/         # HTML-Vorlagen
data/                  # Datenverzeichnisse
  ├── sage_archive/    # Schreibgeschütztes Sage HR-Archiv
  ├── manual_input/    # Manueller Scan-Eingabeordner
  └── email_archive/   # E-Mail-Speicher
```

## Hauptfunktionen

### Eingabekanäle

1. **Sage HR-Archiv (Kanal A)**: Idempotenter Import mit SHA-256-Hash-Prüfung
2. **Manuelle Eingabe (Kanal B)**: Verbrauchen-und-Verschieben-Muster für Scanner/Benutzer-Uploads
3. **Web-Upload (Kanal C)**: Drag-and-Drop-Oberfläche mit AJAX-Upload

### Sicherheit

- Alle Dateien werden mit Fernet vor der Datenbankspeicherung verschlüsselt
- SHA-256-Hash-Tracking zur Vermeidung doppelter Importe
- Rollenbasierte Berechtigungen über Django-Gruppen
- **Passwortschutz für die gesamte Anwendung erforderlich**

### Dokument-Workflow

- Status: NICHT ZUGEWIESEN, ZUGEWIESEN, ARCHIVIERT, PRÜFUNG ERFORDERLICH
- DataMatrix-Barcode-Scanning für automatische Mitarbeiterzuweisung
- Aufgabenerstellung für Prüfungspunkte

### E-Mail-Integration

- Microsoft Graph API über O365-Bibliothek
- Automatische E-Mail-zu-PDF-Konvertierung
- Anhang-Extraktion und -Speicherung

## Docker-Installation

### Schnellstart

1. Setup-Skript ausführen (generiert automatisch alle Schlüssel):
```bash
python setup.py
```

2. Docker-Container starten:
```bash
docker-compose up -d
```

3. Im Browser öffnen: http://localhost

4. Mit den angezeigten Zugangsdaten anmelden

### Samba-Freigaben

Nach dem Start sind folgende Netzwerkfreigaben verfügbar:
- `\\server\Sage_Archiv` (Nur Lesen) - Sage HR-Archiv
- `\\server\Manueller_Scan` (Lesen/Schreiben) - Scanner-Eingabe

## Lokale Entwicklung (Replit)

### Admin-Zugang
- URL: `/admin/`
- Benutzername: `admin`
- Passwort: `admin123`

### Celery-Aufgaben ausführen

Für Hintergrundverarbeitung:
```bash
celery -A dms_project worker -l INFO
celery -A dms_project beat -l INFO
```

## Letzte Änderungen

- Vollständige deutsche Benutzeroberfläche
- Passwortschutz für alle Seiten aktiviert
- Automatische Schlüsselgenerierung beim Setup
- Docker-Deployment-Konfiguration
