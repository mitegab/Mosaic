import time
from django.db import connection
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import structlog
from mosaic_core.introspection import PostgresIntrospector

logger = structlog.get_logger(__name__)

@api_view(['GET'])
def health_check(request):
    db_connected = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
            row = cursor.fetchone()
        if row and row[0] == 1:
            db_connected = True
    except Exception as e:
        logger.error("database_health_check_failed", error=str(e))

    return Response({
        "status": "healthy",
        "timestamp": timezone.now().isoformat(),
        "dbConnected": db_connected
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
def models_list(request):
    try:
        introspector = PostgresIntrospector()
        try:
            models = introspector.introspect_schema()
            serialized = introspector.serialize_schema(models)
            return Response(serialized, status=status.HTTP_200_OK)
        finally:
            introspector.close()
    except Exception as e:
        logger.error("models_list_introspection_failed", error=str(e))
        return Response({
            "error": "Failed to perform database schema introspection"
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def validate_query(request):
    try:
        from mosaic_core.schemas import QueryDsl
        from mosaic_core.validator import DslValidator
        from pydantic import ValidationError
        
        # 1. Parse JSON and validate structure using Pydantic
        try:
            dsl = QueryDsl.model_validate(request.data)
        except ValidationError as ve:
            errors = []
            for err in ve.errors():
                loc = " -> ".join(str(l) for l in err["loc"])
                errors.append(f"Invalid DSL structure: at {loc}, {err['msg']}")
            return Response({
                "valid": False,
                "errors": errors,
                "warnings": []
            }, status=status.HTTP_200_OK)
            
        # 2. Run schema and semantic validation
        validator = DslValidator()
        res = validator.validate(dsl)
        return Response(res, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error("validate_query_failed", error=str(e))
        return Response({
            "valid": False,
            "errors": [f"Internal validation error: {str(e)}"],
            "warnings": []
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def execute_query(request):
    start_overall = time.perf_counter()
    logs = []
    try:
        from mosaic_core.schemas import QueryDsl
        from mosaic_core.compiler import QueryCompiler
        from mosaic_core.profiler import PlanProfiler
        from mosaic_core.orm_generator import OrmGenerator
        from pydantic import ValidationError
        
        # 1. Deserialize DSL
        try:
            dsl = QueryDsl.model_validate(request.data)
        except ValidationError as ve:
            errors = []
            for err in ve.errors():
                loc = " -> ".join(str(l) for l in err["loc"])
                errors.append(f"Invalid DSL structure: at {loc}, {err['msg']}")
            return Response({
                "rows": [],
                "metrics": {
                    "executionTimeMs": 0,
                    "rowsReturned": 0,
                    "backendLatencyMs": round((time.perf_counter() - start_overall) * 1000, 2),
                    "cacheHit": False
                },
                "orm": "Invalid DSL payload structure.",
                "logs": [f"Validation error: {e}" for e in errors],
                "executionPlan": []
            }, status=status.HTTP_200_OK)

        # 2. Compile query
        compiler = QueryCompiler()
        sql, params, compile_logs = compiler.compile(dsl)
        logs.extend(compile_logs)
        
        # 3. Execute query
        start_execute = time.perf_counter()
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            columns = [col[0] for col in cursor.description] if cursor.description else []
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        execution_time_ms = round((time.perf_counter() - start_execute) * 1000, 2)
        logs.append(f"Query executed successfully returning {len(rows)} rows in {execution_time_ms}ms")
        
        # 4. Profile execution plan
        profiler = PlanProfiler()
        plan, profiler_logs = profiler.profile_query(sql, params)
        logs.extend(profiler_logs)
        
        # 5. Translate ORMs
        generator = OrmGenerator()
        django_orm = generator.generate_django_orm(dsl)
        sqlalchemy_orm = generator.generate_sqlalchemy(dsl)
        prisma_orm = generator.generate_prisma(dsl)
        orm_str = f"# Django ORM:\n{django_orm}\n\n# SQLAlchemy:\n{sqlalchemy_orm}\n\n# Prisma:\n{prisma_orm}"
        
        # 6. Build metrics
        backend_latency = round((time.perf_counter() - start_overall) * 1000, 2)
        metrics = {
            "executionTimeMs": execution_time_ms,
            "rowsReturned": len(rows),
            "backendLatencyMs": backend_latency,
            "cacheHit": False
        }
        
        return Response({
            "rows": rows,
            "metrics": metrics,
            "orm": orm_str,
            "logs": logs,
            "executionPlan": plan
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error("execute_query_failed", error=str(e))
        backend_latency = round((time.perf_counter() - start_overall) * 1000, 2)
        return Response({
            "rows": [],
            "metrics": {
                "executionTimeMs": 0,
                "rowsReturned": 0,
                "backendLatencyMs": backend_latency,
                "cacheHit": False
            },
            "orm": "Internal execution error occurred.",
            "logs": logs + [f"Execution error: {str(e)}"],
            "executionPlan": []
        }, status=status.HTTP_200_OK)


@api_view(['POST'])
def ai_assistant(request):
    try:
        from mosaic_core.schemas import AiQueryRequest
        from mosaic_core.ai import AiAssistantEngine
        from pydantic import ValidationError

        # 1. Validate the AiQueryRequest request body
        try:
            ai_req = AiQueryRequest.model_validate(request.data)
        except ValidationError as ve:
            errors = []
            for err in ve.errors():
                loc = " -> ".join(str(l) for l in err["loc"])
                errors.append(f"Invalid AI request structure: at {loc}, {err['msg']}")
            return Response({
                "dsl": None,
                "explanation": "Validation of the request payload failed.",
                "suggestedIndexes": [],
                "warnings": errors
            }, status=status.HTTP_200_OK)

        # 2. Invoke the server-side AI Engine
        engine = AiAssistantEngine()
        res = engine.process_request(
            mode=ai_req.mode,
            prompt=ai_req.prompt,
            current_dsl=ai_req.currentDsl
        )
        return Response(res.model_dump(), status=status.HTTP_200_OK)

    except Exception as e:
        logger.error("ai_assistant_view_failed", error=str(e))
        return Response({
            "dsl": None,
            "explanation": f"Internal server error: {str(e)}",
            "suggestedIndexes": [],
            "warnings": ["An unexpected backend error occurred."]
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
