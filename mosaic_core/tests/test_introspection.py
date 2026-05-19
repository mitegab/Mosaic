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
