@shared_task(bind=True, max_retries=3)
def process_imported_document(self, document_id):
    """
    Verarbeitet ein importiertes Dokument asynchron.
    - Entschlüsselt Dokument
    - Prüft auf DataMatrix-Codes (Sage)
    - Teilt PDF bei Bedarf (Lohnscheine)
    - Führt Auto-Klassifizierung durch
    - Erstellt Aufgaben bei Klärungsbedarf
    """
    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        logger.error(f"ProcessDocument: Document {document_id} not found")
        return "Document not found"
        
    log_system_event('INFO', 'ProcessDocument', f"Starte Verarbeitung für {document.original_filename} ({document_id})",
                     {'tenant': document.tenant.code if document.tenant else 'global'})

    try:
        # Tenant Kontext setzen
        with tenant_context(document.tenant):
            # 1. Inhalt entschlüsseln und temporär speichern (für PDF Processing)
            decrypted_content = decrypt_data(document.encrypted_content)
            
            with tempfile.NamedTemporaryFile(suffix=document.file_extension, delete=False) as temp_file:
                temp_file.write(decrypted_content)
                temp_file_path = temp_file.name
                
            try:
                # 2. Prüfen ob PDF und Verarbeitung notwendig
                is_pdf = document.mime_type == 'application/pdf' or document.file_extension.lower() == '.pdf'
                
                dm_result = None
                split_occurred = False
                
                if is_pdf:
                    # Klassifizierung vorab prüfen um zu sehen ob es Personaldokumente sein könnten
                    doc_type_guess, is_personnel_guess, _, _ = classify_sage_document(document.original_filename)
                    
                    if is_personnel_guess:
                         # Versuch Split wenn DataMatrix vorhanden
                        split_output_dir = Path(settings.BASE_DIR) / 'data' / 'split_temp' / (document.tenant.code if document.tenant else 'global')
                        split_results = split_pdf_by_datamatrix(temp_file_path, str(split_output_dir))
                        
                        if split_results and len(split_results) > 1:
                            # SPLIT FALL
                            log_system_event('INFO', 'ProcessDocument', f"PDF Split erfolgreich: {len(split_results)} Teile")
                            
                            for split_info in split_results:
                                _create_split_document(document, split_info, decrypted_content=None) # Helper creates new docs
                                
                            # Original Dokument archivieren/löschen da aufgeteilt
                            document.status = 'ARCHIVED'
                            document.notes += "\nAutomatisch aufgeteilt und archiviert."
                            document.save(update_fields=['status', 'notes', 'updated_at'])
                            split_occurred = True
                        
                        else:
                             # Kein Split, aber vielleicht Einzel-DataMatrix?
                             dm_result = extract_employee_from_datamatrix(temp_file_path)

                if not split_occurred:
                    # 3. Metadaten extrahieren und anreichern
                    metadata = document.metadata or {}
                    
                    if dm_result and dm_result['success']:
                         metadata['datamatrix'] = {
                            'codes_found': len(dm_result['codes']),
                            'employee_ids': dm_result['employee_ids']
                         }
                         
                         # Mandant Code aus DataMatrix prüfen
                         if dm_result.get('mandant_code'):
                             metadata['mandant_code_dm'] = dm_result.get('mandant_code')
                    
                    # 4. Klassifizierung & Zuordnung
                    doc_type, is_personnel, category, description = classify_sage_document(document.original_filename)
                    
                    employee = document.employee
                    if not employee and dm_result and dm_result.get('employee_ids'):
                        for emp_id in dm_result['employee_ids']:
                            employee = find_employee_by_id(emp_id, tenant=document.tenant, mandant_code=dm_result.get('mandant_code'))
                            if employee:
                                break
                    
                    # Update Document
                    document.document_type = get_or_create_document_type(doc_type, description, category, document.tenant) if doc_type != 'UNBEKANNT' else None
                    document.employee = employee
                    
                    if employee:
                        document.status = 'ASSIGNED'
                    elif is_personnel:
                        document.status = 'REVIEW_NEEDED'
                    elif doc_type != 'UNBEKANNT':
                        document.status = 'COMPANY'
                        
                    # Metadaten update
                    metadata.update({
                        'doc_type': doc_type,
                        'is_personnel_document': is_personnel,
                        'doc_type_description': description,
                        'processed_at': str(timezone.now())
                    })
                    document.metadata = metadata
                    document.save()
                    
                    # 5. Auto-Classify Regelwerk anwenden
                    auto_classify_document(document, tenant=document.tenant)
                    
                    # 6. Tasks erstellen falls nötig
                    if document.status == 'REVIEW_NEEDED':
                        create_review_task(document, source='API_UPLOAD')
                        
                    log_system_event('INFO', 'ProcessDocument', f"Verarbeitung abgeschlossen. Status: {document.status}")

            finally:
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
                    
    except Exception as e:
        logger.error(f"Error processing document {document_id}: {e}")
        log_system_event('ERROR', 'ProcessDocument', f"Fehler bei Verarbeitung: {e}", {'doc_id': str(document_id)})
        raise self.retry(exc=e, countdown=60)


def _create_split_document(parent_doc, split_info, decrypted_content=None):
    """
    Helper to create a new document from a split result.
    """
    from .models import Document, ProcessedFile
    
    split_path = Path(split_info['file_path'])
    
    with open(split_path, 'rb') as f:
        content = f.read()
    
    encrypted = encrypt_data(content)
    file_hash = calculate_sha256(content)
    
    # Metadata parsing
    emp_id = split_info.get('employee_id')
    tenant = parent_doc.tenant
    
    employee = find_employee_by_id(emp_id, tenant=tenant)
    
    doc_type, _, category, desc = classify_sage_document(parent_doc.original_filename)
    
    new_doc = Document.objects.create(
        tenant=tenant,
        title=f"{parent_doc.title} (Teil)",
        original_filename=split_path.name,
        file_extension='.pdf',
        mime_type='application/pdf',
        encrypted_content=encrypted,
        file_size=len(content),
        employee=employee,
        status='ASSIGNED' if employee else 'REVIEW_NEEDED',
        source=parent_doc.source,
        sha256_hash=file_hash,
        metadata={
            'split_from': str(parent_doc.id),
            'original_filename': parent_doc.original_filename,
            'employee_id_dm': emp_id
        }
    )
    
    # Document Type assignment
    if doc_type != 'UNBEKANNT':
        new_doc.document_type = get_or_create_document_type(doc_type, desc, category, tenant)
        new_doc.save(update_fields=['document_type'])

    if new_doc.status == 'REVIEW_NEEDED':
        create_review_task(new_doc, source='SPLIT')
        
    # Cleanup split file
    try:
        split_path.unlink()
    except:
        pass
        
    return new_doc
