from django.urls import path
from . import views

app_name = 'dms'

urlpatterns = [
    path('', views.index, name='index'),
    path('upload/', views.upload_page, name='upload_page'),
    path('upload/file/', views.upload_file, name='upload_file'),
    path('documents/', views.document_list, name='document_list'),
    path('documents/<uuid:pk>/', views.document_detail, name='document_detail'),
    path('documents/<uuid:pk>/download/', views.document_download, name='document_download'),
    path('tasks/', views.task_list, name='task_list'),
    path('tasks/<uuid:pk>/complete/', views.task_complete, name='task_complete'),
]
