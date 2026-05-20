import structlog
from typing import List, Dict, Any, Tuple, Optional, Set, Union
from mosaic_core.schemas import QueryDsl, QueryFilter, QueryFilterGroup, QueryRelation

logger = structlog.get_logger(__name__)

class QueryCompiler:
    def __init__(self, schema_models: Optional[List[Any]] = None):
        if schema_models is None:
            from mosaic_core.introspection import PostgresIntrospector
            introspector = PostgresIntrospector()
            try:
                schema_models = introspector.introspect_schema()
            finally:
                introspector.close()
                
        # Build lookups
        self.models = {}
        for model in schema_models:
            fields_map = {f.name: f for f in model.fields}
            self.models[model.name] = {
                "tableName": model.tableName,
                "fields": fields_map,
                "model_obj": model
            }
            
        # Get all foreign keys for join resolution
        from mosaic_core.introspection import PostgresIntrospector
        introspector = PostgresIntrospector()
        try:
            self.fks = introspector.get_all_foreign_keys()
        finally:
            introspector.close()

    def compile(self, dsl: QueryDsl) -> Tuple[str, List[Any], List[str]]:
        """
        Compiles QueryDsl into a safe parameterized SQL string and a list of bind parameters.
        Returns: (sql_string, parameters, logs)
        """
        logs = []
        params = []
        
        root_model = dsl.model
        if root_model not in self.models:
            raise ValueError(f"Model '{root_model}' does not exist in schema.")
            
        root_table = self.models[root_model]["tableName"]
        logs.append(f"Compiling DSL query for root model: {root_model} (table: {root_table})")
        
        # Build SELECT clause
        select_cols = []
        
        # Determine root columns to select
        root_select = dsl.select or dsl.output
        if not root_select:
            # Default to all standard fields on root
            root_select = [
                f_name for f_name, f_obj in self.models[root_model]["fields"].items()
                if f_obj.kind != "relation"
            ]
            
        for col_name in root_select:
            if col_name in self.models[root_model]["fields"]:
                field_obj = self.models[root_model]["fields"][col_name]
                if field_obj.kind != "relation":
                    select_cols.append(f"{root_table}.{col_name} AS \"{col_name}\"")
                    
        # Track tables joined to prevent duplicate joins
        joined_tables: Set[str] = set()
        join_clauses = []
        
        # Process relations for JOINs and nested select columns
        if dsl.relations:
            self._compile_relations(
                root_model,
                root_table,
                dsl.relations,
                join_clauses,
                select_cols,
                joined_tables,
                path_prefix=""
            )
            
        # Process filters for WHERE clause
        where_clause, filter_params = self._compile_filters(
            root_model,
            root_table,
            dsl.filters,
            path_prefix=""
        )
        params.extend(filter_params)
        
        # Combine parts
        sql = f"SELECT {', '.join(select_cols)} FROM {root_table}"
        
        if join_clauses:
            sql += " " + " ".join(join_clauses)
            
        if where_clause:
            sql += f" WHERE {where_clause}"
            
        # Order By
        if dsl.orderBy:
            order_parts = []
            for spec in dsl.orderBy:
                desc = spec.startswith("-")
                col = spec[1:] if desc else spec
                # Check if it exists on root model
                if col in self.models[root_model]["fields"]:
                    direction = "DESC" if desc else "ASC"
                    order_parts.append(f"{root_table}.{col} {direction}")
            if order_parts:
                sql += f" ORDER BY {', '.join(order_parts)}"
                
        # Limit & Offset
        if dsl.limit is not None:
            sql += f" LIMIT {int(dsl.limit)}"
        if dsl.offset is not None:
            sql += f" OFFSET {int(dsl.offset)}"
            
        logs.append(f"Generated SQL: {sql}")
        logs.append(f"Parameters: {params}")
        return sql, params, logs

    def _compile_relations(
        self,
        current_model: str,
        current_table: str,
        relations: List[QueryRelation],
        join_clauses: List[str],
        select_cols: List[str],
        joined_tables: Set[str],
        path_prefix: str
    ):
        for rel in relations:
            # Detect if it's the backend recursive model or frontend relation
            if rel.relation:
                # Backend style
                rel_name = rel.relation
            elif rel.field:
                # Frontend style edge connecting from/to
                rel_name = rel.field
            else:
                continue
                
            # Find the relationship field in current model
            fields_map = self.models[current_model]["fields"]
            if rel_name not in fields_map:
                continue
                
            rel_field = fields_map[rel_name]
            if rel_field.kind != "relation":
                continue
                
            related_model = rel_field.relatedModel
            if not related_model or related_model not in self.models:
                continue
                
            related_table = self.models[related_model]["tableName"]
            
            # Resolve JOIN condition
            join_cond = self._resolve_join_condition(current_table, related_table, rel_name)
            if not join_cond:
                continue
                
            # Use unique table alias if same table is joined multiple times
            join_key = f"{current_table}_to_{related_table}_{rel_name}"
            if join_key not in joined_tables:
                join_clauses.append(f"LEFT JOIN {related_table} ON {join_cond}")
                joined_tables.add(join_key)
                
            # Compile nested select columns
            next_prefix = f"{path_prefix}{rel_name}__"
            if rel.select:
                for col_name in rel.select:
                    if col_name in self.models[related_model]["fields"]:
                        col_field = self.models[related_model]["fields"][col_name]
                        if col_field.kind != "relation":
                            select_cols.append(f"{related_table}.{col_name} AS \"{next_prefix}{col_name}\"")
                            
            # Recurse if there are sub-relations
            if rel.relations:
                self._compile_relations(
                    related_model,
                    related_table,
                    rel.relations,
                    join_clauses,
                    select_cols,
                    joined_tables,
                    next_prefix
                )

    def _resolve_join_condition(self, from_table: str, to_table: str, field_name: str) -> Optional[str]:
        # Outgoing FK from from_table to to_table
        for fk in self.fks:
            if fk["source_table"] == from_table and fk["target_table"] == to_table:
                src_col = fk["source_column"]
                if src_col == field_name or src_col == f"{field_name}_id" or field_name == src_col[:-3]:
                    return f"{to_table}.{fk['target_column']} = {from_table}.{src_col}"
                    
        # Incoming FK from to_table to from_table (reverse relation)
        for fk in self.fks:
            if fk["source_table"] == to_table and fk["target_table"] == from_table:
                return f"{to_table}.{fk['source_column']} = {from_table}.{fk['target_column']}"
                
        return None

    def _compile_filters(
        self,
        model_name: str,
        table_name: str,
        filters: Optional[List[Union[QueryFilter, QueryFilterGroup]]],
        path_prefix: str
    ) -> Tuple[str, List[Any]]:
        if not filters:
            return "", []
            
        grouped = self._group_filters(filters)
        
        parts = []
        params = []
        
        for logic_type, item in grouped:
            if logic_type == "OR":
                or_parts = []
                for sub_filter in item:
                    cond, sub_params = self._compile_single_filter_or_group(model_name, table_name, sub_filter)
                    if cond:
                        or_parts.append(cond)
                        params.extend(sub_params)
                if or_parts:
                    parts.append(f"({ ' OR '.join(or_parts) })")
            else:  # AND / single filter
                cond, sub_params = self._compile_single_filter_or_group(model_name, table_name, item)
                if cond:
                    parts.append(cond)
                    params.extend(sub_params)
                    
        if parts:
            return " AND ".join(parts), params
        return "", []

    def _group_filters(self, filters):
        """
        Groups list of filters based on consecutive logic rules.
        """
        if not filters:
            return []
            
        grouped = []
        or_buffer = []
        
        for i, f in enumerate(filters):
            f_logic = getattr(f, "logic", None)
            
            next_f = filters[i + 1] if i + 1 < len(filters) else None
            next_logic = getattr(next_f, "logic", None) if next_f else None
            
            is_or = (f_logic in ("OR", "or")) or (next_logic in ("OR", "or"))
            
            # If the current filter is a group, treat it as single AND item (no flat OR buffering)
            if hasattr(f, "filters"):
                if or_buffer:
                    grouped.append(("OR", or_buffer))
                    or_buffer = []
                grouped.append(("AND", f))
                continue
                
            if is_or:
                or_buffer.append(f)
            else:
                if or_buffer:
                    or_buffer.append(f)
                    grouped.append(("OR", or_buffer))
                    or_buffer = []
                else:
                    grouped.append(("AND", f))
                    
        if or_buffer:
            grouped.append(("OR", or_buffer))
            
        return grouped

    def _compile_single_filter_or_group(
        self,
        model_name: str,
        table_name: str,
        item: Union[QueryFilter, QueryFilterGroup]
    ) -> Tuple[str, List[Any]]:
        if hasattr(item, "filters"):  # QueryFilterGroup
            sub_parts = []
            sub_params = []
            for sub in item.filters:
                cond, p = self._compile_single_filter_or_group(model_name, table_name, sub)
                if cond:
                    sub_parts.append(cond)
                    sub_params.extend(p)
            if sub_parts:
                logic_op = f" {item.logic.upper()} "
                return f"({logic_op.join(sub_parts)})", sub_params
            return "", []
            
        # Standard filter
        field_name = item.field
        op = item.operator
        val = item.value
        
        # Check field exists
        fields_map = self.models[model_name]["fields"]
        if field_name not in fields_map:
            return "", []
            
        # Map operator to SQL
        if op == "exact":
            if val is None:
                return f"{table_name}.{field_name} IS NULL", []
            else:
                return f"{table_name}.{field_name} = %s", [val]
        elif op == "contains":
            return f"{table_name}.{field_name} LIKE %s", [f"%{val}%"]
        elif op == "icontains":
            return f"{table_name}.{field_name} ILIKE %s", [f"%{val}%"]
        elif op == "gt":
            return f"{table_name}.{field_name} > %s", [val]
        elif op == "gte":
            return f"{table_name}.{field_name} >= %s", [val]
        elif op == "lt":
            return f"{table_name}.{field_name} < %s", [val]
        elif op == "lte":
            return f"{table_name}.{field_name} <= %s", [val]
        elif op == "in":
            if isinstance(val, list):
                val_list = val
            elif isinstance(val, str):
                val_list = [v.strip() for v in val.split(",") if v.strip()]
            else:
                val_list = [val]
            return f"{table_name}.{field_name} = ANY(%s)", [val_list]
        elif op == "isnull":
            is_null = bool(val)
            if is_null:
                return f"{table_name}.{field_name} IS NULL", []
            else:
                return f"{table_name}.{field_name} IS NOT NULL", []
                
        return "", []
