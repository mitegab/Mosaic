import pytest
from rest_framework import status
from django.urls import reverse
from rest_framework.test import APIClient

@pytest.mark.django_db
def test_health_check_endpoint():
    client = APIClient()
    url = reverse('health_check')
    
    response = client.get(url)
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    
    assert data['status'] == 'healthy'
    assert 'timestamp' in data
    assert data['dbConnected'] is True
