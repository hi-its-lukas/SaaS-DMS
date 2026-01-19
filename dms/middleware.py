"""
Tenant Middleware for Multi-Tenancy SaaS Architecture.

This middleware identifies the current tenant based on the logged-in user
and stores it in thread-local storage for access throughout the request lifecycle.
"""

import threading
from django.utils.deprecation import MiddlewareMixin

_thread_locals = threading.local()


def get_current_tenant():
    """
    Retrieve the current tenant from thread-local storage.
    Returns None if no tenant is set (e.g., anonymous user or superuser).
    """
    return getattr(_thread_locals, 'tenant', None)


def get_current_user():
    """
    Retrieve the current user from thread-local storage.
    """
    return getattr(_thread_locals, 'user', None)


def set_current_tenant(tenant):
    """
    Set the current tenant in thread-local storage.
    """
    _thread_locals.tenant = tenant


def set_current_user(user):
    """
    Set the current user in thread-local storage.
    """
    _thread_locals.user = user


def clear_tenant_context():
    """
    Clear tenant context from thread-local storage.
    Called at the end of each request to prevent data leakage.
    """
    _thread_locals.tenant = None
    _thread_locals.user = None


class TenantMiddleware(MiddlewareMixin):
    """
    Middleware that identifies the current tenant based on the authenticated user.
    
    For SaaS single-URL architecture (e.g., app.dms.cloud), the tenant is determined
    by the user's TenantUser membership rather than subdomain.
    
    Superusers (is_superuser=True) are NOT assigned a tenant, giving them
    global access for support and administration purposes.
    """
    
    def process_request(self, request):
        """
        Identify tenant at the start of each request.
        """
        clear_tenant_context()
        
        if not hasattr(request, 'user') or not request.user.is_authenticated:
            return None
        
        user = request.user
        set_current_user(user)
        
        if user.is_superuser:
            request.tenant = None
            return None
        
        tenant = self._get_user_tenant(user)
        
        if tenant:
            set_current_tenant(tenant)
            request.tenant = tenant
        else:
            request.tenant = None
        
        return None
    
    def _get_user_tenant(self, user):
        """
        Get the primary tenant for a user.
        Returns the first active tenant membership.
        """
        from dms.models import TenantUser
        
        try:
            tenant_user = TenantUser.objects.select_related('tenant').filter(
                user=user,
                tenant__is_active=True
            ).first()
            
            if tenant_user:
                return tenant_user.tenant
        except Exception:
            pass
        
        return None
    
    def process_response(self, request, response):
        """
        Clean up tenant context after response is generated.
        Prevents data leakage between requests in the same thread.
        """
        clear_tenant_context()
        return response
    
    def process_exception(self, request, exception):
        """
        Clean up tenant context on exception.
        """
        clear_tenant_context()
        return None
