import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from mosaic_core.ai import AiAssistantEngine
from mosaic_core.schemas import QueryDsl, QueryFilter, QueryRelation

@pytest.mark.django_db
def test_ai_engine_suggest_indexes():
    engine = AiAssistantEngine()
    
    # 1. Test query with non-indexed filter
    dsl = QueryDsl(
        model="BlogPost",
        select=["id", "title"],
        filters=[
            QueryFilter(field="title", operator="icontains", value="django", logic="AND"),
            QueryFilter(field="status", operator="exact", value="published", logic="AND")
        ]
    )
    res = engine.suggest_indexes(dsl)
    
    # Verify suggestions are returned
    assert res.suggestedIndexes is not None
    assert len(res.suggestedIndexes) > 0
    # Title icontains should recommend a GIN trigram index
    assert any("gin" in sql.lower() and "title" in sql.lower() for sql in res.suggestedIndexes)
    # BlogPost.status is already indexed (see metadata in models.py), so it should not recommend an index
    assert not any("blog_posts" in sql.lower() and "status" in sql.lower() for sql in res.suggestedIndexes)


@pytest.mark.django_db
def test_ai_engine_optimize():
    engine = AiAssistantEngine()
    
    # 1. Test missing limit and explicit projection optimization
    dsl = QueryDsl(model="User")
    res = engine.optimize(dsl)
    
    assert res.dsl is not None
    assert res.dsl.limit == 100
    assert res.dsl.select is not None
    assert "username" in res.dsl.select
    assert "email" in res.dsl.select


@pytest.mark.django_db
def test_ai_engine_fix():
    engine = AiAssistantEngine()
    
    # 1. Test fixing model name typo and field typo
    dsl = QueryDsl(
        model="usr", # misspelled User
        select=["usrname", "email", "invalid_field"], # misspelled username, correct email, invalid field
        filters=[
            QueryFilter(field="is_active", operator="exact", value=True)
        ]
    )
    res = engine.fix(dsl, "")
    
    assert res.dsl is not None
    assert res.dsl.model == "User"
    assert "username" in res.dsl.select
    assert "invalid_field" not in res.dsl.select
    assert res.dsl.limit == 10  # default limit applied


@pytest.mark.django_db
def test_ai_engine_sql_to_dsl():
    engine = AiAssistantEngine()
    
    sql = "SELECT id, title FROM blog_posts WHERE status = 'published' ORDER BY published_at DESC LIMIT 5"
    res = engine.sql_to_dsl(sql)
    
    assert res.dsl is not None
    assert res.dsl.model == "BlogPost"
    assert "title" in res.dsl.select
    assert len(res.dsl.filters) == 1
    assert res.dsl.filters[0].field == "status"
    assert res.dsl.filters[0].value == "published"
    assert res.dsl.orderBy == ["-published_at"]
    assert res.dsl.limit == 5


@pytest.mark.django_db
def test_ai_engine_generate():
    engine = AiAssistantEngine()
    
    # Generate for blog posts with text matching
    res = engine.generate("find draft blog posts about 'react' published after 2024")
    
    assert res.dsl is not None
    assert res.dsl.model == "BlogPost"
    
    # Verify filters
    fields = [f.field for f in res.dsl.filters]
    assert "status" in fields
    assert "title" in fields
    assert "published_at" in fields


@pytest.mark.django_db
def test_ai_assistant_api_endpoint():
    client = APIClient()
    url = reverse('ai_assistant')
    
    # Test valid API request
    payload = {
        "mode": "generate",
        "prompt": "active users registered after 2023",
        "currentDsl": None
    }
    
    response = client.post(url, payload, format='json')
    assert response.status_code == status.HTTP_200_OK
    
    data = response.json()
    assert "explanation" in data
    assert "dsl" in data
    assert data["dsl"] is not None
    assert data["dsl"]["model"] == "User"
