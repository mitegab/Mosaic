import re
from typing import List, Dict, Any, Optional, Union
import structlog
from mosaic_core.schemas import QueryDsl, QueryFilter, QueryFilterGroup, QueryRelation, AiQueryResponse
from mosaic_core.validator import DslValidator

logger = structlog.get_logger(__name__)

def levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

def get_closest_match(word: str, possibilities: List[str], threshold: int = 3) -> Optional[str]:
    if not possibilities:
        return None
    matches = []
    for p in possibilities:
        dist = levenshtein_distance(word.lower(), p.lower())
        if dist <= threshold:
            matches.append((dist, p))
    if matches:
        return min(matches, key=lambda x: x[0])[1]
    for p in possibilities:
        if word.lower() in p.lower() or p.lower() in word.lower():
            return p
    return None

class AiAssistantEngine:
    """
    Live Schema-Aware AI Workbench engine providing query translation, correction,
    index optimization, and SQL translation backed by Postgres schema catalog details.
    """
    def __init__(self):
        self.validator = DslValidator()
        self.models_info = self.validator.models

    def process_request(self, mode: str, prompt: str, current_dsl: Optional[QueryDsl] = None) -> AiQueryResponse:
        try:
            if mode == 'suggest-indexes':
                return self.suggest_indexes(current_dsl)
            elif mode == 'optimize':
                return self.optimize(current_dsl)
            elif mode == 'fix':
                return self.fix(current_dsl, prompt)
            elif mode == 'sql-to-dsl':
                return self.sql_to_dsl(prompt)
            elif mode == 'generate':
                return self.generate(prompt)
            else:
                return AiQueryResponse(
                    explanation=f"Unsupported AI mode: {mode}",
                    warnings=[f"Mode {mode} is not recognized by the backend."]
                )
        except Exception as e:
            logger.exception("ai_assistant_engine_processing_failed", mode=mode, error=str(e))
            return AiQueryResponse(
                explanation=f"An error occurred in the server-side AI engine: {str(e)}",
                warnings=["Server-side processing failed."]
            )

    def suggest_indexes(self, dsl: Optional[QueryDsl]) -> AiQueryResponse:
        if not dsl:
            return AiQueryResponse(
                explanation="No query was provided. Please build a query first to receive index recommendations.",
                suggestedIndexes=[]
            )

        model_name = dsl.model
        if model_name not in self.models_info:
            return AiQueryResponse(
                explanation=f"Model '{model_name}' does not exist in schema. Cannot suggest indexes.",
                suggestedIndexes=[]
            )

        model_meta = self.models_info[model_name]
        table_name = model_meta["tableName"]
        indexed_cols = model_meta["indexed_fields"]
        fields_map = model_meta["fields"]

        suggested_sql = []
        explanation_parts = []

        # Recursively find filter fields
        def collect_filters(filters_list) -> List[QueryFilter]:
            collected = []
            for f in filters_list:
                if hasattr(f, "filters"):  # QueryFilterGroup
                    collected.extend(collect_filters(f.filters))
                else:
                    collected.append(f)
            return collected

        filters = collect_filters(dsl.filters or [])
        checked_fields = set()

        for f in filters:
            field_name = f.field
            if field_name in checked_fields:
                continue
            checked_fields.add(field_name)

            if field_name in fields_map:
                field_obj = fields_map[field_name]
                kind = field_obj.kind

                # If field is already indexed, skip or mention
                if field_name in indexed_cols:
                    explanation_parts.append(f"Field '{model_name}.{field_name}' is already indexed in the database.")
                    continue

                # Generate index recommendation
                idx_name = f"idx_{table_name}_{field_name}"
                if f.operator in ('icontains', 'contains') and kind == 'string':
                    sql = f"CREATE INDEX {idx_name}_trgm ON {table_name} USING gin ({field_name} gin_trgm_ops);"
                    suggested_sql.append(sql)
                    explanation_parts.append(
                        f"Suggested Trigram GIN index on '{model_name}.{field_name}' to accelerate high-volume partial match ('{f.operator}') filtering."
                    )
                else:
                    sql = f"CREATE INDEX {idx_name} ON {table_name} ({field_name});"
                    suggested_sql.append(sql)
                    explanation_parts.append(
                        f"Suggested B-Tree index on '{model_name}.{field_name}' to optimize search lookup filtering."
                    )

        # Check Order By fields
        if dsl.orderBy:
            for order_field in dsl.orderBy:
                clean_field = order_field.lstrip('-')
                if clean_field in fields_map and clean_field not in indexed_cols and clean_field not in checked_fields:
                    idx_name = f"idx_{table_name}_{clean_field}"
                    sql = f"CREATE INDEX {idx_name} ON {table_name} ({clean_field});"
                    suggested_sql.append(sql)
                    explanation_parts.append(
                        f"Suggested B-Tree index on '{model_name}.{clean_field}' to optimize query sorting order."
                    )

        if not suggested_sql:
            explanation = "Your query filters and ordering are fully covered by active database indices. No new indexes are required."
        else:
            explanation = " ".join(explanation_parts)

        return AiQueryResponse(
            dsl=dsl,
            explanation=explanation,
            suggestedIndexes=suggested_sql
        )

    def optimize(self, dsl: Optional[QueryDsl]) -> AiQueryResponse:
        if not dsl:
            return AiQueryResponse(explanation="Provide a valid Query DSL to optimize.")

        optimized_dsl = dsl.model_copy(deep=True)
        explanations = []

        # 1. Enforce limit caps
        if not optimized_dsl.limit:
            optimized_dsl.limit = 100
            explanations.append("Set a default safety limit of 100 rows to prevent full table scans and high network cost.")
        elif optimized_dsl.limit > 100:
            original_limit = optimized_dsl.limit
            optimized_dsl.limit = 100
            explanations.append(f"Capped query limit from {original_limit} to 100 for optimal server-side resource usage.")

        # 2. Enforce explicit projections
        model_name = dsl.model
        if model_name in self.models_info:
            fields_map = self.models_info[model_name]["fields"]
            # If no select/output is specified, select only non-relation columns
            if not optimized_dsl.select and not optimized_dsl.output:
                standard_fields = [f_name for f_name, f_obj in fields_map.items() if f_obj.kind != 'relation']
                # Take first 4 fields for cleaner response
                optimized_dsl.select = standard_fields[:4]
                explanations.append(f"Applied explicit column projection ({', '.join(optimized_dsl.select)}) instead of wildcard SELECT * to minimize column payload.")

        # 3. Check for multiple filters that could benefit from a compound index recommendation
        def count_filters(filters_list) -> int:
            count = 0
            for f in filters_list:
                if hasattr(f, "filters"):
                    count += count_filters(f.filters)
                else:
                    count += 1
            return count

        f_count = count_filters(dsl.filters or [])
        if f_count > 1:
            explanations.append("Identified multiple filter fields. Recommending a compound index on those columns if frequently run together.")

        return AiQueryResponse(
            dsl=optimized_dsl,
            explanation=" ".join(explanations)
        )

    def fix(self, dsl: Optional[QueryDsl], prompt: str) -> AiQueryResponse:
        if not dsl:
            # If no DSL is provided but a prompt is, generate one!
            return self.generate(prompt)

        fixed_dsl = dsl.model_copy(deep=True)
        explanations = []

        # 1. Check and autocorrect Model
        model_name = fixed_dsl.model
        model_options = list(self.models_info.keys())
        
        # Mappings for common names
        mappings = {
            "users": "User", "auth_users": "User", "user": "User",
            "blog": "BlogPost", "posts": "BlogPost", "post": "BlogPost", "blogpost": "BlogPost",
            "comments": "PostComment", "comment": "PostComment", "postcomment": "PostComment",
            "profiles": "UserProfile", "profile": "UserProfile", "userprofile": "UserProfile"
        }

        fixed_model = None
        if model_name not in self.models_info:
            lookup = model_name.lower().strip()
            if lookup in mappings:
                fixed_model = mappings[lookup]
            else:
                fixed_model = get_closest_match(model_name, model_options)
            
            if fixed_model:
                fixed_dsl.model = fixed_model
                explanations.append(f"Corrected model name from '{model_name}' to '{fixed_model}'.")
                model_name = fixed_model
            else:
                return AiQueryResponse(
                    explanation=f"Could not resolve model '{model_name}' in the database schema.",
                    warnings=["Verification failed: Model not found."]
                )

        model_meta = self.models_info[model_name]
        fields_map = model_meta["fields"]
        relations_map = model_meta["relations"]

        # 2. Fix select fields
        if fixed_dsl.select:
            corrected_select = []
            for f in fixed_dsl.select:
                if f in fields_map or f in relations_map:
                    corrected_select.append(f)
                else:
                    match = get_closest_match(f, list(fields_map.keys()) + list(relations_map.keys()))
                    if match:
                        corrected_select.append(match)
                        explanations.append(f"Corrected select field '{f}' to '{match}'.")
                    else:
                        explanations.append(f"Removed unrecognized select field '{f}'.")
            fixed_dsl.select = corrected_select

        # 3. Fix filters recursively
        def fix_filter_items(filters_list):
            for f in filters_list:
                if hasattr(f, "filters"):
                    fix_filter_items(f.filters)
                else:
                    field_name = f.field
                    if field_name not in fields_map:
                        match = get_closest_match(field_name, list(fields_map.keys()))
                        if match:
                            f.field = match
                            explanations.append(f"Corrected filter field '{field_name}' to '{match}'.")

        if fixed_dsl.filters:
            fix_filter_items(fixed_dsl.filters)

        # 4. Fix relations
        if fixed_dsl.relations:
            for rel in fixed_dsl.relations:
                rel_name = rel.relation or rel.field
                if rel_name not in relations_map:
                    match = get_closest_match(rel_name, list(relations_map.keys()))
                    if match:
                        if rel.relation:
                            rel.relation = match
                        if rel.field:
                            rel.field = match
                        explanations.append(f"Corrected relation path from '{rel_name}' to '{match}'.")

        # 5. Enforce safety limit if missing or set incorrectly
        if not fixed_dsl.limit or fixed_dsl.limit <= 0:
            fixed_dsl.limit = 10
            explanations.append("Applied standard safety limit default of 10 rows.")

        if not explanations:
            explanations.append("The DSL query structure, models, fields, and relationships conform perfectly to the schema. No changes were required.")

        return AiQueryResponse(
            dsl=fixed_dsl,
            explanation=" ".join(explanations)
        )

    def sql_to_dsl(self, sql: str) -> AiQueryResponse:
        # Simple schema-aware SQL transpiler
        # Normalizes spacing
        sql_normalized = re.sub(r'\s+', ' ', sql).strip()
        
        # Regex to capture SELECT, FROM, WHERE, ORDER BY, LIMIT, OFFSET
        select_match = re.search(r'SELECT\s+(.*?)\s+FROM', sql_normalized, re.IGNORECASE)
        from_match = re.search(r'FROM\s+([a-zA-Z_0-9]+)', sql_normalized, re.IGNORECASE)
        where_match = re.search(r'WHERE\s+(.*?)(?:\s+ORDER\s+BY|\s+LIMIT|\s+OFFSET|$)', sql_normalized, re.IGNORECASE)
        orderby_match = re.search(r'ORDER\s+BY\s+(.*?)(?:\s+LIMIT|\s+OFFSET|$)', sql_normalized, re.IGNORECASE)
        limit_match = re.search(r'LIMIT\s+(\d+)', sql_normalized, re.IGNORECASE)
        offset_match = re.search(r'OFFSET\s+(\d+)', sql_normalized, re.IGNORECASE)

        if not from_match:
            return AiQueryResponse(
                explanation="Could not parse table name in FROM clause. Please write a valid SQL statement.",
                warnings=["Invalid SQL structure."]
            )

        table_name = from_match.group(1).lower().strip()
        
        # Match table name to model name
        model_name = None
        for m_name, meta in self.models_info.items():
            if meta["tableName"].lower() == table_name:
                model_name = m_name
                break

        if not model_name:
            # Fallback to fuzzy match
            all_tables = [meta["tableName"] for meta in self.models_info.values()]
            best_table = get_closest_match(table_name, all_tables)
            if best_table:
                for m_name, meta in self.models_info.items():
                    if meta["tableName"] == best_table:
                        model_name = m_name
                        table_name = best_table
                        break
        
        if not model_name:
            return AiQueryResponse(
                explanation=f"Table '{table_name}' does not map to any active model in schema.",
                warnings=["Schema mismatch."]
            )

        model_meta = self.models_info[model_name]
        fields_map = model_meta["fields"]

        # Parse select fields
        select_fields = []
        if select_match:
            cols_str = select_match.group(1).strip()
            if cols_str != '*':
                cols = [c.strip() for c in cols_str.split(',')]
                for col in cols:
                    # check if column exists, strip aliases or quotes if any
                    clean_col = col.split(' ')[-1].split('.')[-1].replace('"', '').replace('`', '').strip()
                    if clean_col in fields_map:
                        select_fields.append(clean_col)
                    else:
                        match = get_closest_match(clean_col, list(fields_map.keys()))
                        if match:
                            select_fields.append(match)

        if not select_fields:
            select_fields = [f_name for f_name, f_obj in fields_map.items() if f_obj.kind != 'relation'][:4]

        # Parse filters
        filters = []
        if where_match:
            where_clause = where_match.group(1).strip()
            # Split by AND for now
            conditions = re.split(r'\s+AND\s+', where_clause, flags=re.IGNORECASE)
            for cond in conditions:
                # E.g. field = value, field > value, field LIKE value
                op_match = re.search(r'([a-zA-Z_0-9.]+)\s*(>=|<=|!=|=|>|<|LIKE|ILIKE|IS\s+NULL)\s*(.*)', cond, re.IGNORECASE)
                if op_match:
                    f_raw = op_match.group(1).split('.')[-1].strip()
                    op_raw = op_match.group(2).upper().strip()
                    val_raw = op_match.group(3).strip().strip("'\"")

                    # Map field
                    f_name = f_raw if f_raw in fields_map else get_closest_match(f_raw, list(fields_map.keys()))
                    if f_name:
                        # Map operator
                        op_map = {
                            "=": "exact",
                            ">": "gt",
                            ">=": "gte",
                            "<": "lt",
                            "<=": "lte",
                            "!=": "exact", # fallback
                            "LIKE": "contains",
                            "ILIKE": "icontains",
                            "IS NULL": "isnull"
                        }
                        op = op_map.get(op_raw, "exact")
                        val = True if op == "isnull" else val_raw
                        
                        # Handle numbers
                        if fields_map[f_name].kind == 'number':
                            try:
                                if '.' in val_raw:
                                    val = float(val_raw)
                                else:
                                    val = int(val_raw)
                            except ValueError:
                                pass
                        
                        filters.append(QueryFilter(
                            field=f_name,
                            operator=op,
                            value=val,
                            logic="AND"
                        ))

        # Parse sorting
        orderby_fields = []
        if orderby_match:
            sorts = orderby_match.group(1).split(',')
            for s in sorts:
                parts = s.strip().split(' ')
                col = parts[0].split('.')[-1].strip()
                col_name = col if col in fields_map else get_closest_match(col, list(fields_map.keys()))
                if col_name:
                    direction = "-" if len(parts) > 1 and parts[1].upper() == "DESC" else ""
                    orderby_fields.append(f"{direction}{col_name}")

        # Parse limit and offset
        limit_val = int(limit_match.group(1)) if limit_match else 10
        offset_val = int(offset_match.group(1)) if offset_match else None

        dsl = QueryDsl(
            model=model_name,
            select=select_fields,
            filters=filters if filters else None,
            orderBy=orderby_fields if orderby_fields else None,
            limit=limit_val,
            offset=offset_val
        )

        return AiQueryResponse(
            dsl=dsl,
            explanation=f"Successfully transpiled SQL statement for table '{table_name}' into schema-conforming Query DSL."
        )

    def generate(self, prompt: str) -> AiQueryResponse:
        p_lower = prompt.lower()

        # 1. Classify target model
        model_name = "User"
        if any(w in p_lower for w in ("comment", "comments", "body", "rating")):
            model_name = "PostComment"
        elif any(w in p_lower for w in ("post", "posts", "blog", "title", "content", "status")):
            model_name = "BlogPost"
        elif any(w in p_lower for w in ("profile", "bio", "avatar", "phone")):
            model_name = "UserProfile"
        elif any(w in p_lower for w in ("user", "users", "email", "username", "is_active")):
            model_name = "User"

        model_meta = self.models_info[model_name]
        fields_map = model_meta["fields"]

        # Default select fields
        default_fields = {
            "User": ["id", "username", "email", "is_active"],
            "UserProfile": ["id", "bio", "phone"],
            "BlogPost": ["id", "title", "status", "published_at"],
            "PostComment": ["id", "body", "rating", "created_at"]
        }
        select_fields = default_fields[model_name]

        filters = []
        explanations = [f"Identified target model '{model_name}' based on prompt keywords."]

        # 2. Extract Filters
        # Look for status filters in BlogPost
        if model_name == "BlogPost":
            if "published" in p_lower:
                filters.append(QueryFilter(field="status", operator="exact", value="published", logic="AND"))
                explanations.append("Applied filter: status = 'published'.")
            elif "draft" in p_lower:
                filters.append(QueryFilter(field="status", operator="exact", value="draft", logic="AND"))
                explanations.append("Applied filter: status = 'draft'.")

        # Look for is_active filters in User
        if model_name == "User":
            if "active" in p_lower and "inactive" not in p_lower:
                filters.append(QueryFilter(field="is_active", operator="exact", value=True, logic="AND"))
                explanations.append("Applied filter: is_active = True.")
            elif "inactive" in p_lower or "disabled" in p_lower:
                filters.append(QueryFilter(field="is_active", operator="exact", value=False, logic="AND"))
                explanations.append("Applied filter: is_active = False.")

        # Look for text matching
        # E.g., matching "containing 'django'", or "about 'ai'"
        match_quote = re.search(r"(?:containing|about|matching|with|named)\s+['\"](.*?)['\"]", p_lower)
        if match_quote:
            text_val = match_quote.group(1)
            # Find a suitable string field
            string_fields = [f_name for f_name, f_obj in fields_map.items() if f_obj.kind == 'string']
            target_field = "title" if "title" in string_fields else (string_fields[0] if string_fields else None)
            if target_field:
                filters.append(QueryFilter(field=target_field, operator="icontains", value=text_val, logic="AND"))
                explanations.append(f"Applied text filter on '{target_field}' containing '{text_val}'.")

        # Look for rating filters in PostComment
        if model_name == "PostComment":
            # rating > X, rating greater than X, rating of X
            rating_match = re.search(r"rating\s*(?:greater than|>)\s*(\d+)", p_lower)
            if rating_match:
                val = int(rating_match.group(1))
                filters.append(QueryFilter(field="rating", operator="gt", value=val, logic="AND"))
                explanations.append(f"Applied filter: rating > {val}.")
            else:
                rating_match_exact = re.search(r"rating\s*(?:of|=)\s*(\d+)", p_lower)
                if rating_match_exact:
                    val = int(rating_match_exact.group(1))
                    filters.append(QueryFilter(field="rating", operator="exact", value=val, logic="AND"))
                    explanations.append(f"Applied filter: rating = {val}.")

        # Look for datetime filters
        # e.g., after 2024, since 2023
        year_match = re.search(r"(?:after|since|newer than)\s+(\d{4})", p_lower)
        if year_match:
            year = year_match.group(1)
            date_fields = [f_name for f_name, f_obj in fields_map.items() if f_obj.kind in ('date', 'datetime')]
            target_date = "published_at" if "published_at" in date_fields else ("created_at" if "created_at" in date_fields else (date_fields[0] if date_fields else None))
            if target_date:
                filters.append(QueryFilter(field=target_date, operator="gt", value=f"{year}-01-01T00:00:00Z", logic="AND"))
                explanations.append(f"Applied date filter on '{target_date}' after {year}-01-01.")

        # Default limit
        limit_val = 10
        explanations.append("Applied draft safety limit of 10 rows.")

        dsl = QueryDsl(
            model=model_name,
            select=select_fields,
            filters=filters if filters else None,
            limit=limit_val
        )

        return AiQueryResponse(
            dsl=dsl,
            explanation=" ".join(explanations),
            warnings=["Generated visual Query DSL draft from natural language description. Inspect and test before executing."]
        )
