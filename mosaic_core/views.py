from django.db import connection
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import structlog

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
