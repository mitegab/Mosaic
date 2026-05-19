import pytest
from django.conf import settings
from django.db import connection

def test_settings_loaded():
    assert settings.SECRET_KEY is not None
    assert isinstance(settings.DEBUG, bool)

@pytest.mark.django_db
def test_database_connection():
    # Attempt a basic database check on the PostgreSQL instance
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1;")
        row = cursor.fetchone()
    assert row[0] == 1
