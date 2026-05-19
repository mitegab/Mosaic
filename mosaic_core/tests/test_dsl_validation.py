import pytest
from pydantic import ValidationError
from mosaic_core.schemas import QueryDsl, QueryFilter, QueryFilterGroup, QueryRelation

def test_pydantic_simple_dsl_deserialization():
    payload = {
        "model": "User",
        "select": ["id", "email"],
        "limit": 10,
        "offset": 0
    }
    
    dsl = QueryDsl.model_validate(payload)
    assert dsl.model == "User"
    assert dsl.select == ["id", "email"]
    assert dsl.limit == 10
    assert dsl.offset == 0

def test_pydantic_nested_logical_filters():
    payload = {
        "model": "BlogPost",
        "filters": [
            {
                "logic": "or",
                "filters": [
                    {"field": "status", "operator": "exact", "value": "published"},
                    {"field": "is_featured", "operator": "exact", "value": True}
                ]
            },
            {"field": "created_at", "operator": "gt", "value": "2026-01-01"}
        ]
    }
    
    dsl = QueryDsl.model_validate(payload)
    assert len(dsl.filters) == 2
    
    # Verify first filter is a QueryFilterGroup with logic 'or'
    group = dsl.filters[0]
    assert isinstance(group, QueryFilterGroup)
    assert group.logic == "or"
    assert len(group.filters) == 2
    assert group.filters[0].field == "status"
    assert group.filters[1].value is True
    
    # Verify second filter is a standard QueryFilter
    second_filter = dsl.filters[1]
    assert isinstance(second_filter, QueryFilter)
    assert second_filter.field == "created_at"
    assert second_filter.operator == "gt"

def test_pydantic_recursive_relations():
    payload = {
        "model": "User",
        "relations": [
            {
                "relation": "posts",
                "select": ["id", "title"],
                "relations": [
                    {
                        "relation": "comments",
                        "select": ["body", "rating"]
                    }
                ]
            }
        ]
    }
    
    dsl = QueryDsl.model_validate(payload)
    assert len(dsl.relations) == 1
    
    post_rel = dsl.relations[0]
    assert isinstance(post_rel, QueryRelation)
    assert post_rel.relation == "posts"
    assert post_rel.select == ["id", "title"]
    assert len(post_rel.relations) == 1
    
    comment_rel = post_rel.relations[0]
    assert comment_rel.relation == "comments"
    assert comment_rel.select == ["body", "rating"]

def test_pydantic_validation_failures():
    # Limit too large (> 1000)
    with pytest.raises(ValidationError) as exc:
        QueryDsl.model_validate({"model": "User", "limit": 1001})
    assert "limit" in str(exc.value)

    # Limit less than 1
    with pytest.raises(ValidationError) as exc:
        QueryDsl.model_validate({"model": "User", "limit": 0})
    assert "limit" in str(exc.value)

    # Offset negative
    with pytest.raises(ValidationError) as exc:
        QueryDsl.model_validate({"model": "User", "offset": -1})
    assert "offset" in str(exc.value)


@pytest.mark.django_db
def test_dsl_validator_model_presence():
    from mosaic_core.validator import DslValidator
    
    # Initialize validator dynamically (loads live Postgres schema)
    validator = DslValidator()
    
    # Valid model User
    dsl_valid = QueryDsl.model_validate({"model": "User"})
    res_valid = validator.validate(dsl_valid)
    assert res_valid["valid"] is True
    assert len(res_valid["errors"]) == 0
    
    # Invalid model NonExistent
    dsl_invalid = QueryDsl.model_validate({"model": "NonExistent"})
    res_invalid = validator.validate(dsl_invalid)
    assert res_invalid["valid"] is False
    assert len(res_invalid["errors"]) == 1
    assert "Model 'NonExistent' does not exist" in res_invalid["errors"][0]

