import json
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q

from .models import Document, Employee, Task
from .encryption import encrypt_data, decrypt_data, calculate_sha256
import magic


@login_required
def index(request):
    recent_documents = Document.objects.all()[:10]
    open_tasks = Task.objects.filter(status='OPEN')[:5]
    
    stats = {
        'total_documents': Document.objects.count(),
        'unassigned': Document.objects.filter(status='UNASSIGNED').count(),
        'review_needed': Document.objects.filter(status='REVIEW_NEEDED').count(),
        'open_tasks': Task.objects.filter(status='OPEN').count(),
    }
    
    return render(request, 'dms/index.html', {
        'recent_documents': recent_documents,
        'open_tasks': open_tasks,
        'stats': stats,
    })


@login_required
def upload_page(request):
    return render(request, 'dms/upload.html')


def _can_access_document(user, document):
    if user.has_perm('dms.view_all_documents'):
        return True
    if document.owner == user:
        return True
    if hasattr(user, 'employee_profile') and document.employee == user.employee_profile:
        return True
    return False


@login_required
@csrf_protect
@require_http_methods(["POST"])
def upload_file(request):
    if 'file' not in request.FILES:
        return JsonResponse({'success': False, 'error': 'No file provided'}, status=400)
    
    uploaded_file = request.FILES['file']
    
    max_size = 50 * 1024 * 1024
    if uploaded_file.size > max_size:
        return JsonResponse({'success': False, 'error': 'File too large (max 50MB)'}, status=400)
    
    allowed_extensions = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.jpg', '.jpeg', '.png', '.tiff', '.txt'}
    file_ext = '.' + uploaded_file.name.rsplit('.', 1)[-1].lower() if '.' in uploaded_file.name else ''
    if file_ext not in allowed_extensions:
        return JsonResponse({'success': False, 'error': 'File type not allowed'}, status=400)
    
    try:
        content = uploaded_file.read()
        file_hash = calculate_sha256(content)
        encrypted_content = encrypt_data(content)
        
        try:
            mime_type = magic.from_buffer(content, mime=True)
        except Exception:
            mime_type = uploaded_file.content_type or 'application/octet-stream'
        
        title = request.POST.get('title', uploaded_file.name.rsplit('.', 1)[0])
        
        document = Document.objects.create(
            title=title,
            original_filename=uploaded_file.name,
            file_extension=file_ext,
            mime_type=mime_type,
            encrypted_content=encrypted_content,
            file_size=len(content),
            status='UNASSIGNED',
            source='WEB',
            sha256_hash=file_hash,
            owner=request.user,
        )
        
        return JsonResponse({
            'success': True,
            'document_id': str(document.id),
            'message': 'File uploaded successfully'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': 'Upload failed. Please try again.'}, status=500)


@login_required
def document_list(request):
    if request.user.has_perm('dms.view_all_documents'):
        documents = Document.objects.all()
    elif hasattr(request.user, 'employee_profile'):
        documents = Document.objects.filter(
            Q(employee=request.user.employee_profile) | Q(owner=request.user)
        )
    else:
        documents = Document.objects.filter(owner=request.user)
    
    status = request.GET.get('status')
    source = request.GET.get('source')
    search = request.GET.get('search')
    
    if status:
        documents = documents.filter(status=status)
    if source:
        documents = documents.filter(source=source)
    if search:
        documents = documents.filter(
            Q(title__icontains=search) | 
            Q(original_filename__icontains=search)
        )
    
    paginator = Paginator(documents, 25)
    page = request.GET.get('page', 1)
    documents = paginator.get_page(page)
    
    return render(request, 'dms/document_list.html', {
        'documents': documents,
        'status_choices': Document.STATUS_CHOICES,
        'source_choices': Document.SOURCE_CHOICES,
    })


@login_required
def document_detail(request, pk):
    document = get_object_or_404(Document, pk=pk)
    
    if not _can_access_document(request.user, document):
        return HttpResponse('Permission denied', status=403)
    
    return render(request, 'dms/document_detail.html', {'document': document})


@login_required
def document_download(request, pk):
    document = get_object_or_404(Document, pk=pk)
    
    if not _can_access_document(request.user, document):
        return HttpResponse('Permission denied', status=403)
    
    try:
        decrypted_content = decrypt_data(document.encrypted_content)
        
        response = HttpResponse(
            decrypted_content,
            content_type=document.mime_type or 'application/octet-stream'
        )
        response['Content-Disposition'] = f'attachment; filename="{document.original_filename}"'
        return response
    except Exception as e:
        return HttpResponse('Error downloading file', status=500)


@login_required
def task_list(request):
    if request.user.has_perm('dms.manage_documents'):
        tasks = Task.objects.all()
    else:
        tasks = Task.objects.filter(assigned_to=request.user)
    
    status = request.GET.get('status')
    if status:
        tasks = tasks.filter(status=status)
    
    paginator = Paginator(tasks, 25)
    page = request.GET.get('page', 1)
    tasks = paginator.get_page(page)
    
    return render(request, 'dms/task_list.html', {
        'tasks': tasks,
        'status_choices': Task.STATUS_CHOICES,
    })


@login_required
@require_http_methods(["POST"])
def task_complete(request, pk):
    task = get_object_or_404(Task, pk=pk)
    
    if not request.user.has_perm('dms.manage_documents'):
        if task.assigned_to != request.user:
            return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
    
    task.complete()
    return JsonResponse({'success': True, 'message': 'Task completed'})
