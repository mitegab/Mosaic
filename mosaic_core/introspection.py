from django.db import connection
import structlog

logger = structlog.get_logger(__name__)

class PostgresIntrospector:
    """
    Introspects local PostgreSQL catalog system metadata to discover
    active schema tables, columns, indexes, and relationship constraints.
    """
    def __init__(self):
        self.cursor = connection.cursor()

    def get_tables(self):
        """
        Scans information_schema to find user-defined tables in the 'public' schema.
        """
        query = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
              AND table_name NOT IN ('django_migrations', 'django_content_type', 'django_session', 'django_admin_log', 'auth_permission', 'auth_group', 'auth_group_permissions', 'auth_user_groups', 'auth_user_user_permissions');
        """
        try:
            self.cursor.execute(query)
            rows = self.cursor.fetchall()
            tables = [row[0] for row in rows]
            logger.debug("introspected_tables_list", count=len(tables), tables=tables)
            return tables
        except Exception as e:
            logger.error("get_tables_catalog_failed", error=str(e))
            return []

    def get_views(self):
        """
        Scans information_schema to find user-defined views in the 'public' schema.
        """
        query = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_type = 'VIEW'
              AND table_name NOT IN ('django_migrations', 'django_content_type', 'django_session', 'django_admin_log', 'auth_permission', 'auth_group', 'auth_group_permissions', 'auth_user_groups', 'auth_user_user_permissions');
        """
        try:
            self.cursor.execute(query)
            rows = self.cursor.fetchall()
            views = [row[0] for row in rows]
            logger.debug("introspected_views_list", count=len(views), views=views)
            return views
        except Exception as e:
            logger.error("get_views_catalog_failed", error=str(e))
            return []

    def close(self):
        self.cursor.close()
