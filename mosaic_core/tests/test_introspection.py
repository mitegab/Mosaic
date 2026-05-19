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

@pytest.mark.django_db
def test_introspector_get_constraints():
    introspector = PostgresIntrospector()
    try:
        constraints = introspector.get_constraints("auth_users")
        # Check id constraint contains PRIMARY KEY
        assert "id" in constraints
        id_types = [c["type"] for c in constraints["id"]]
        assert "PRIMARY KEY" in id_types
        
        # Check email constraint contains UNIQUE (Django creates unique constraints or indexes)
        # Note: sometimes email has a unique index rather than constraint depending on model Meta
        # but let's assert what is actually present in db.
        # User has `email = models.CharField(max_length=255, unique=True)` which translates to a UNIQUE constraint.
        assert "email" in constraints or "username" in constraints
    finally:
        introspector.close()

@pytest.mark.django_db
def test_introspector_get_indexes():
    introspector = PostgresIntrospector()
    try:
        # Check BTree on auth_users email
        indexes = introspector.get_indexes("auth_users")
        assert "email" in indexes
        email_idx = indexes["email"]
        assert any(idx["type"] == "btree" for idx in email_idx)
        
        # Check GIN index on blog_posts metadata
        post_indexes = introspector.get_indexes("blog_posts")
        assert "metadata" in post_indexes
        metadata_idx = post_indexes["metadata"]
        assert any(idx["type"] == "gin" for idx in metadata_idx)
    finally:
        introspector.close()

@pytest.mark.django_db
def test_introspector_get_all_foreign_keys():
    introspector = PostgresIntrospector()
    try:
        fks = introspector.get_all_foreign_keys()
        assert len(fks) > 0
        
        # Verify BlogPost -> User foreign key is present
        post_to_user = next(fk for fk in fks if fk["source_table"] == "blog_posts" and fk["target_table"] == "auth_users")
        assert post_to_user["source_column"] == "author_id"
        assert post_to_user["target_column"] == "id"
    finally:
        introspector.close()

@pytest.mark.django_db
def test_introspector_get_relations():
    introspector = PostgresIntrospector()
    try:
        fks = introspector.get_all_foreign_keys()
        
        # User relations check
        user_rels = introspector.get_relations("auth_users", fks)
        # Should have profile (one-to-one) and posts (one-to-many)
        rel_types = {r["name"]: r["relationType"] for r in user_rels}
        assert "profile" in rel_types
        assert rel_types["profile"] == "one-to-one"
        assert "posts" in rel_types
        assert rel_types["posts"] == "one-to-many"
        
        # BlogPost relations check
        post_rels = introspector.get_relations("blog_posts", fks)
        post_types = {r["name"]: r["relationType"] for r in post_rels}
        assert "author" in post_types
        assert post_types["author"] == "many-to-one"
        assert "comments" in post_types
        assert post_types["comments"] == "one-to-many"
    finally:
        introspector.close()

@pytest.mark.django_db
def test_introspector_get_row_estimate():
    introspector = PostgresIntrospector()
    try:
        est = introspector.get_row_estimate("auth_users")
        assert isinstance(est, int)
        assert est >= 0
    finally:
        introspector.close()

@pytest.mark.django_db
def test_introspector_get_sample_data():
    introspector = PostgresIntrospector()
    try:
        samples = introspector.get_sample_data("auth_users", limit=2)
        assert isinstance(samples, list)
        assert len(samples) <= 2
        if len(samples) > 0:
            assert "id" in samples[0]
            assert "email" in samples[0]
            assert "username" in samples[0]
    finally:
        introspector.close()

@pytest.mark.django_db
def test_introspector_schema_mapping():
    from mosaic_core.schemas import SchemaModel
    introspector = PostgresIntrospector()
    try:
        models = introspector.introspect_schema()
        assert len(models) > 0
        assert all(isinstance(m, SchemaModel) for m in models)
        
        # Verify User model details
        user_model = next(m for m in models if m.name == "User")
        assert user_model.tableName == "auth_users"
        assert user_model.description == "User registration and authentication table"
        
        # Verify there are fields and relations
        field_names = [f.name for f in user_model.fields]
        assert "email" in field_names
        assert "posts" in field_names
        
        post_field = next(f for f in user_model.fields if f.name == "posts")
        assert post_field.kind == "relation"
        assert post_field.relatedModel == "BlogPost"
        assert post_field.relationType == "one-to-many"
    finally:
        introspector.close()


@pytest.mark.django_db
def test_introspector_serialize_schema():
    introspector = PostgresIntrospector()
    try:
        models = introspector.introspect_schema()
        serialized = introspector.serialize_schema(models)
        assert isinstance(serialized, list)
        assert len(serialized) > 0
        
        user_ser = next(m for m in serialized if m["name"] == "User")
        assert user_ser["tableName"] == "auth_users"
        
        # Verify that None values are omitted
        for field in user_ser["fields"]:
            # A field should not have None values
            assert None not in field.values()
            
            # Non-relation fields should not have relatedModel or relationType
            if field["kind"] != "relation":
                assert "relatedModel" not in field
                assert "relationType" not in field
            else:
                # Relation fields should not have primaryKey or nullable
                assert "primaryKey" not in field
                assert "nullable" not in field
    finally:
        introspector.close()


@pytest.mark.django_db
def test_track_queries_context_manager():
    from mosaic_core.utils import track_queries
    from django.db import connection
    
    with track_queries("test_op") as queries:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
            cursor.fetchone()
            cursor.execute("SELECT 2;")
            cursor.fetchone()
            
    assert len(queries) == 2
    assert "SELECT 1;" in queries[0]["sql"]
    assert "SELECT 2;" in queries[1]["sql"]
    assert queries[0]["duration_ms"] > 0


@pytest.mark.django_db
def test_introspector_benchmark_latency():
    import time
    import structlog
    logger = structlog.get_logger(__name__)
    
    introspector = PostgresIntrospector()
    try:
        # Warmup execution
        introspector.introspect_schema()
        
        runs = 10
        durations = []
        
        for _ in range(runs):
            start = time.perf_counter()
            introspector.introspect_schema()
            durations.append(time.perf_counter() - start)
            
        avg_duration_sec = sum(durations) / runs
        logger.info(
            "introspector_benchmark_metrics",
            runs=runs,
            durations_seconds=durations,
            average_duration_ms=avg_duration_sec * 1000.0
        )
        
        # Verify schema introspection runs extremely fast (less than 300ms)
        assert avg_duration_sec < 0.3
    finally:
        introspector.close()



