import os
import hashlib
from cryptography.fernet import Fernet
from django.conf import settings


def get_encryption_key():
    key = settings.ENCRYPTION_KEY
    if not key:
        key = os.environ.get('ENCRYPTION_KEY')
    if not key:
        raise ValueError("ENCRYPTION_KEY environment variable is not set. Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
    if isinstance(key, str):
        key = key.encode()
    return key


def get_fernet():
    return Fernet(get_encryption_key())


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


def encrypt_file(file_path):
    with open(file_path, 'rb') as f:
        data = f.read()
    return encrypt_data(data), calculate_sha256(data)


def decrypt_to_bytes(encrypted_data):
    return decrypt_data(encrypted_data)
