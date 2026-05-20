from django.urls import path
from mosaic_core import views

urlpatterns = [
    path('health/', views.health_check, name='health_check'),
    path('models/', views.models_list, name='models_list'),
    path('validate-query/', views.validate_query, name='validate_query'),
]

