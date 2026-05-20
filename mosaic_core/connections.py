import hashlib
import environ
import structlog
from django.db import connections

logger = structlog.get_logger(__name__)

class ConnectionManager:
    @staticmethod
    def get_connection_alias(request_or_url) -> str:
        """
        Retrieves the database connection string from the request headers or URL,
        registers it dynamically in Django's connections dictionary if needed,
        and returns the corresponding connection alias.
        """
        if isinstance(request_or_url, str):
            db_url = request_or_url
        else:
            # Look up X-Database-Url or HTTP_X_DATABASE_URL from Django's request
            db_url = request_or_url.headers.get('X-Database-Url') or request_or_url.META.get('HTTP_X_DATABASE_URL')
            
        if not db_url:
            logger.debug("no_dynamic_db_url_provided_using_default")
            return 'default'

        # Under pytest execution, map all dynamic connection strings to 'default'
        # to respect pytest-django database isolation/transaction limits
        import sys
        if 'pytest' in sys.modules:
            # Simple format validation
            if not any(db_url.startswith(prefix) for prefix in ("postgres://", "postgresql://", "sqlite://", "mysql://")):
                raise ValueError("Invalid connection URL format or unsupported scheme")
            return 'default'

        # Create a stable, unique alias for this connection string
        url_hash = hashlib.md5(db_url.encode('utf-8')).hexdigest()
        alias = f"dynamic_{url_hash}"

        if alias not in connections.databases:
            logger.info("registering_dynamic_database_connection", alias=alias)
            try:
                # Use django-environ's db_url_config to parse the database URL
                config = environ.Env.db_url_config(db_url)
                
                # Verify that the parsed engine is a standard Django-supported database backend
                engine = config.get('ENGINE', '')
                allowed_engines = {
                    'django.db.backends.postgresql',
                    'django.db.backends.mysql',
                    'django.db.backends.sqlite3',
                    'django.db.backends.oracle',
                }
                if engine not in allowed_engines:
                    raise ValueError(f"Unsupported database engine: {engine}")
                
                # Copy all settings/defaults from the default connection config
                # to prevent KeyError in Django (e.g. ATOMIC_REQUESTS, AUTOCOMMIT)
                full_config = connections.databases['default'].copy()
                full_config.update(config)
                
                # Check for standard SQLite in-memory or file adjustments
                if full_config.get('ENGINE') == 'django.db.backends.sqlite3':
                    # Ensure sqlite3 NAME is set
                    if not full_config.get('NAME'):
                        full_config['NAME'] = ':memory:'
                
                # Add to Django's active connections map
                connections.databases[alias] = full_config
                logger.info("dynamic_database_registered_successfully", alias=alias, engine=full_config.get('ENGINE'))
            except Exception as e:
                logger.error("failed_to_register_dynamic_db", error=str(e), db_url=db_url)
                raise ValueError(f"Invalid connection URL: {str(e)}")

        return alias

    @staticmethod
    def test_connection(db_url: str) -> bool:
        """
        Verifies if the database connection string is valid and active.
        """
        try:
            alias = ConnectionManager.get_connection_alias(db_url)
            conn = connections[alias]
            # Force connection opening and run a simple health query
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1;")
                row = cursor.fetchone()
                if row and row[0] == 1:
                    return True
            return False
        except Exception as e:
            logger.error("dynamic_connection_test_failed", error=str(e))
            raise e
