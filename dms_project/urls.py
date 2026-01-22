from django.contrib import admin
from django.urls import path, include, re_path
from django.contrib.auth import views as auth_views
from mfa.views import LoginView as MFALoginView
from dms.admin_views import agent_download_page, agent_download_zip

urlpatterns = [
    # Custom admin URLs (must be before admin.site.urls)
    path('admin/dms/agent-download/', agent_download_page, name='dms_agent_download'),
    path('admin/dms/agent-download/<int:tenant_id>/', agent_download_zip, name='dms_agent_download_zip'),
    
    path('admin/', admin.site.urls),
    path('mfa/', include('mfa.urls', namespace='mfa')),
    path('login/', MFALoginView.as_view(template_name='dms/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('', include('dms.urls')),
]
