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

    def get_columns(self, table_name):
        """
        Fetches columns for the given table name, return list of dicts with:
        name, data_type, nullable, primary_key.
        """
        query = """
            SELECT 
                c.column_name, 
                c.data_type, 
                c.is_nullable,
                CASE WHEN kcu.column_name IS NOT NULL THEN TRUE ELSE FALSE END as is_primary_key
            FROM information_schema.columns c
            LEFT JOIN information_schema.key_column_usage kcu 
              ON c.table_name = kcu.table_name 
              AND c.column_name = kcu.column_name 
              AND c.table_schema = kcu.table_schema
              AND kcu.constraint_name IN (
                  SELECT constraint_name 
                  FROM information_schema.table_constraints 
                  WHERE table_name = c.table_name 
                    AND table_schema = c.table_schema 
                    AND constraint_type = 'PRIMARY KEY'
              )
            WHERE c.table_schema = 'public' AND c.table_name = %s
            ORDER BY c.ordinal_position;
        """
        try:
            self.cursor.execute(query, [table_name])
            rows = self.cursor.fetchall()
            columns = []
            for row in rows:
                columns.append({
                    "name": row[0],
                    "data_type": row[1],
                    "kind": self.normalize_type(row[1]),
                    "nullable": row[2] == "YES",
                    "primary_key": bool(row[3])
                })
            logger.debug("introspected_table_columns", table_name=table_name, count=len(columns), columns=columns)
            return columns
        except Exception as e:
            logger.error("get_columns_catalog_failed", table_name=table_name, error=str(e))
            return []

    def normalize_type(self, db_type):
        """
        Maps PostgreSQL raw types to standardized frontend kind:
        'string' | 'number' | 'boolean' | 'date' | 'datetime' | 'json' | 'relation' | 'unknown'
        """
        db_type = db_type.lower().strip()
        if db_type in ("integer", "bigint", "smallint", "numeric", "double precision", "real", "serial", "bigserial"):
            return "number"
        elif db_type in ("boolean", "bool"):
            return "boolean"
        elif db_type in ("date",):
            return "date"
        elif "timestamp" in db_type or "timestamptz" in db_type or db_type in ("timestamp without time zone", "timestamp with time zone"):
            return "datetime"
        elif db_type in ("jsonb", "json"):
            return "json"
        elif any(t in db_type for t in ("character", "char", "varchar", "text", "uuid", "varying")):
            return "string"
        else:
            return "unknown"

    def get_constraints(self, table_name):
        """
        Fetches constraints for the given table: primary keys, unique constraints.
        Returns a dict mapping column names to constraint lists.
        """
        query = """
            SELECT 
                kcu.column_name,
                tc.constraint_type,
                tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu 
              ON tc.constraint_name = kcu.constraint_name
              AND tc.table_schema = kcu.table_schema
            WHERE tc.table_schema = 'public' AND tc.table_name = %s;
        """
        try:
            self.cursor.execute(query, [table_name])
            rows = self.cursor.fetchall()
            constraints = {}
            for row in rows:
                col = row[0]
                const_type = row[1]
                const_name = row[2]
                if col not in constraints:
                    constraints[col] = []
                constraints[col].append({
                    "type": const_type,
                    "name": const_name
                })
            logger.debug("introspected_table_constraints", table_name=table_name, count=len(constraints), constraints=constraints)
            return constraints
        except Exception as e:
            logger.error("get_constraints_catalog_failed", table_name=table_name, error=str(e))
            return {}

    def close(self):
        self.cursor.close()
