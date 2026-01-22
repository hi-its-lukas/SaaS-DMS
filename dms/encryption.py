import os
import hashlib
import secrets
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings


# Streaming encryption constants
CHUNK_SIZE = 64 * 1024  # 64KB chunks for streaming
NONCE_SIZE = 12  # 96-bit nonce for AES-GCM


def get_encryption_key():
    """Get the master encryption key (KEK - Key Encryption Key)."""
    key = settings.ENCRYPTION_KEY
    if not key:
        key = os.environ.get('ENCRYPTION_KEY')
    if not key:
        raise ValueError("ENCRYPTION_KEY environment variable is not set. Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
    if isinstance(key, str):
        key = key.encode()
    return key


def get_fernet():
    """Get Fernet instance for legacy encryption."""
    return Fernet(get_encryption_key())


def get_aesgcm_key():
    """
    Derive a 256-bit AES key from the Fernet key for streaming encryption.
    Uses first 32 bytes of base64-decoded Fernet key.
    """
    import base64
    fernet_key = get_encryption_key()
    raw_key = base64.urlsafe_b64decode(fernet_key)
    return raw_key[:32]  # AES-256 requires 32 bytes


def encrypt_data(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    fernet = get_fernet()
    return fernet.encrypt(data)


def decrypt_data(encrypted_data):
    if isinstance(encrypted_data, memoryview):
        encrypted_data = bytes(encrypted_data)
    fernet = get_fernet()
    return fernet.decrypt(encrypted_data)


def calculate_sha256(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def calculate_sha256_chunked(file_path, chunk_size=65536):
    """
    Berechnet SHA256 eines Files per Streaming ohne gesamte Datei in RAM zu laden.
    Paperless-ngx-Style: 64KB Chunks für optimale Performance.
    """
    sha256_hash = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


# SECURITY: Maximale Dateigröße für Verschlüsselung (100 MB)
# Fernet lädt alles in den RAM, daher muss ein Limit gesetzt werden
MAX_ENCRYPTION_FILE_SIZE = 100 * 1024 * 1024  # 100 MB


def encrypt_file(file_path):
    """
    Verschlüsselt eine Datei und berechnet den Hash.
    
    WARNUNG: Lädt die gesamte Datei in den Speicher.
    Für große Dateien encrypt_file_streaming verwenden.
    
    Raises: ValueError wenn Datei zu groß ist
    """
    # SECURITY: Dateigröße prüfen bevor in RAM geladen wird
    file_stats = os.stat(file_path)
    if file_stats.st_size > MAX_ENCRYPTION_FILE_SIZE:
        raise ValueError(
            f"Datei zu groß für Verschlüsselung ({file_stats.st_size / 1024 / 1024:.1f} MB). "
            f"Maximum: {MAX_ENCRYPTION_FILE_SIZE / 1024 / 1024:.0f} MB"
        )
    
    with open(file_path, 'rb') as f:
        data = f.read()
    return encrypt_data(data), calculate_sha256(data)


def encrypt_file_streaming(file_path, chunk_size=1048576):
    """
    Verschlüsselt Datei und berechnet Hash in einem Durchgang.
    1MB Chunks für Verschlüsselung, 64KB für Hash.
    
    WARNUNG: Fernet unterstützt kein echtes Streaming.
    Die gesamte Datei wird in den Speicher geladen.
    Dateigröße wird vorher geprüft.
    
    Returns: (encrypted_bytes, sha256_hash, file_size)
    
    Raises: ValueError wenn Datei zu groß ist
    """
    # SECURITY: Dateigröße prüfen bevor in RAM geladen wird
    file_stats = os.stat(file_path)
    if file_stats.st_size > MAX_ENCRYPTION_FILE_SIZE:
        raise ValueError(
            f"Datei zu groß für Verschlüsselung ({file_stats.st_size / 1024 / 1024:.1f} MB). "
            f"Maximum: {MAX_ENCRYPTION_FILE_SIZE / 1024 / 1024:.0f} MB"
        )
    
    sha256_hash = hashlib.sha256()
    chunks = []
    file_size = 0
    
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            sha256_hash.update(chunk)
            chunks.append(chunk)
            file_size += len(chunk)
    
    content = b''.join(chunks)
    encrypted = encrypt_data(content)
    
    return encrypted, sha256_hash.hexdigest(), file_size


def decrypt_to_bytes(encrypted_data):
    return decrypt_data(encrypted_data)


# =============================================================================
# TRUE STREAMING ENCRYPTION (AES-GCM)
# These functions use chunk-based encryption for large files without loading
# the entire file into memory. Suitable for Azure Blob upload streams.
# =============================================================================

def encrypt_stream_to_blob(input_stream, output_stream, chunk_size=CHUNK_SIZE):
    """
    Encrypt data from input stream to output stream using AES-GCM.
    Each chunk is encrypted separately with a unique nonce.
    
    Format per chunk: [4 bytes length][12 bytes nonce][encrypted_chunk with tag]
    Length field contains the size of encrypted_chunk (including 16-byte tag).
    
    Args:
        input_stream: File-like object to read from
        output_stream: File-like object to write encrypted data to
        chunk_size: Size of chunks to process (default 64KB)
    
    Returns:
        (sha256_hash, total_bytes_read, total_bytes_written)
    """
    import struct
    aesgcm = AESGCM(get_aesgcm_key())
    sha256_hash = hashlib.sha256()
    total_read = 0
    total_written = 0
    
    while True:
        chunk = input_stream.read(chunk_size)
        if not chunk:
            break
        
        # Update hash with original data
        sha256_hash.update(chunk)
        total_read += len(chunk)
        
        # Generate unique nonce for this chunk
        nonce = secrets.token_bytes(NONCE_SIZE)
        
        # Encrypt chunk with AEAD (ciphertext includes 16-byte auth tag)
        encrypted_chunk = aesgcm.encrypt(nonce, chunk, None)
        
        # Write: [length (4 bytes, big-endian)][nonce][encrypted_chunk]
        length_bytes = struct.pack('>I', len(encrypted_chunk))
        output_stream.write(length_bytes)
        output_stream.write(nonce)
        output_stream.write(encrypted_chunk)
        total_written += 4 + NONCE_SIZE + len(encrypted_chunk)
    
    return sha256_hash.hexdigest(), total_read, total_written


def decrypt_stream_from_blob(input_stream, output_stream, chunk_size=CHUNK_SIZE):
    """
    Decrypt data from input stream to output stream using AES-GCM.
    
    Format per chunk: [4 bytes length][12 bytes nonce][encrypted_chunk with tag]
    
    Args:
        input_stream: File-like object with encrypted data
        output_stream: File-like object to write decrypted data to
        chunk_size: Original chunk size used during encryption (default 64KB, ignored - uses length prefix)
    
    Returns:
        total_bytes_written
    """
    import struct
    aesgcm = AESGCM(get_aesgcm_key())
    total_written = 0
    
    while True:
        # Read length prefix (4 bytes, big-endian)
        length_bytes = input_stream.read(4)
        if not length_bytes or len(length_bytes) < 4:
            break
        
        encrypted_length = struct.unpack('>I', length_bytes)[0]
        
        # Read nonce (12 bytes)
        nonce = input_stream.read(NONCE_SIZE)
        if not nonce or len(nonce) < NONCE_SIZE:
            raise ValueError("Truncated stream: missing nonce")
        
        # Read encrypted chunk + tag
        encrypted_chunk = input_stream.read(encrypted_length)
        if len(encrypted_chunk) < encrypted_length:
            raise ValueError("Truncated stream: incomplete encrypted chunk")
        
        # Decrypt
        decrypted = aesgcm.decrypt(nonce, encrypted_chunk, None)
        output_stream.write(decrypted)
        total_written += len(decrypted)
    
    return total_written


def encrypt_bytes_streaming(data, chunk_size=CHUNK_SIZE):
    """
    Encrypt bytes using streaming encryption.
    Useful for in-memory data that should use the same format as stream encryption.
    
    Returns: encrypted_bytes
    """
    from io import BytesIO
    input_stream = BytesIO(data)
    output_stream = BytesIO()
    encrypt_stream_to_blob(input_stream, output_stream, chunk_size)
    return output_stream.getvalue()


def decrypt_bytes_streaming(encrypted_data, chunk_size=CHUNK_SIZE):
    """
    Decrypt bytes that were encrypted with streaming encryption.
    
    Returns: decrypted_bytes
    """
    from io import BytesIO
    input_stream = BytesIO(encrypted_data)
    output_stream = BytesIO()
    decrypt_stream_from_blob(input_stream, output_stream, chunk_size)
    return output_stream.getvalue()


# =============================================================================
# GDPR UTILITIES
# =============================================================================

def mask_ip_address(ip_address):
    """
    Mask IP address for GDPR compliance.
    IPv4: Last octet set to 0 (e.g., 192.168.1.100 -> 192.168.1.0)
    IPv6: Last 80 bits masked (e.g., 2001:db8::1 -> 2001:db8::)
    
    Returns: Masked IP address string or None
    """
    if not ip_address:
        return None
    
    ip_address = str(ip_address).strip()
    
    if ':' in ip_address:
        # IPv6: Mask last 80 bits (keep first 48 bits)
        parts = ip_address.split(':')
        if len(parts) >= 3:
            return ':'.join(parts[:3]) + '::'
        return ip_address
    else:
        # IPv4: Zero last octet
        parts = ip_address.split('.')
        if len(parts) == 4:
            parts[3] = '0'
            return '.'.join(parts)
        return ip_address
