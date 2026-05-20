import pytest
from rest_framework.test import APIClient
from rest_framework import status


@pytest.mark.django_db
def test_execute_query_basic():
    """POST /api/query/ with a simple DSL returns rows, metrics, orm, logs, executionPlan."""
    client = APIClient()
    payload = {
        "model": "User",
        "output": ["id", "email", "username"],
        "limit": 5
    }
    response = client.post('/api/query/', payload, format='json')
    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    # Shape matches QueryExecutionResponse
    assert "rows" in data
    assert isinstance(data["rows"], list)

    assert "metrics" in data
    metrics = data["metrics"]
    assert "executionTimeMs" in metrics
    assert "rowsReturned" in metrics
    assert "backendLatencyMs" in metrics
    assert metrics["rowsReturned"] == len(data["rows"])

    assert "orm" in data
    assert isinstance(data["orm"], str)
    assert "Django ORM" in data["orm"]
    assert "SQLAlchemy" in data["orm"]
    assert "Prisma" in data["orm"]

    assert "logs" in data
    assert isinstance(data["logs"], list)
    assert len(data["logs"]) > 0

    assert "executionPlan" in data


@pytest.mark.django_db
def test_execute_query_with_filters():
    """POST /api/query/ with filters returns filtered rows."""
    client = APIClient()
    payload = {
        "model": "User",
        "output": ["id", "email"],
        "filters": [
            {"field": "is_active", "operator": "exact", "value": True}
        ],
        "limit": 10
    }
    response = client.post('/api/query/', payload, format='json')
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data["rows"], list)
    assert data["metrics"]["rowsReturned"] == len(data["rows"])


@pytest.mark.django_db
def test_execute_query_with_relations():
    """POST /api/query/ with a relation join returns joined columns."""
    client = APIClient()
    payload = {
        "model": "BlogPost",
        "output": ["id", "title"],
        "relations": [
            {"relation": "author", "select": ["username"]}
        ],
        "limit": 5
    }
    response = client.post('/api/query/', payload, format='json')
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    # Rows should contain author__username column
    if len(data["rows"]) > 0:
        assert "author__username" in data["rows"][0]


@pytest.mark.django_db
def test_execute_query_invalid_dsl():
    """POST /api/query/ with invalid DSL returns graceful error response, not 500."""
    client = APIClient()
    payload = {"not_a_model": "bad"}
    response = client.post('/api/query/', payload, format='json')
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["rows"] == []
    assert len(data["logs"]) > 0


@pytest.mark.django_db
def test_execute_query_invalid_model():
    """POST /api/query/ with a nonexistent model returns error in logs."""
    client = APIClient()
    payload = {
        "model": "NonExistentModel",
        "output": ["id"],
        "limit": 5
    }
    response = client.post('/api/query/', payload, format='json')
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["rows"] == []
    assert any("error" in log.lower() or "NonExistentModel" in log for log in data["logs"])
