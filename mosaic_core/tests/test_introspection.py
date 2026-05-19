import pytest
from mosaic_core.introspection import PostgresIntrospector

@pytest.mark.django_db
def test_introspector_get_tables_and_views():
    introspector = PostgresIntrospector()
    try:
        tables = introspector.get_tables()
        assert "auth_users" in tables
        assert "blog_posts" in tables
        assert "user_profiles" in tables
        assert "post_comments" in tables
        
        views = introspector.get_views()
        assert isinstance(views, list)
    finally:
        introspector.close()

@pytest.mark.django_db
def test_introspector_get_columns():
    introspector = PostgresIntrospector()
    try:
        columns = introspector.get_columns("auth_users")
        # should have id, email, username, is_active, created_at
        col_names = [c["name"] for c in columns]
        assert "id" in col_names
        assert "email" in col_names
        assert "username" in col_names
        assert "is_active" in col_names
        assert "created_at" in col_names
        
        # Check id is primary_key
        id_col = next(c for c in columns if c["name"] == "id")
        assert id_col["primary_key"] is True
        assert id_col["nullable"] is False
        
        # Check email is not primary_key
        email_col = next(c for c in columns if c["name"] == "email")
        assert email_col["primary_key"] is False
        assert email_col["kind"] == "string"
        
        # Check active status is boolean
        active_col = next(c for c in columns if c["name"] == "is_active")
        assert active_col["kind"] == "boolean"
    finally:
        introspector.close()

@pytest.mark.django_db
def test_introspector_normalize_type():
    introspector = PostgresIntrospector()
    try:
        assert introspector.normalize_type("integer") == "number"
        assert introspector.normalize_type("bigint") == "number"
        assert introspector.normalize_type("character varying") == "string"
        assert introspector.normalize_type("varchar(100)") == "string"
        assert introspector.normalize_type("boolean") == "boolean"
        assert introspector.normalize_type("timestamp with time zone") == "datetime"
        assert introspector.normalize_type("jsonb") == "json"
        assert introspector.normalize_type("unknown_type") == "unknown"
    finally:
        introspector.close()
