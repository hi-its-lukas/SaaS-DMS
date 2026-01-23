# Logik-Überprüfung & Verbesserungsvorschläge

## Zusammenfassung
Die Analyse des Codes (`dms/models.py`, `dms/admin.py`) zeigt Diskrepanzen zwischen der gewünschten Logik (Audio-Transkript) und der aktuellen Implementierung. Insbesondere das Konzept des **Unternehmens-Admins** (Enterprise Admin), der *oberhalb* von Mandanten existiert, fehlt.

## Gefundene Diskrepanzen

### 1. Fehlende Zuweisung "Unternehmens-Admin" bei Anlage
**Anforderung:** "Dem Unternehmen muss bei Anlage ein Unternehmens-Admin zugeordnet werden."
**Status:** **Fehlt**.
- Das Modell `Company` hat kein Feld für Administratoren (nur `created_by`, was der Root-Admin ist).
- Es gibt kein Modell `CompanyUser`. Benutzer sind aktuell nur über `TenantUser` mit einem *Mandanten* verknüpft.
- **Problem:** Wenn ein Unternehmen erstellt wird, kann niemand es konfigurieren oder den ersten Mandanten anlegen, da es noch keine Mandanten gibt, in die man einen User einladen könnte.

### 2. Fehlende Ebene "Unternehmens-Konfiguration"
**Anforderung:** "Dieser [Unternehmens-Admin] ist zuständig für die Konfiguration innerhalb des Unternehmens [und Anlage von Mandanten]."
**Status:** **Nicht möglich**.
- Da Benutzer nur an Mandanten hängen, gibt es keine Berechtigungsebene "Unternehmen".
- Aktuell können Mandanten nur vom Root-Admin (via Django Admin) angelegt werden, da es keine View gibt, die einem "Unternehmens-Admin" erlaubt, Mandanten zu erstellen.

### 3. Support-Zugriff (Impersonation) fehlt
**Anforderung:** "Der Unternehmens-Admin muss die Möglichkeit haben, dem Root-Admin einen Support-Zugriff auf seine Instanz zu geben."
**Status:** **Fehlt**.
- Es gibt keinen Schalter `allow_support_access` am `Company` oder `Tenant` Modell.
- `BlindRootAdminMixin` sperrt Root-Admins derzeit hart aus, ohne Ausnahme-Mechanismus.

### 4. Mehrere Admins / Mehrere Unternehmen
**Anforderung:** "Unternehmen kann mehrere Admins haben, ein Admin kann mehreren Unternehmen zugeordnet sein."
**Status:** **Teilweise**.
- Ein User kann in mehreren *Mandanten* sein. Aber ohne direkte Verknüpfung zum *Unternehmen* ist die Anforderung "Admin für das ganze Unternehmen" nicht sauber abgebildet.

---

## Verbesserungsvorschläge (Implementation Roadmap)

Um die Logik korrekt abzubilden, müssen folgende Änderungen vorgenommen werden:

### Schritt A: Neues Modell `CompanyUser` einführen
Erstellung einer expliziten Beziehung zwischen Usern und Unternehmen, unabhängig von Mandanten.

```python
class CompanyUser(models.Model):
    company = models.ForeignKey(Company, ...)
    user = models.ForeignKey(User, ...)
    is_main_admin = models.BooleanField(default=False)  # "Haupt-Admin"
    
    class Meta:
        unique_together = ['company', 'user']
```

### Schritt B: `Company` Modell erweitern
Hinzufügen eines Feldes für den Support-Zugriff.

```diff
class Company(models.Model):
    # ... bestehende Felder
+   support_access_granted_until = models.DateTimeField(null=True, blank=True)
```

### Schritt C: Anpassung der Erstellungs-Logik (Admin)
Wenn der Root-Admin ein Unternehmen erstellt, muss er zwingend eine E-Mail-Adresse für den ersten Admin angeben.
1. Root-Admin füllt Formular aus (Name, Limits, **Admin-Email**).
2. System erstellt `Company`.
3. System erstellt `User` (falls nicht existent) oder verknüpft ihn.
4. System erstellt `CompanyUser` Eintrag.
5. Einladungsemail wird verschickt.

### Schritt D: Support-Zugriff Logik
Implementierung einer Middleware oder Permission-Check:
- Root-Admin darf normalerweise keine Tenant-Daten sehen.
- **Ausnahme:** Wenn `company.support_access_granted_until > now()`, darf Root-Admin zugreifen (impersonate oder direkt).

### Schritt E: Unternehmens-Dashboard
Eine neue View für Unternehmens-Admins, in der sie:
1. Globale Einstellungen d. Unternehmens sehen.
2. Mandanten verwalten (erstellen/sperren).
3. Support-Zugriff aktivieren/deaktivieren.
