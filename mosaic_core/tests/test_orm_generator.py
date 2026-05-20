import pytest
from mosaic_core.schemas import QueryDsl
from mosaic_core.orm_generator import OrmGenerator


def test_django_orm_basic():
    dsl = QueryDsl.model_validate({
        "model": "User",
        "output": ["id", "email"],
        "filters": [
            {"field": "is_active", "operator": "exact", "value": True}
        ],
        "limit": 10,
        "offset": 5
    })
    gen = OrmGenerator()
    result = gen.generate_django_orm(dsl)

    assert "User.objects" in result
    assert "filter(" in result
    assert "is_active=True" in result
    assert "values('id', 'email')" in result
    assert "[5:15]" in result


def test_django_orm_with_relations():
    dsl = QueryDsl.model_validate({
        "model": "BlogPost",
        "output": ["title"],
        "relations": [
            {"relation": "author"}
        ]
    })
    gen = OrmGenerator()
    result = gen.generate_django_orm(dsl)
    assert "select_related('author')" in result


def test_sqlalchemy_basic():
    dsl = QueryDsl.model_validate({
        "model": "User",
        "output": ["id", "email"],
        "filters": [
            {"field": "id", "operator": "gt", "value": 5}
        ],
        "orderBy": ["-email"],
        "limit": 10
    })
    gen = OrmGenerator()
    result = gen.generate_sqlalchemy(dsl)

    assert "select(User.id, User.email)" in result
    assert "User.id > 5" in result
    assert "User.email.desc()" in result
    assert ".limit(10)" in result


def test_prisma_basic():
    dsl = QueryDsl.model_validate({
        "model": "User",
        "output": ["id", "email"],
        "filters": [
            {"field": "is_active", "operator": "exact", "value": True}
        ],
        "limit": 10
    })
    gen = OrmGenerator()
    result = gen.generate_prisma(dsl)

    assert "prisma.user.findMany(" in result
    assert "is_active: True" in result or "is_active: true" in result
    assert "take: 10" in result


def test_prisma_with_relations():
    dsl = QueryDsl.model_validate({
        "model": "BlogPost",
        "output": ["title"],
        "relations": [
            {"relation": "author", "select": ["email"]}
        ]
    })
    gen = OrmGenerator()
    result = gen.generate_prisma(dsl)
    assert "prisma.blogPost.findMany(" in result
    # author should appear in the select block
    assert "author" in result
