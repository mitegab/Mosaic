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

    def get_indexes(self, table_name):
        """
        Fetches indexes (BTree, GIN, etc.) for columns of the given table.
        Returns a dict mapping column names to index lists.
        """
        query = """
            SELECT
                i.relname AS index_name,
                a.attname AS column_name,
                am.amname AS index_type,
                ix.indisunique AS is_unique
            FROM
                pg_class t
            JOIN
                pg_index ix ON t.oid = ix.indrelid
            JOIN
                pg_class i ON i.oid = ix.indexrelid
            JOIN
                pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
            JOIN
                pg_am am ON i.relam = am.oid
            WHERE
                t.relkind = 'r'
                AND t.relname = %s;
        """
        try:
            self.cursor.execute(query, [table_name])
            rows = self.cursor.fetchall()
            indexes = {}
            for row in rows:
                idx_name = row[0]
                col = row[1]
                idx_type = row[2]
                is_unique = bool(row[3])
                if col not in indexes:
                    indexes[col] = []
                indexes[col].append({
                    "name": idx_name,
                    "type": idx_type,
                    "is_unique": is_unique
                })
            logger.debug("introspected_table_indexes", table_name=table_name, count=len(indexes), indexes=indexes)
            return indexes
        except Exception as e:
            logger.error("get_indexes_catalog_failed", table_name=table_name, error=str(e))
            return {}

    def get_all_foreign_keys(self):
        """
        Fetches all foreign key constraints in the public schema.
        Returns a list of dicts with constraint_name, source_table, source_column, target_table, target_column.
        """
        query = """
            SELECT
                tc.constraint_name,
                tc.table_name AS source_table,
                kcu.column_name AS source_column,
                ccu.table_name AS target_table,
                ccu.column_name AS target_column
            FROM
                information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
              AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
              ON ccu.constraint_name = tc.constraint_name
              AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public';
        """
        try:
            self.cursor.execute(query)
            rows = self.cursor.fetchall()
            fks = []
            for row in rows:
                fks.append({
                    "constraint_name": row[0],
                    "source_table": row[1],
                    "source_column": row[2],
                    "target_table": row[3],
                    "target_column": row[4]
                })
            logger.debug("introspected_all_foreign_keys", count=len(fks), fks=fks)
            return fks
        except Exception as e:
            logger.error("get_all_foreign_keys_failed", error=str(e))
            return []

    def get_relations(self, table_name, all_fks):
        """
        Solves relationships for the table based on foreign keys.
        Returns a list of dicts matching SchemaField shape:
        {
          "name": str,
          "type": "relation",
          "kind": "relation",
          "relatedModel": str,
          "relationType": "one-to-one" | "one-to-many" | "many-to-one" | "many-to-many"
        }
        """
        relations = []
        
        # Helper to convert table to model name
        def table_to_model_name(t_name):
            mapping = {
                "auth_users": "User",
                "user_profiles": "UserProfile",
                "blog_posts": "BlogPost",
                "post_comments": "PostComment"
            }
            if t_name in mapping:
                return mapping[t_name]
            return "".join(part.capitalize() for part in t_name.split("_"))

        # Fetch index and constraint details for checking uniqueness
        indexes = self.get_indexes(table_name)
        constraints = self.get_constraints(table_name)
        
        # Outgoing foreign keys (Many-to-One or One-to-One)
        for fk in all_fks:
            if fk["source_table"] == table_name:
                col = fk["source_column"]
                target_table = fk["target_table"]
                
                # Determine if col has a unique constraint or index
                is_unique = False
                if col in indexes and any(idx["is_unique"] for idx in indexes[col]):
                    is_unique = True
                if col in constraints and any(c["type"] == "UNIQUE" for c in constraints[col]):
                    is_unique = True
                
                rel_type = "one-to-one" if is_unique else "many-to-one"
                
                # Name the relation: e.g. "author_id" -> "author"
                rel_name = col
                if rel_name.endswith("_id"):
                    rel_name = rel_name[:-3]
                
                relations.append({
                    "name": rel_name,
                    "type": "relation",
                    "kind": "relation",
                    "relatedModel": table_to_model_name(target_table),
                    "relationType": rel_type
                })
                
            elif fk["target_table"] == table_name:
                # Incoming foreign keys (One-to-Many or One-to-One reverse)
                source_table = fk["source_table"]
                source_col = fk["source_column"]
                
                # Need to check uniqueness of source column on source table
                src_indexes = self.get_indexes(source_table)
                src_constraints = self.get_constraints(source_table)
                
                is_unique = False
                if source_col in src_indexes and any(idx["is_unique"] for idx in src_indexes[source_col]):
                    is_unique = True
                if source_col in src_constraints and any(c["type"] == "UNIQUE" for c in src_constraints[source_col]):
                    is_unique = True
                
                if is_unique:
                    rel_type = "one-to-one"
                    # Name reverse: e.g. "profile"
                    rel_name = source_table
                    if rel_name.startswith("user_"):
                        rel_name = rel_name[5:]
                    if rel_name.endswith("s") and not rel_name.endswith("ss"):
                        rel_name = rel_name[:-1]
                else:
                    rel_type = "one-to-many"
                    # Name reverse: e.g. "posts", "comments"
                    rel_name = source_table
                    if rel_name == "blog_posts":
                        rel_name = "posts"
                    elif rel_name == "post_comments":
                        rel_name = "comments"
                    elif rel_name == "user_profiles":
                        rel_name = "profiles"
                
                relations.append({
                    "name": rel_name,
                    "type": "relation",
                    "kind": "relation",
                    "relatedModel": table_to_model_name(source_table),
                    "relationType": rel_type
                })
                
        return relations

    def get_row_estimate(self, table_name):
        """
        Fetches the estimated row count for the table from pg_class.reltuples.
        """
        query = "SELECT reltuples FROM pg_class WHERE relname = %s;"
        try:
            self.cursor.execute(query, [table_name])
            row = self.cursor.fetchone()
            if row:
                # reltuples is a float/real in pg, cast to int
                val = int(row[0])
                # sometimes un-analyzed tables can show -1
                return max(0, val)
            return 0
        except Exception as e:
            logger.error("get_row_estimate_failed", table_name=table_name, error=str(e))
            return 0

    def close(self):
        self.cursor.close()
