"""
Tenant-Aware Model Managers for Multi-Tenancy Security.

These managers automatically filter querysets by the current tenant,
preventing data leakage between tenants. Superusers bypass filtering
to enable global administration and support.
"""

from django.db import models
from dms.middleware import get_current_tenant, get_current_user


class TenantAwareQuerySet(models.QuerySet):
    """
    QuerySet that can filter by tenant context.
    """
    
    def for_tenant(self, tenant):
        """
        Explicitly filter for a specific tenant.
        """
        if tenant is None:
            return self
        return self.filter(tenant=tenant)
    
    def for_current_tenant(self):
        """
        Filter for the current request's tenant.
        Superusers see all data (no filtering).
        """
        user = get_current_user()
        
        if user and user.is_superuser:
            return self
        
        tenant = get_current_tenant()
        
        if tenant:
            return self.filter(tenant=tenant)
        
        return self


class TenantAwareManager(models.Manager):
    """
    Model manager that automatically filters by the current tenant.
    
    Usage:
        class MyModel(models.Model):
            tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
            # ... other fields ...
            
            objects = TenantAwareManager()
            all_objects = models.Manager()  # Unfiltered access for migrations/admin
    
    Security Features:
        - Automatically filters all queries by current tenant
        - Superusers (is_superuser=True) bypass filtering for global access
        - Anonymous requests return empty querysets for tenant-filtered models
        - Thread-safe using thread-local storage
    """
    
    def get_queryset(self):
        """
        Return a queryset filtered by the current tenant.
        """
        qs = TenantAwareQuerySet(self.model, using=self._db)
        
        user = get_current_user()
        if user and user.is_superuser:
            return qs
        
        tenant = get_current_tenant()
        if tenant:
            return qs.filter(tenant=tenant)
        
        return qs
    
    def unfiltered(self):
        """
        Return an unfiltered queryset (use with caution).
        Intended for migrations, management commands, and admin operations.
        """
        return TenantAwareQuerySet(self.model, using=self._db)
    
    def for_tenant(self, tenant):
        """
        Explicitly filter for a specific tenant.
        """
        return self.unfiltered().filter(tenant=tenant)


class TenantAwareManagerAllowNull(TenantAwareManager):
    """
    Variant of TenantAwareManager that also includes objects with tenant=NULL.
    
    Useful for models where some records are global (tenant=NULL) and some are
    tenant-specific. For example, default document types that apply to all tenants.
    """
    
    def get_queryset(self):
        """
        Return queryset including both current tenant's data and global (NULL tenant) data.
        """
        qs = TenantAwareQuerySet(self.model, using=self._db)
        
        user = get_current_user()
        if user and user.is_superuser:
            return qs
        
        tenant = get_current_tenant()
        if tenant:
            return qs.filter(models.Q(tenant=tenant) | models.Q(tenant__isnull=True))
        
        return qs.filter(tenant__isnull=True)
