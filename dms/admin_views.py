"""
Custom admin views for DMS.
"""
import os
import zipfile
import io
import logging
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponse, Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.conf import settings
from .models import Tenant

logger = logging.getLogger(__name__)

AGENT_BLOB_PATH = "agent-binaries/DMSSyncAgent.exe"
AGENT_BLOB_CONTAINER = "system"


def is_superuser(user):
    """Check if user is a superuser (Root-Admin)."""
    return user.is_superuser


def get_agent_exe_from_azure():
    """
    Try to download the DMS Sync Agent EXE from Azure Blob Storage.
    
    Returns:
        bytes: The EXE file content, or None if not available.
    """
    try:
        from dms.azure_storage import get_container_client
        
        container = get_container_client(AGENT_BLOB_CONTAINER)
        if not container:
            logger.debug("Azure container not configured")
            return None
        
        blob_client = container.get_blob_client(AGENT_BLOB_PATH)
        if not blob_client.exists():
            logger.debug(f"Agent binary not found at {AGENT_BLOB_PATH}")
            return None
        
        download_stream = blob_client.download_blob()
        exe_bytes = download_stream.readall()
        logger.info(f"Downloaded agent binary from Azure ({len(exe_bytes)} bytes)")
        return exe_bytes
        
    except Exception as e:
        logger.warning(f"Failed to download agent from Azure: {e}")
        return None


def check_agent_available():
    """
    Check if the real agent EXE is available in Azure.
    
    Returns:
        tuple: (available: bool, size: int or None, version: str or None)
    """
    try:
        from dms.azure_storage import get_container_client
        
        container = get_container_client(AGENT_BLOB_CONTAINER)
        if not container:
            return (False, None, None)
        
        blob_client = container.get_blob_client(AGENT_BLOB_PATH)
        if not blob_client.exists():
            return (False, None, None)
        
        props = blob_client.get_blob_properties()
        size = props.size
        version = props.metadata.get('version', 'unbekannt') if props.metadata else 'unbekannt'
        
        return (True, size, version)
        
    except Exception:
        return (False, None, None)


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
    
    agent_available, agent_size, agent_version = check_agent_available()
    
    context = {
        'title': 'DMS Sync Agent Download',
        'tenants': tenants,
        'agent_available': agent_available,
        'agent_size': agent_size,
        'agent_version': agent_version,
    }
    return render(request, 'admin/dms/agent_download.html', context)


@staff_member_required
@user_passes_test(is_superuser)
def agent_download_zip(request, tenant_id):
    """
    Download the DMS Sync Agent as a ZIP with pre-configured config.yaml.
    
    The ZIP contains:
    - DMSSyncAgent.exe (from Azure Blob Storage or placeholder)
    - config.yaml (pre-configured with tenant token and DMS URL)
    - token.txt (ingest token for this tenant)
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
    
    token_txt = "BITTE_IM_ADMIN_PANEL_NEU_GENERIEREN"
    
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
4. Token installieren: DMSSyncAgent.exe --set-token <Ihr-Token>
   (Generieren Sie einen neuen Token im Admin-Panel unter "Mandanten" -> "Token zurücksetzen")
5. Dienst installieren: DMSSyncAgent.exe --install
6. Dienst starten: DMSSyncAgent.exe --start

HINWEIS: Der Token wird aus Sicherheitsgründen nicht mehr in dieser Datei gespeichert.
Bitte generieren Sie einen Token im Admin-Bereich.

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

    exe_bytes = get_agent_exe_from_azure()
    if exe_bytes is None:
        exe_bytes = b"MZ" + b"\x00" * 100 + b"PLACEHOLDER - Bitte wenden Sie sich an Ihren Administrator fuer die echte EXE-Datei."
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr('DMSSyncAgent/config.yaml', config_yaml)
        zip_file.writestr('DMSSyncAgent/README.txt', readme_txt)
        zip_file.writestr('DMSSyncAgent/token.txt', token_txt)
        zip_file.writestr('DMSSyncAgent/DMSSyncAgent.exe', exe_bytes)
    
    zip_buffer.seek(0)
    
    safe_name = (tenant.code or tenant.name).replace(' ', '_').replace('/', '_')
    filename = f"DMSSyncAgent_{safe_name}.zip"
    
    response = HttpResponse(zip_buffer.read(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@staff_member_required
@user_passes_test(is_superuser)
def agent_upload(request):
    """
    Upload the DMS Sync Agent EXE to Azure Blob Storage.
    Only accessible to Root-Admins (superusers).
    """
    if request.method != 'POST':
        return redirect('dms_agent_download')
    
    exe_file = request.FILES.get('agent_exe')
    version = request.POST.get('version', '').strip() or 'unknown'
    
    if not exe_file:
        messages.error(request, 'Keine Datei ausgewählt.')
        return redirect('dms_agent_download')
    
    if not exe_file.name.endswith('.exe'):
        messages.error(request, 'Nur .exe Dateien sind erlaubt.')
        return redirect('dms_agent_download')
    
    try:
        from dms.azure_storage import get_container_client
        
        container = get_container_client(AGENT_BLOB_CONTAINER)
        if not container:
            messages.error(request, 'Azure Storage ist nicht konfiguriert.')
            return redirect('dms_agent_download')
        
        try:
            container.create_container()
        except Exception:
            pass
        
        blob_client = container.get_blob_client(AGENT_BLOB_PATH)
        
        exe_bytes = exe_file.read()
        blob_client.upload_blob(
            exe_bytes, 
            overwrite=True,
            metadata={'version': version}
        )
        
        messages.success(
            request, 
            f'Agent-Binary v{version} erfolgreich hochgeladen ({len(exe_bytes):,} Bytes).'
        )
        logger.info(f"Agent binary uploaded: version={version}, size={len(exe_bytes)}")
        
    except Exception as e:
        logger.exception("Failed to upload agent binary")
        messages.error(request, f'Upload fehlgeschlagen: {str(e)}')
    
    return redirect('dms_agent_download')
