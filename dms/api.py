"""
DMS REST API Endpoints

Provides stateless API endpoints for document ingest from external sources
(e.g., local scanner .exe, third-party integrations).

Authentication is via X-DMS-Token header using Tenant.ingest_token.
"""
import json
import uuid
from io import BytesIO
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.utils import timezone
from django.db import transaction

from .models import Tenant, Document, ProcessedFile, SystemLog
from .encryption import encrypt_stream_to_blob, mask_ip_address


def log_api_event(tenant, level, source, message, details=None):
    """Log API events with tenant isolation."""
    SystemLog.objects.create(
        tenant=tenant,
        level=level,
        source=source,
        message=message,
        details=details or {}
    )


def get_client_ip(request):
    """Extract client IP from request, handling proxies."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return mask_ip_address(ip)


@csrf_exempt
@require_http_methods(["POST"])
def api_upload_document(request):
    """
    API endpoint for document upload.
    
    Endpoint: POST /api/v1/ingest/document/
    Auth: Header X-DMS-Token: <tenant.ingest_token>
    
    Body: multipart/form-data with:
        - file: The document file (required)
        - filename: Original filename (optional, uses uploaded filename)
        - document_type: Document type code (optional)
        - employee_id: Employee ID to assign (optional)
        - metadata: JSON object with additional metadata (optional)
    
    Returns:
        - 200: {"status": "success", "document_id": "<uuid>", "hash": "<sha256>"}
        - 400: {"error": "Bad request description"}
        - 401: {"error": "Missing Token"}
        - 403: {"error": "Invalid Token"}
        - 413: {"error": "File too large"}
        - 500: {"error": "Internal error"}
    """
    # 1. Authenticate via token
    token = request.headers.get('X-DMS-Token')
    if not token:
        return JsonResponse({'error': 'Missing Token'}, status=401)
    
    try:
        tenant = Tenant.objects.select_related('company').get(
            ingest_token=token, 
            is_active=True
        )
    except Tenant.DoesNotExist:
        return JsonResponse({'error': 'Invalid Token'}, status=403)
    
    # Check if company is active
    if tenant.company and not tenant.company.is_active:
        return JsonResponse({'error': 'Company suspended'}, status=403)
    
    # 2. Validate file
    if 'file' not in request.FILES:
        log_api_event(tenant, 'WARNING', 'api.upload', 'Upload attempt without file')
        return JsonResponse({'error': 'No file provided'}, status=400)
    
    uploaded_file = request.FILES['file']
    
    # Check file size (max 100MB)
    max_size = 100 * 1024 * 1024
    if uploaded_file.size > max_size:
        log_api_event(tenant, 'WARNING', 'api.upload', 
                     f'File too large: {uploaded_file.size} bytes',
                     {'filename': uploaded_file.name})
        return JsonResponse({
            'error': f'File too large. Maximum size: {max_size // (1024*1024)}MB'
        }, status=413)
    
    # 3. Extract metadata
    original_filename = request.POST.get('filename', uploaded_file.name)
    document_type_code = request.POST.get('document_type')
    employee_id = request.POST.get('employee_id')
    metadata_json = request.POST.get('metadata', '{}')
    
    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError:
        metadata = {}
    
    client_ip = get_client_ip(request)
    
    try:
        with transaction.atomic():
            # 4. Generate document ID
            doc_id = uuid.uuid4()
            
            # 5. Encrypt file using streaming encryption
            input_stream = uploaded_file.file
            output_stream = BytesIO()
            
            sha256_hash, original_size, encrypted_size = encrypt_stream_to_blob(
                input_stream, output_stream
            )
            
            encrypted_content = output_stream.getvalue()
            
            # 6. Check for duplicates using hash
            existing = ProcessedFile.objects.filter(
                tenant=tenant,
                file_hash=sha256_hash
            ).first()
            
            if existing:
                log_api_event(tenant, 'INFO', 'api.upload',
                             f'Duplicate file skipped: {original_filename}',
                             {'hash': sha256_hash, 'existing_id': str(existing.document_id)})
                return JsonResponse({
                    'status': 'duplicate',
                    'message': 'File already exists',
                    'existing_document_id': str(existing.document_id) if existing.document else None,
                    'hash': sha256_hash
                }, status=200)
            
            # 7. Create document record
            document = Document(
                id=doc_id,
                tenant=tenant,
                original_filename=original_filename,
                encrypted_content=encrypted_content,
                file_size=original_size,
                file_hash=sha256_hash,
                status='UNASSIGNED',
                source='API',
            )
            
            # Assign document type if provided
            if document_type_code:
                from .models import DocumentType
                try:
                    doc_type = DocumentType.objects.get(
                        code=document_type_code,
                        tenant=tenant
                    )
                    document.document_type = doc_type
                except DocumentType.DoesNotExist:
                    pass
            
            # Assign employee if provided
            if employee_id:
                from .models import Employee
                try:
                    employee = Employee.objects.get(
                        id=employee_id,
                        tenant=tenant
                    )
                    document.employee = employee
                    document.status = 'ASSIGNED'
                except Employee.DoesNotExist:
                    pass
            
            document.save()
            
            # 8. Create processed file record
            ProcessedFile.objects.create(
                tenant=tenant,
                source_path=f"api://{client_ip}/{original_filename}",
                file_hash=sha256_hash,
                document=document,
                status='COMPLETED',
                processed_at=timezone.now()
            )
            
            log_api_event(tenant, 'INFO', 'api.upload',
                         f'Document uploaded: {original_filename}',
                         {
                             'document_id': str(doc_id),
                             'hash': sha256_hash,
                             'size': original_size,
                             'ip': client_ip
                         })
            
            return JsonResponse({
                'status': 'success',
                'document_id': str(doc_id),
                'hash': sha256_hash,
                'size': original_size
            }, status=200)
    
    except Exception as e:
        log_api_event(tenant, 'ERROR', 'api.upload',
                     f'Upload failed: {str(e)}',
                     {'filename': original_filename})
        return JsonResponse({
            'error': 'Internal server error'
        }, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def api_health(request):
    """
    Health check endpoint.
    
    Endpoint: GET /api/v1/health/
    
    Returns: {"status": "ok", "version": "1.0"}
    """
    return JsonResponse({
        'status': 'ok',
        'version': '1.0',
        'timestamp': timezone.now().isoformat()
    })


@csrf_exempt
@require_http_methods(["GET"])
def api_tenant_info(request):
    """
    Get tenant information for authenticated token.
    
    Endpoint: GET /api/v1/tenant/
    Auth: Header X-DMS-Token: <tenant.ingest_token>
    
    Returns tenant name, ingest email, and basic stats.
    """
    token = request.headers.get('X-DMS-Token')
    if not token:
        return JsonResponse({'error': 'Missing Token'}, status=401)
    
    try:
        tenant = Tenant.objects.select_related('company').get(
            ingest_token=token, 
            is_active=True
        )
    except Tenant.DoesNotExist:
        return JsonResponse({'error': 'Invalid Token'}, status=403)
    
    return JsonResponse({
        'tenant_name': tenant.name,
        'company_name': tenant.company.name if tenant.company else None,
        'ingest_email': f"upload.{tenant.ingest_token}@dms.cloud" if tenant.ingest_token else None,
        'document_count': tenant.documents.count(),
        'employee_count': tenant.employees.count() if hasattr(tenant, 'employees') else 0
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_agent_heartbeat(request):
    """
    Agent heartbeat endpoint for status monitoring.
    
    Endpoint: POST /api/v1/agent/heartbeat/
    Auth: Header X-DMS-Token: <tenant.ingest_token>
    
    Body (JSON):
        - version: Agent version string
        - status: Agent status (running, idle, error)
        - queue_size: Number of files in upload queue
    
    Returns:
        - 200: {"status": "ok", "update_available": false, "latest_version": "1.0.0"}
    """
    token = request.headers.get('X-DMS-Token')
    if not token:
        return JsonResponse({'error': 'Missing Token'}, status=401)
    
    try:
        tenant = Tenant.objects.get(ingest_token=token, is_active=True)
    except Tenant.DoesNotExist:
        return JsonResponse({'error': 'Invalid Token'}, status=403)
    
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}
    
    agent_version = data.get('version', 'unknown')
    agent_status = data.get('status', 'unknown')
    queue_size = data.get('queue_size', 0)
    
    client_ip = get_client_ip(request)
    
    tenant.agent_last_seen = timezone.now()
    tenant.agent_version = agent_version
    tenant.agent_status = agent_status
    tenant.agent_queue_size = queue_size
    tenant.agent_ip = client_ip
    tenant.save(update_fields=[
        'agent_last_seen', 'agent_version', 'agent_status', 
        'agent_queue_size', 'agent_ip'
    ])
    
    latest_version = "1.0.0"
    update_available = agent_version != latest_version and agent_version != "unknown"
    
    return JsonResponse({
        'status': 'ok',
        'update_available': update_available,
        'latest_version': latest_version
    })
