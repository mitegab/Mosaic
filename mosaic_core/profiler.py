import time
import json
import structlog
from typing import List, Dict, Any, Tuple, Optional
from django.db import connections

logger = structlog.get_logger(__name__)

class PlanProfiler:
    """
    Profiles SQL queries by running EXPLAIN on PostgreSQL, MySQL, or SQLite,
    and parses the execution plan into standardized ExecutionPlanStep items.
    """
    def __init__(self, connection_alias='default'):
        self.connection_alias = connection_alias

    def profile_query(self, sql: str, params: List[Any]) -> Tuple[Optional[List[Dict[str, Any]]], List[str]]:
        logs = []
        try:
            conn = connections[self.connection_alias]
            if conn.vendor != 'postgresql':
                return self._profile_query_generic(sql, params, conn)

            # We run EXPLAIN (ANALYZE, FORMAT JSON) to get actual timings if possible.
            # In case the database has strict read-only settings or we want to be 100% safe,
            # we fallback to regular EXPLAIN (FORMAT JSON) which doesn't execute the query.
            explain_query = f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}"
            logs.append("Running EXPLAIN (ANALYZE, FORMAT JSON) to retrieve execution plan")
            
            try:
                with conn.cursor() as cursor:
                    cursor.execute(explain_query, params)
                    explain_data = cursor.fetchone()[0]
            except Exception as analyze_err:
                logs.append(f"EXPLAIN ANALYZE failed: {str(analyze_err)}. Falling back to EXPLAIN (FORMAT JSON)")
                # Reset connection state after error if needed, and fallback
                explain_query_safe = f"EXPLAIN (FORMAT JSON) {sql}"
                with conn.cursor() as cursor_safe:
                    cursor_safe.execute(explain_query_safe, params)
                    explain_data = cursor_safe.fetchone()[0]
            
            # Parse explain output
            if isinstance(explain_data, str):
                explain_json = json.loads(explain_data)
            else:
                explain_json = explain_data
                
            steps = self._parse_plan_root(explain_json)
            return steps, logs
            
        except Exception as e:
            logger.error("profiling_query_failed", error=str(e))
            logs.append(f"Failed to profile query: {str(e)}")
            return None, logs

    def _profile_query_generic(self, sql: str, params: List[Any], conn) -> Tuple[Optional[List[Dict[str, Any]]], List[str]]:
        logs = []
        try:
            vendor = conn.vendor
            if vendor == 'sqlite':
                explain_query = f"EXPLAIN QUERY PLAN {sql}"
            else:
                explain_query = f"EXPLAIN {sql}"
                
            logs.append(f"Running {explain_query} to retrieve execution plan")
            with conn.cursor() as cursor:
                cursor.execute(explain_query, params)
                rows = cursor.fetchall()
                
            steps = []
            for i, row in enumerate(rows):
                label = f"Step {i+1}"
                detail = " | ".join(str(val) for val in row if val is not None)
                steps.append({
                    "id": str(i + 1),
                    "label": label,
                    "detail": detail,
                    "durationMs": 0.0
                })
            return steps, logs
        except Exception as e:
            logger.warning("generic_profile_failed", error=str(e))
            logs.append(f"Profile not supported or failed for vendor {conn.vendor}: {str(e)}")
            return None, logs

    def _parse_plan_root(self, explain_json: Any) -> List[Dict[str, Any]]:
        if not explain_json or not isinstance(explain_json, list):
            return []
            
        root_plan = explain_json[0].get("Plan", {})
        
        counter = {"id": 1}
        return [self._parse_node(root_plan, counter)]

    def _parse_node(self, node: Dict[str, Any], counter: Dict[str, int]) -> Dict[str, Any]:
        node_id = str(counter["id"])
        counter["id"] += 1
        
        label = node.get("Node Type", "Scan")
        
        # Build detail string
        details = []
        if "Relation Name" in node:
            details.append(f"on {node['Relation Name']}")
        if "Index Name" in node:
            details.append(f"using {node['Index Name']}")
        if "Index Cond" in node:
            details.append(f"cond: {node['Index Cond']}")
        if "Filter" in node:
            details.append(f"filter: {node['Filter']}")
            
        detail_str = " ".join(details)
        
        # Duration: Actual Total Time is in ms. If not present, we can estimate from Total Cost.
        duration_ms = None
        if "Actual Total Time" in node:
            duration_ms = float(node["Actual Total Time"])
        elif "Total Cost" in node:
            # Estimate roughly from cost
            duration_ms = round(float(node["Total Cost"]) / 100.0, 3)
            
        # Recurse children
        children = []
        if "Plans" in node:
            for sub_plan in node["Plans"]:
                children.append(self._parse_node(sub_plan, counter))
                
        step = {
            "id": node_id,
            "label": label,
            "detail": detail_str if detail_str else None,
            "durationMs": duration_ms,
        }
        if children:
            step["children"] = children
            
        return step
