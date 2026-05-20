import pytest
from mosaic_core.schemas import QueryDsl
from mosaic_core.compiler import QueryCompiler

@pytest.mark.django_db
def test_compile_basic_query():
    compiler = QueryCompiler()
    
    # 1. Simple query with select, limit, offset
    dsl = QueryDsl.model_validate({
        "model": "User",
        "select": ["id", "email"],
        "limit": 10,
        "offset": 5
    })
    
    sql, params, logs = compiler.compile(dsl)
    
    assert "SELECT auth_users.id AS \"id\", auth_users.email AS \"email\" FROM auth_users" in sql
    assert "LIMIT 10" in sql
    assert "OFFSET 5" in sql
    assert len(params) == 0

@pytest.mark.django_db
def test_compile_with_filters():
    compiler = QueryCompiler()
    
    # Query with diverse operators
    dsl = QueryDsl.model_validate({
        "model": "User",
        "output": ["email"],
        "filters": [
            {"field": "email", "operator": "icontains", "value": "test@example.com"},
            {"field": "is_active", "operator": "exact", "value": True},
            {"field": "id", "operator": "gt", "value": 5}
        ]
    })
    
    sql, params, logs = compiler.compile(dsl)
    
    assert "auth_users.email ILIKE %s" in sql
    assert "auth_users.is_active = %s" in sql
    assert "auth_users.id > %s" in sql
    assert params == ["%test@example.com%", True, 5]

@pytest.mark.django_db
def test_compile_consecutive_or_filters():
    compiler = QueryCompiler()
    
    # Test flat consecutive OR rules matching frontend grouping logic
    dsl = QueryDsl.model_validate({
        "model": "User",
        "output": ["id"],
        "filters": [
            {"field": "username", "operator": "exact", "value": "alice", "logic": "OR"},
            {"field": "username", "operator": "exact", "value": "bob", "logic": "OR"},
            {"field": "username", "operator": "exact", "value": "charlie"}
        ]
    })
    
    sql, params, logs = compiler.compile(dsl)
    
    # Consecutive ORs should group into (A OR B OR C)
    assert "(auth_users.username = %s OR auth_users.username = %s OR auth_users.username = %s)" in sql
    assert params == ["alice", "bob", "charlie"]
    
    # Mix of AND and OR
    dsl_mixed = QueryDsl.model_validate({
        "model": "User",
        "output": ["id"],
        "filters": [
            {"field": "is_active", "operator": "exact", "value": True},
            {"field": "username", "operator": "exact", "value": "alice", "logic": "OR"},
            {"field": "username", "operator": "exact", "value": "bob"}
        ]
    })
    sql_mixed, params_mixed, _ = compiler.compile(dsl_mixed)
    # Consecutive grouping evaluates to: (is_active OR alice OR bob) matching JS logic
    assert "(auth_users.is_active = %s OR auth_users.username = %s OR auth_users.username = %s)" in sql_mixed
    assert params_mixed == [True, "alice", "bob"]

@pytest.mark.django_db
def test_compile_relations_joins():
    compiler = QueryCompiler()
    
    # Join BlogPost -> User, select nested columns
    dsl = QueryDsl.model_validate({
        "model": "BlogPost",
        "select": ["id", "title"],
        "relations": [
            {
                "relation": "author",
                "select": ["email", "username"]
            }
        ]
    })
    
    sql, params, logs = compiler.compile(dsl)
    
    assert "SELECT blog_posts.id AS \"id\", blog_posts.title AS \"title\", auth_users.email AS \"author__email\", auth_users.username AS \"author__username\" FROM blog_posts" in sql
    assert "LEFT JOIN auth_users ON auth_users.id = blog_posts.author_id" in sql

@pytest.mark.django_db
def test_compile_reverse_relations_joins():
    compiler = QueryCompiler()
    
    # Reverse join User -> BlogPost (posts)
    dsl = QueryDsl.model_validate({
        "model": "User",
        "select": ["id", "username"],
        "relations": [
            {
                "relation": "posts",
                "select": ["title"]
            }
        ]
    })
    
    sql, params, logs = compiler.compile(dsl)
    
    assert "SELECT auth_users.id AS \"id\", auth_users.username AS \"username\", blog_posts.title AS \"posts__title\" FROM auth_users" in sql
    assert "LEFT JOIN blog_posts ON blog_posts.author_id = auth_users.id" in sql

@pytest.mark.django_db
def test_compile_with_order_by():
    compiler = QueryCompiler()
    
    dsl = QueryDsl.model_validate({
        "model": "User",
        "select": ["id"],
        "orderBy": ["-created_at", "id"]
    })
    
    sql, params, logs = compiler.compile(dsl)
    
    assert "ORDER BY auth_users.created_at DESC, auth_users.id ASC" in sql
