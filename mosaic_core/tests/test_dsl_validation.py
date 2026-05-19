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


@pytest.mark.django_db
def test_dsl_validator_field_existence():
    from mosaic_core.validator import DslValidator
    validator = DslValidator()
    
    # Valid fields in select and filters
    dsl = QueryDsl.model_validate({
        "model": "User",
        "select": ["id", "email"],
        "filters": [{"field": "email", "operator": "exact", "value": "test@example.com"}],
        "limit": 10
    })
    res = validator.validate(dsl)
    assert res["valid"] is True
    assert len(res["errors"]) == 0
    
    # Invalid select field
    dsl_invalid_select = QueryDsl.model_validate({
        "model": "User",
        "select": ["id", "non_existent_field"],
        "limit": 10
    })
    res_invalid_select = validator.validate(dsl_invalid_select)
    assert res_invalid_select["valid"] is False
    assert any("does not exist on model 'User'" in e for e in res_invalid_select["errors"])
    
    # Invalid filter field
    dsl_invalid_filter = QueryDsl.model_validate({
        "model": "User",
        "filters": [{"field": "invalid_filter_col", "operator": "exact", "value": "val"}],
        "limit": 10
    })
    res_invalid_filter = validator.validate(dsl_invalid_filter)
    assert res_invalid_filter["valid"] is False
    assert any("does not exist on model 'User'" in e for e in res_invalid_filter["errors"])


@pytest.mark.django_db
def test_dsl_validator_operators():
    from mosaic_core.validator import DslValidator
    validator = DslValidator()

    # Valid operator 'icontains' on string field 'email'
    dsl_valid = QueryDsl.model_validate({
        "model": "User",
        "filters": [{"field": "email", "operator": "icontains", "value": "gmail.com"}],
        "limit": 10
    })
    res_valid = validator.validate(dsl_valid)
    assert res_valid["valid"] is True

    # Invalid operator 'gt' on boolean field 'is_active'
    dsl_invalid = QueryDsl.model_validate({
        "model": "User",
        "filters": [{"field": "is_active", "operator": "gt", "value": True}],
        "limit": 10
    })
    res_invalid = validator.validate(dsl_invalid)
    assert res_invalid["valid"] is False
    assert any("Operator 'gt' is not compatible with field 'is_active' of kind 'boolean'" in e for e in res_invalid["errors"])


@pytest.mark.django_db
def test_dsl_validator_relations():
    from mosaic_core.validator import DslValidator
    validator = DslValidator()

    # Valid relation path: User has posts
    dsl_valid = QueryDsl.model_validate({
        "model": "User",
        "relations": [
            {
                "relation": "posts",
                "select": ["id", "title"],
                "filters": [{"field": "status", "operator": "exact", "value": "published"}]
            }
        ],
        "limit": 10
    })
    res_valid = validator.validate(dsl_valid)
    assert res_valid["valid"] is True
    assert len(res_valid["errors"]) == 0

    # Invalid relation: User has no 'non_existent_relation'
    dsl_invalid_rel = QueryDsl.model_validate({
        "model": "User",
        "relations": [
            {
                "relation": "non_existent_relation",
                "select": ["id"]
            }
        ],
        "limit": 10
    })
    res_invalid_rel = validator.validate(dsl_invalid_rel)
    assert res_invalid_rel["valid"] is False
    assert any("Relation 'non_existent_relation' does not exist on model 'User'" in e for e in res_invalid_rel["errors"])

    # Invalid fields inside related model select list
    dsl_invalid_fields = QueryDsl.model_validate({
        "model": "User",
        "relations": [
            {
                "relation": "posts",
                "select": ["id", "non_existent_post_col"]
            }
        ],
        "limit": 10
    })
    res_invalid_fields = validator.validate(dsl_invalid_fields)
    assert res_invalid_fields["valid"] is False
    assert any("Field 'non_existent_post_col' does not exist on model 'BlogPost'" in e for e in res_invalid_fields["errors"])




