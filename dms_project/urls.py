from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from mfa.views import LoginView as MFALoginView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('mfa/', include('mfa.urls', namespace='mfa')),
    path('login/', MFALoginView.as_view(template_name='dms/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('', include('dms.urls')),
]
