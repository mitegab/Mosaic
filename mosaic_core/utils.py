import contextlib
import time
import structlog
from django.db import connection

logger = structlog.get_logger(__name__)

@contextlib.contextmanager
def track_queries(operation_name="database_operation"):
    """
    Context manager that intercepts, times, and logs all SQL queries
    executed against the active Django PostgreSQL database connection.
    """
    queries = []
    
    def wrapper(execute, sql, params, many, context):
        start_time = time.perf_counter_ns()
        try:
            return execute(sql, params, many, context)
        finally:
            elapsed_ms = (time.perf_counter_ns() - start_time) / 1_000_000.0
            queries.append({
                "sql": sql,
                "params": str(params),
                "duration_ms": elapsed_ms
            })
            
    with connection.execute_wrapper(wrapper):
        yield queries
        
    total_duration_ms = sum(q["duration_ms"] for q in queries)
    logger.info(
        "query_tracker_summary",
        operation=operation_name,
        query_count=len(queries),
        total_duration_ms=total_duration_ms,
        queries=queries
    )
