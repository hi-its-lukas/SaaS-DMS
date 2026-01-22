"""
Custom admin views for DMS.
"""
import os
import zipfile
import io
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponse, Http404
from django.shortcuts import render, get_object_or_404
from django.conf import settings
from .models import Tenant


def is_superuser(user):
    """Check if user is a superuser (Root-Admin)."""
    return user.is_superuser


@staff_member_required
@user_passes_test(is_superuser)
def agent_download_page(request):
    """
    Page for downloading the DMS Sync Agent.
    Only accessible to Root-Admins (superusers).
    """
    tenants = Tenant.objects.select_related('company').filter(
        is_active=True,
        code__isnull=False
    ).exclude(code='')
    
    context = {
        'title': 'DMS Sync Agent Download',
        'tenants': tenants,
    }
    return render(request, 'admin/dms/agent_download.html', context)


@staff_member_required
@user_passes_test(is_superuser)
def agent_download_zip(request, tenant_id):
    """
    Download the DMS Sync Agent as a ZIP with pre-configured config.yaml.
    
    The ZIP contains:
    - DMSSyncAgent.exe (placeholder - actual build would be from CI/CD)
    - config.yaml (pre-configured with tenant token and DMS URL)
    - README.txt (installation instructions)
    """
    tenant = get_object_or_404(Tenant, pk=tenant_id)
    
    dms_url = getattr(settings, 'DMS_PUBLIC_URL', 'https://portal.personalmappe.cloud')
    
    config_yaml = f"""# DMS Sync Agent Konfiguration
# Mandant: {tenant.name}
# Erstellt: Automatisch generiert

dms_url: {dms_url}
watch_folder: C:\\SageArchiv\\{tenant.code or 'Mandant'}
processed_folder: C:\\SageArchiv\\{tenant.code or 'Mandant'}\\processed
tenant_code: "{tenant.code or ''}"

include_patterns:
  - "*.pdf"
  - "*.xlsx"
  - "*.docx"

stability_seconds: 5
heartbeat_interval_seconds: 300
"""
    
    token_txt = f"""{tenant.ingest_token}"""
    
    readme_txt = f"""==============================================
    DMS SYNC AGENT - INSTALLATIONSANLEITUNG
==============================================

Mandant: {tenant.name}
{f'Mandanten-Code: {tenant.code}' if tenant.code else ''}

1. INSTALLATION
---------------
1. Kopieren Sie den kompletten Ordner nach C:\\Programme\\DMSSyncAgent\\
2. Öffnen Sie eine Administrator-Eingabeaufforderung (als Administrator)
3. Wechseln Sie in das Verzeichnis: cd C:\\Programme\\DMSSyncAgent
4. Token installieren: DMSSyncAgent.exe --set-token <Token aus token.txt>
   (Der Token lautet: {tenant.ingest_token})
5. Dienst installieren: DMSSyncAgent.exe --install
6. Dienst starten: DMSSyncAgent.exe --start

HINWEIS: Die Datei token.txt enthält Ihren persönlichen Zugangstoken.
Löschen Sie diese Datei nach der Installation aus Sicherheitsgründen!

2. KONFIGURATION ANPASSEN
-------------------------
Bearbeiten Sie config.yaml und passen Sie die Pfade an:
- watch_folder: Ordner, der überwacht werden soll
- processed_folder: Ordner für verarbeitete Dateien

3. DIENST VERWALTEN
-------------------
Status prüfen: DMSSyncAgent.exe --status
Dienst stoppen: DMSSyncAgent.exe --stop
Dienst starten: DMSSyncAgent.exe --start
Dienst deinstallieren: DMSSyncAgent.exe --uninstall

4. LOGS
-------
Logs befinden sich unter:
C:\\ProgramData\\DMSSyncAgent\\logs\\agent.log

5. SUPPORT
----------
Bei Fragen wenden Sie sich an Ihren DMS-Administrator.

==============================================
"""

    placeholder_exe = b"MZ" + b"\x00" * 100 + b"PLACEHOLDER_EXE - Please build actual agent with: go build -o DMSSyncAgent.exe ./cmd/agent"
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr('DMSSyncAgent/config.yaml', config_yaml)
        zip_file.writestr('DMSSyncAgent/README.txt', readme_txt)
        zip_file.writestr('DMSSyncAgent/token.txt', token_txt)
        zip_file.writestr('DMSSyncAgent/DMSSyncAgent.exe', placeholder_exe)
    
    zip_buffer.seek(0)
    
    safe_name = (tenant.code or tenant.name).replace(' ', '_').replace('/', '_')
    filename = f"DMSSyncAgent_{safe_name}.zip"
    
    response = HttpResponse(zip_buffer.read(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
