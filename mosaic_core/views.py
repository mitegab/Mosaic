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


