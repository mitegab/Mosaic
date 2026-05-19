import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

@pytest.mark.django_db
def test_models_list_endpoint():
    client = APIClient()
    url = reverse('models_list')
    
    response = client.get(url)
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    
    # We expect a list of SchemaModels
    assert isinstance(data, list)
    assert len(data) > 0
    
    # Check thatauth_users is present as User
    user_model = next((m for m in data if m["name"] == "User"), None)
    assert user_model is not None
    assert user_model["tableName"] == "auth_users"
    assert "description" in user_model
    assert "rowEstimate" in user_model
    assert "fields" in user_model
    
    # Verify that fields have expected keys and no None values
    fields = user_model["fields"]
    email_field = next((f for f in fields if f["name"] == "email"), None)
    assert email_field is not None
    assert email_field["kind"] == "string"
    assert email_field["type"] == "character varying"
    assert email_field["primaryKey"] is False
    assert email_field["nullable"] is False
    
    # Verify relations
    posts_field = next((f for f in fields if f["name"] == "posts"), None)
    assert posts_field is not None
    assert posts_field["kind"] == "relation"
    assert posts_field["type"] == "relation"
    assert posts_field["relatedModel"] == "BlogPost"
    assert posts_field["relationType"] == "one-to-many"
