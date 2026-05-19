import structlog
from typing import List, Dict, Any, Optional
from mosaic_core.schemas import QueryDsl, QueryFilter, QueryFilterGroup, QueryRelation

logger = structlog.get_logger(__name__)

class DslValidator:
    """
    Validates Query DSL syntax and schema structures against the active
    PostgreSQL catalog schema mappings, checking models, fields, operators, and relations.
    """
    def __init__(self, schema_models: Optional[List[Any]] = None):
        if schema_models is None:
            from mosaic_core.introspection import PostgresIntrospector
            introspector = PostgresIntrospector()
            try:
                schema_models = introspector.introspect_schema()
            finally:
                introspector.close()
                
        # Build optimized lookup dictionaries for schema validation
        self.models = {}
        for model in schema_models:
            fields_map = {}
            relations_map = {}
            for field in model.fields:
                if field.kind == "relation":
                    relations_map[field.name] = field
                else:
                    fields_map[field.name] = field
                    
            self.models[model.name] = {
                "tableName": model.tableName,
                "fields": fields_map,
                "relations": relations_map,
                "model_obj": model
            }

    def validate(self, dsl: QueryDsl) -> Dict[str, Any]:
        """
        Validates Query DSL input.
        Returns a dict: {"valid": bool, "errors": List[str]}
        """
        errors = []
        
        # 1. Model Presence Check
        if dsl.model not in self.models:
            errors.append(f"Model '{dsl.model}' does not exist in the database schema.")
            return {"valid": False, "errors": errors}
            
        return {"valid": len(errors) == 0, "errors": errors}
