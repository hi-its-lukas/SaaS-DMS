"""
Azure Blob Storage connector for DMS SaaS.

Provides utilities for:
- Listing blobs in a container (for Sage archive scanning)
- Downloading blobs to temporary files
- Uploading encrypted documents to blob storage
"""

import os
import tempfile
from pathlib import Path
from typing import Generator, Optional, Tuple
from functools import lru_cache

from azure.storage.blob import BlobServiceClient, ContainerClient
from azure.core.exceptions import ResourceNotFoundError

from dms.encryption import decrypt_data


def get_blob_service_client() -> Optional[BlobServiceClient]:
    """
    Get Azure Blob Service client from SystemSettings.
    Returns None if not configured.
    """
    from dms.models import SystemSettings
    
    settings = SystemSettings.load()
    if not settings.azure_storage_connection_string_encrypted:
        return None
    
    connection_string = decrypt_data(
        settings.azure_storage_connection_string_encrypted
    ).decode('utf-8')
    
    return BlobServiceClient.from_connection_string(connection_string)


def get_container_client(container_name: Optional[str] = None) -> Optional[ContainerClient]:
    """
    Get Azure Blob Container client.
    Uses container name from SystemSettings if not provided.
    """
    from dms.models import SystemSettings
    
    blob_service = get_blob_service_client()
    if not blob_service:
        return None
    
    if not container_name:
        settings = SystemSettings.load()
        container_name = settings.azure_storage_container_name or "documents"
    
    return blob_service.get_container_client(container_name)


def list_sage_archive_blobs(
    prefix: str = "sage-archive/",
    container_name: Optional[str] = None
) -> Generator[Tuple[str, int], None, None]:
    """
    List blobs in the Sage archive folder.
    
    Expected structure: sage-archive/{tenant_code}/{YYYYMM}/{filename}
    
    Args:
        prefix: Blob prefix to filter (default: "sage-archive/")
        container_name: Override container name
    
    Yields:
        Tuple of (blob_name, blob_size)
    """
    container = get_container_client(container_name)
    if not container:
        return
    
    try:
        for blob in container.list_blobs(name_starts_with=prefix):
            if not blob.name.endswith('/'):
                yield (blob.name, blob.size)
    except ResourceNotFoundError:
        return


def download_blob_to_tempfile(
    blob_name: str,
    container_name: Optional[str] = None,
    suffix: Optional[str] = None
) -> Optional[str]:
    """
    Download a blob to a temporary file.
    
    Args:
        blob_name: Full blob path
        container_name: Override container name
        suffix: File suffix for temp file (e.g., ".pdf")
    
    Returns:
        Path to temporary file, or None if download failed.
        Caller is responsible for deleting the temp file.
    """
    container = get_container_client(container_name)
    if not container:
        return None
    
    try:
        blob_client = container.get_blob_client(blob_name)
        
        if not suffix:
            suffix = Path(blob_name).suffix or ""
        
        fd, temp_path = tempfile.mkstemp(suffix=suffix)
        try:
            with os.fdopen(fd, 'wb') as f:
                download_stream = blob_client.download_blob()
                f.write(download_stream.readall())
            return temp_path
        except Exception:
            os.unlink(temp_path)
            raise
    except ResourceNotFoundError:
        return None


def upload_blob(
    blob_name: str,
    data: bytes,
    container_name: Optional[str] = None,
    overwrite: bool = True
) -> bool:
    """
    Upload data to a blob.
    
    Args:
        blob_name: Full blob path
        data: Bytes to upload
        container_name: Override container name
        overwrite: Whether to overwrite existing blob
    
    Returns:
        True if successful, False otherwise
    """
    container = get_container_client(container_name)
    if not container:
        return False
    
    try:
        blob_client = container.get_blob_client(blob_name)
        blob_client.upload_blob(data, overwrite=overwrite)
        return True
    except Exception:
        return False


def upload_blob_stream(
    blob_name: str,
    stream,
    container_name: Optional[str] = None,
    overwrite: bool = True
) -> bool:
    """
    Upload a stream to a blob (for large files).
    
    Args:
        blob_name: Full blob path
        stream: File-like object to upload
        container_name: Override container name
        overwrite: Whether to overwrite existing blob
    
    Returns:
        True if successful, False otherwise
    """
    container = get_container_client(container_name)
    if not container:
        return False
    
    try:
        blob_client = container.get_blob_client(blob_name)
        blob_client.upload_blob(stream, overwrite=overwrite)
        return True
    except Exception:
        return False


def delete_blob(
    blob_name: str,
    container_name: Optional[str] = None
) -> bool:
    """
    Delete a blob.
    
    Args:
        blob_name: Full blob path
        container_name: Override container name
    
    Returns:
        True if successful (or blob didn't exist), False on error
    """
    container = get_container_client(container_name)
    if not container:
        return False
    
    try:
        blob_client = container.get_blob_client(blob_name)
        blob_client.delete_blob()
        return True
    except ResourceNotFoundError:
        return True
    except Exception:
        return False


def blob_exists(
    blob_name: str,
    container_name: Optional[str] = None
) -> bool:
    """
    Check if a blob exists.
    
    Args:
        blob_name: Full blob path
        container_name: Override container name
    
    Returns:
        True if blob exists, False otherwise
    """
    container = get_container_client(container_name)
    if not container:
        return False
    
    try:
        blob_client = container.get_blob_client(blob_name)
        return blob_client.exists()
    except Exception:
        return False


def parse_sage_blob_path(blob_name: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Parse a Sage archive blob path into components.
    
    Expected format: sage-archive/{tenant_code}/{YYYYMM}/{filename}
    
    Args:
        blob_name: Full blob path
    
    Returns:
        Tuple of (tenant_code, month_folder, filename) or (None, None, None)
    """
    parts = blob_name.split('/')
    
    if len(parts) < 4 or parts[0] != 'sage-archive':
        return (None, None, None)
    
    tenant_code = parts[1]
    month_folder = parts[2] if len(parts[2]) == 6 and parts[2].isdigit() else None
    filename = parts[-1]
    
    return (tenant_code, month_folder, filename)
