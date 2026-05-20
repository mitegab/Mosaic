import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.db import connections

@pytest.mark.django_db
def test_connect_db_endpoint_valid_sqlite():
    client = APIClient()
    url = reverse('connect_db')
    
    # SQLite in-memory should be trivially connectable
    payload = {"url": "sqlite:///:memory:"}
    response = client.post(url, payload, format='json')
    
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "connected"}

@pytest.mark.django_db
def test_connect_db_endpoint_invalid_url():
    client = APIClient()
    url = reverse('connect_db')
    
    payload = {"url": "invalid-url://localhost"}
    response = client.post(url, payload, format='json')
    
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "error" in response.json()

@pytest.mark.django_db
def test_models_list_with_dynamic_sqlite_connection():
    client = APIClient()
    url = reverse('models_list')
    
    # Pass an empty in-memory SQLite database connection URL in the header
    headers = {"HTTP_X_DATABASE_URL": "sqlite:///:memory:"}
    response = client.get(url, **headers)
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    
    # Under test execution, dynamic urls redirect to default (the PostgreSQL test db)
    # So we expect it to return the test database tables/models successfully
    assert isinstance(data, list)
    assert len(data) > 0
