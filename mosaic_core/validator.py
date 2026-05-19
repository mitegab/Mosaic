import structlog
from typing import List, Dict, Any, Optional, Union
from mosaic_core.schemas import QueryDsl, QueryFilter, QueryFilterGroup, QueryRelation

logger = structlog.get_logger(__name__)

VALID_OPERATORS_BY_KIND = {
    'string': {'exact', 'icontains', 'contains', 'startswith', 'endswith', 'in', 'isnull'},
    'number': {'exact', 'gt', 'gte', 'lt', 'lte', 'in', 'isnull'},
    'boolean': {'exact', 'isnull'},
    'date': {'exact', 'gt', 'gte', 'lt', 'lte', 'in', 'isnull'},
    'datetime': {'exact', 'gt', 'gte', 'lt', 'lte', 'in', 'isnull'},
    'json': {'exact', 'isnull', 'contains'},
    'unknown': {'exact', 'isnull', 'in'},
}

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
                "model_obj": model,
                "indexed_fields": set()
            }

        # Build indexes lookup dynamically from database to provide performance warnings
        from django.db import connection
        try:
            with connection.cursor() as cursor:
                for model_name, info in self.models.items():
                    table_name = info["tableName"]
                    # Query indexes from pg catalog
                    query = """
                        SELECT DISTINCT
                            a.attname AS column_name
                        FROM
                            pg_class t
                        JOIN
                            pg_index ix ON t.oid = ix.indrelid
                        JOIN
                            pg_class i ON i.oid = ix.indexrelid
                        JOIN
                            pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
                        WHERE
                            t.relkind = 'r'
                            AND t.relname = %s;
                    """
                    cursor.execute(query, [table_name])
                    indexed_cols = {row[0] for row in cursor.fetchall()}
                    info["indexed_fields"] = indexed_cols
        except Exception as e:
            logger.warning("failed_to_load_indexes_for_validation", error=str(e))

    def validate(self, dsl: QueryDsl) -> Dict[str, Any]:
        """
        Validates Query DSL input.
        Returns a dict: {"valid": bool, "errors": List[str], "warnings": List[str]}
        """
        errors = []
        warnings = []
        
        # 1. Model Presence Check
        if dsl.model not in self.models:
            errors.append(f"Model '{dsl.model}' does not exist in the database schema.")
            return {"valid": False, "errors": errors, "warnings": warnings}
            
        # 2. Check for missing limit warning at root
        if dsl.limit is None:
            warnings.append("No 'limit' was specified. This query might retrieve a large number of rows, impacting performance.")
            
        # 3. Recursively validate select fields, filters, and relations
        self._validate_model_fields(
            dsl.model,
            select=dsl.select,
            filters=dsl.filters,
            relations=dsl.relations,
            errors=errors,
            warnings=warnings
        )
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }

    def _validate_model_fields(
        self,
        model_name: str,
        select: Optional[List[str]],
        filters: Optional[List[Union[QueryFilter, QueryFilterGroup]]],
        relations: Optional[List[QueryRelation]],
        errors: List[str],
        warnings: List[str]
    ):
        model_info = self.models[model_name]
        fields_map = model_info["fields"]
        relations_map = model_info["relations"]
        indexed_fields = model_info["indexed_fields"]

        # Validate select fields
        if select:
            for field_name in select:
                if field_name in relations_map:
                    errors.append(f"Field '{field_name}' on model '{model_name}' is a relation and cannot be selected directly. Use the 'relations' array to select relation fields.")
                elif field_name not in fields_map:
                    errors.append(f"Field '{field_name}' does not exist on model '{model_name}'.")

        # Validate filters recursively
        if filters:
            self._validate_filters(model_name, filters, errors, warnings)

        # Validate relations recursively
        if relations:
            for rel in relations:
                rel_name = rel.relation
                if rel_name not in relations_map:
                    errors.append(f"Relation '{rel_name}' does not exist on model '{model_name}'.")
                else:
                    rel_field = relations_map[rel_name]
                    related_model = rel_field.relatedModel
                    if not related_model:
                        errors.append(f"Relation '{rel_name}' on model '{model_name}' has no target model.")
                    elif related_model not in self.models:
                        errors.append(f"Related model '{related_model}' for relation '{rel_name}' on model '{model_name}' does not exist in schema.")
                    else:
                        # Recursively validate under related model
                        self._validate_model_fields(
                            related_model,
                            select=rel.select,
                            filters=rel.filters,
                            relations=rel.relations,
                            errors=errors,
                            warnings=warnings
                        )

    def _validate_filters(
        self,
        model_name: str,
        filters: List[Union[QueryFilter, QueryFilterGroup]],
        errors: List[str],
        warnings: List[str]
    ):
        model_info = self.models[model_name]
        fields_map = model_info["fields"]
        relations_map = model_info["relations"]
        indexed_fields = model_info["indexed_fields"]

        for filter_item in filters:
            if hasattr(filter_item, "logic"):  # QueryFilterGroup
                self._validate_filters(model_name, filter_item.filters, errors, warnings)
            else:  # QueryFilter
                field_name = filter_item.field
                if field_name in relations_map:
                    errors.append(f"Field '{field_name}' on model '{model_name}' is a relation and cannot be used directly in filters. Use the 'relations' array to filter related models.")
                elif field_name not in fields_map:
                    errors.append(f"Field '{field_name}' does not exist on model '{model_name}'.")
                else:
                    field_obj = fields_map[field_name]
                    op = filter_item.operator
                    kind = field_obj.kind
                    
                    # Validate operator compatibility
                    valid_ops = VALID_OPERATORS_BY_KIND.get(kind, {'exact', 'isnull'})
                    if op not in valid_ops:
                        errors.append(f"Operator '{op}' is not compatible with field '{field_name}' of kind '{kind}' on model '{model_name}'.")
                    
                    # Check for indexing warnings
                    if field_name not in indexed_fields:
                        warnings.append(f"Field '{field_name}' on model '{model_name}' is not indexed. Filtering on this field may cause slow full-table scans.")
                        
                    # Check for potentially slow partial match operators on string fields without GIN/trigram index
                    if op in ('icontains', 'contains') and kind == 'string':
                        warnings.append(f"Operator '{op}' on field '{field_name}' of model '{model_name}' might perform slowly on large datasets without a trigram index.")
