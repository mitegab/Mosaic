from typing import Any, List, Dict, Union, Optional
from mosaic_core.schemas import QueryDsl, QueryFilter, QueryFilterGroup, QueryRelation

class OrmGenerator:
    """
    Generates equivalent ORM query code in:
    1. Django ORM
    2. SQLAlchemy Core / ORM
    3. Prisma client
    """
    def generate_django_orm(self, dsl: QueryDsl) -> str:
        model = dsl.model
        parts = [f"{model}.objects"]
        
        # 1. Filters
        if dsl.filters:
            filter_args = self._django_filters(dsl.filters)
            if filter_args:
                parts.append(f"filter({filter_args})")
                
        # 2. Relations (Select/Prefetch Related)
        if dsl.relations:
            related_fields = []
            for rel in dsl.relations:
                rel_name = rel.relation or rel.field
                if rel_name:
                    related_fields.append(f"'{rel_name}'")
            if related_fields:
                parts.append(f"select_related({', '.join(related_fields)})")
                
        # 3. Projection / Values
        select_fields = dsl.select or dsl.output
        if select_fields:
            field_list = ", ".join(f"'{f}'" for f in select_fields)
            parts.append(f"values({field_list})")
            
        # 4. Sorting
        if dsl.orderBy:
            order_list = ", ".join(f"'{o}'" for o in dsl.orderBy)
            parts.append(f"order_by({order_list})")
            
        # 5. Limit/Offset slicing
        slice_str = ""
        offset = dsl.offset or 0
        limit = dsl.limit
        
        if limit is not None:
            slice_str = f"[{offset}:{offset + limit}]"
        elif offset > 0:
            slice_str = f"[{offset}:]"
            
        return ".".join(parts) + slice_str

    def _django_filters(self, filters: List[Union[QueryFilter, QueryFilterGroup]]) -> str:
        conds = []
        for item in filters:
            if hasattr(item, "filters"):  # Group
                # For groups, we combine using Q objects
                sub_conds = []
                for sub in item.filters:
                    if not hasattr(sub, "filters"):
                        sub_conds.append(self._django_single_filter(sub))
                if sub_conds:
                    logic_symbol = " | " if item.logic.upper() == "OR" else " & "
                    conds.append(f"({logic_symbol.join(sub_conds)})")
            else:
                conds.append(self._django_single_filter(item))
        return ", ".join(conds)

    def _django_single_filter(self, f: QueryFilter) -> str:
        field = f.field
        op = f.operator
        val = repr(f.value)
        
        if op == "exact":
            return f"{field}={val}"
        elif op == "isnull":
            return f"{field}__isnull={val}"
        else:
            return f"{field}__{op}={val}"

    def generate_sqlalchemy(self, dsl: QueryDsl) -> str:
        model = dsl.model
        select_fields = dsl.select or dsl.output
        
        # Select list
        if select_fields:
            select_cols = ", ".join(f"{model}.{f}" for f in select_fields)
            q = f"select({select_cols})"
        else:
            q = f"select({model})"
            
        # Joins
        if dsl.relations:
            for rel in dsl.relations:
                rel_name = rel.relation or rel.field
                if rel_name:
                    q += f".join({model}.{rel_name})"
                    
        # Filters
        if dsl.filters:
            filter_clauses = self._sqlalchemy_filters(model, dsl.filters)
            if filter_clauses:
                q += f".filter({filter_clauses})"
                
        # Order By
        if dsl.orderBy:
            order_parts = []
            for spec in dsl.orderBy:
                desc = spec.startswith("-")
                col = spec[1:] if desc else spec
                if desc:
                    order_parts.append(f"{model}.{col}.desc()")
                else:
                    order_parts.append(f"{model}.{col}.asc()")
            q += f".order_by({', '.join(order_parts)})"
            
        # Limit / Offset
        if dsl.limit is not None:
            q += f".limit({dsl.limit})"
        if dsl.offset is not None:
            q += f".offset({dsl.offset})"
            
        return q

    def _sqlalchemy_filters(self, model: str, filters: List[Union[QueryFilter, QueryFilterGroup]]) -> str:
        conds = []
        for item in filters:
            if hasattr(item, "filters"):
                sub_conds = []
                for sub in item.filters:
                    if not hasattr(sub, "filters"):
                        sub_conds.append(self._sqlalchemy_single_filter(model, sub))
                if sub_conds:
                    logic_fn = "or_" if item.logic.upper() == "OR" else "and_"
                    conds.append(f"{logic_fn}({', '.join(sub_conds)})")
            else:
                conds.append(self._sqlalchemy_single_filter(model, item))
        return ", ".join(conds)

    def _sqlalchemy_single_filter(self, model: str, f: QueryFilter) -> str:
        field = f.field
        op = f.operator
        val = repr(f.value)
        
        if op == "exact":
            return f"{model}.{field} == {val}"
        elif op == "gt":
            return f"{model}.{field} > {val}"
        elif op == "gte":
            return f"{model}.{field} >= {val}"
        elif op == "lt":
            return f"{model}.{field} < {val}"
        elif op == "lte":
            return f"{model}.{field} <= {val}"
        elif op == "contains":
            return f"{model}.{field}.like(f'%{{{val}}}%')"
        elif op == "icontains":
            return f"{model}.{field}.ilike(f'%{{{val}}}%')"
        elif op == "in":
            return f"{model}.{field}.in_({val})"
        elif op == "isnull":
            return f"{model}.{field} == None" if f.value else f"{model}.{field} != None"
        return f"{model}.{field}"

    def generate_prisma(self, dsl: QueryDsl) -> str:
        model_camel = dsl.model[0].lower() + dsl.model[1:]
        
        args = {}
        
        # 1. Select Projection
        select_fields = dsl.select or dsl.output
        if select_fields:
            args["select"] = {f: True for f in select_fields}
            
        # 2. Relations
        if dsl.relations:
            if "select" not in args:
                # If select is not active, we can use include
                args["include"] = {}
                for rel in dsl.relations:
                    rel_name = rel.relation or rel.field
                    if rel_name:
                        args["include"][rel_name] = True
            else:
                # If select is active, Prisma requires joined models to be nested in select
                for rel in dsl.relations:
                    rel_name = rel.relation or rel.field
                    if rel_name:
                        rel_select = {sf: True for sf in rel.select} if rel.select else True
                        args["select"][rel_name] = rel_select
                        
        # 3. Where Clause
        if dsl.filters:
            args["where"] = self._prisma_filters(dsl.filters)
            
        # 4. Order By
        if dsl.orderBy:
            order_list = []
            for spec in dsl.orderBy:
                desc = spec.startswith("-")
                col = spec[1:] if desc else spec
                order_list.append({col: "desc" if desc else "asc"})
            args["orderBy"] = order_list
            
        # 5. Take & Skip
        if dsl.limit is not None:
            args["take"] = dsl.limit
        if dsl.offset is not None:
            args["skip"] = dsl.offset
            
        # Format as Javascript invocation
        def format_dict(d: dict, indent: int = 2) -> str:
            # Simple custom formatter to look like standard JS object literals
            lines = []
            spaces = " " * indent
            for k, v in d.items():
                if isinstance(v, dict):
                    formatted_val = format_dict(v, indent + 2)
                    lines.append(f"{spaces}{k}: {formatted_val}")
                elif isinstance(v, list):
                    item_strs = []
                    for item in v:
                        if isinstance(item, dict):
                            item_strs.append(format_dict(item, indent + 2).strip())
                        else:
                            item_strs.append(repr(item))
                    lines.append(f"{spaces}{k}: [{', '.join(item_strs)}]")
                elif isinstance(v, bool):
                    lines.append(f"{spaces}{k}: {str(v).lower()}")
                else:
                    lines.append(f"{spaces}{k}: {repr(v)}")
            return "{\n" + ",\n".join(lines) + "\n" + (" " * (indent - 2)) + "}"

        if args:
            args_str = format_dict(args)
            return f"prisma.{model_camel}.findMany({args_str})"
        return f"prisma.{model_camel}.findMany()"

    def _prisma_filters(self, filters: List[Union[QueryFilter, QueryFilterGroup]]) -> dict:
        # Standardize filters list to Prisma where structure
        and_list = []
        or_list = []
        
        for item in filters:
            if hasattr(item, "filters"):
                sub_list = []
                for sub in item.filters:
                    if not hasattr(sub, "filters"):
                        sub_list.append(self._prisma_single_filter(sub))
                if sub_list:
                    key = "OR" if item.logic.upper() == "OR" else "AND"
                    and_list.append({key: sub_list})
            else:
                # Handle consecutive logic grouping
                f_logic = getattr(item, "logic", None)
                if f_logic in ("OR", "or"):
                    or_list.append(self._prisma_single_filter(item))
                else:
                    if or_list:
                        or_list.append(self._prisma_single_filter(item))
                        and_list.append({"OR": or_list})
                        or_list = []
                    else:
                        and_list.append(self._prisma_single_filter(item))
                        
        if or_list:
            and_list.append({"OR": or_list})
            
        if len(and_list) == 1:
            return and_list[0]
        elif and_list:
            return {"AND": and_list}
        return {}

    def _prisma_single_filter(self, f: QueryFilter) -> dict:
        field = f.field
        op = f.operator
        val = f.value
        
        if op == "exact":
            return {field: val}
        elif op == "gt":
            return {field: {"gt": val}}
        elif op == "gte":
            return {field: {"gte": val}}
        elif op == "lt":
            return {field: {"lt": val}}
        elif op == "lte":
            return {field: {"lte": val}}
        elif op == "contains" or op == "icontains":
            mode = "insensitive" if op == "icontains" else "default"
            return {field: {"contains": val, "mode": mode}}
        elif op == "in":
            return {field: {"in": val}}
        elif op == "isnull":
            return {field: {"equals": None}} if val else {field: {"not": None}}
            
        return {field: val}
