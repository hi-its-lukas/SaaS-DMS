import os
import sys
import socket

def check_env_var(var_name, required=True, default=None):
    value = os.environ.get(var_name, default)
    if required and not value:
        print(f"❌ MISSING: {var_name} is required but not set.")
        return False
    
    status = "✅" if value else "⚠️"
    display_value = value if value and 'KEY' not in var_name and 'PASSWORD' not in var_name and 'SECRET' not in var_name else '******'
    print(f"{status} {var_name}: {display_value}")
    return True

def verify_environment():
    print("🔍 Starting Environment Verification...")
    
    all_ok = True
    
    print("\n--- Core Security ---")
    if not check_env_var('DJANGO_SECRET_KEY', required=True): all_ok = False
    
    print("\n--- Database Configuration ---")
    # Check if using Azure DB or local
    db_host = os.environ.get('DB_HOST')
    if db_host:
        print(f"ℹ️  Database Mode: Custom/Azure ({db_host})")
        if not check_env_var('DB_NAME'): all_ok = False
        if not check_env_var('DB_USER'): all_ok = False
        if not check_env_var('DB_PASSWORD'): all_ok = False
    else:
        print("ℹ️  Database Mode: DATABASE_URL or SQLite")
        # Just check if DATABASE_URL is present if we aren't in a dev mode that implies sqlite
        if os.environ.get('Simple_Dev_Mode', 'False').lower() != 'true':
             if not check_env_var('DATABASE_URL', required=False): 
                 print("⚠️  No DATABASE_URL found. Will likely default to SQLite or fail if not configured.")

    print("\n--- 2FA / MFA Setup ---")
    mfa_domain = os.environ.get('MFA_DOMAIN')
    print(f"ℹ️  MFA_DOMAIN: {mfa_domain}")
    
    if not mfa_domain:
        print("⚠️  MFA_DOMAIN is not set. FIDO2/WebAuthn might fail.")
        print("   -> For Docker Dev, set MFA_DOMAIN=localhost")
    elif mfa_domain == 'localhost':
        print("✅ MFA_DOMAIN set to localhost (Good for local dev)")
    
    print("\n--- Docker Specifics ---")
    if os.path.exists('/.dockerenv'):
        print("✅ Running inside Docker container.")
    else:
        print("ℹ️  Running on Host Machine (not inside Docker).")

    print("\n--- Network ---")
    try:
        host_name = socket.gethostname() 
        host_ip = socket.gethostbyname(host_name) 
        print(f"ℹ️  Hostname: {host_name}")
        print(f"ℹ️  IP: {host_ip}")
    except:
        print("⚠️  Could not determine Hostname/IP")

    print("\n" + "="*30)
    if all_ok:
        print("✅ Environment looks GOOD.")
        sys.exit(0)
    else:
        print("❌ Environment has ERRORS. Please fix missing variables.")
        sys.exit(1)

if __name__ == "__main__":
    verify_environment()
