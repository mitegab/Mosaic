# Mosaic Core Engine

Mosaic Core is a high-performance Django + Django REST Framework + PostgreSQL engine exposing structured query catalogs, dynamic database schemas, execution telemetries, and ORM translations (Django ORM, SQLAlchemy, and Prisma syntax) to the "Mosaic Studio GUI".

## 🛠️ Technology Stack
- **Core:** Python 3.14.5 + Django 5.2.14 + Django REST Framework 3.17.1
- **Database:** PostgreSQL 18 with Advanced Introspection (JSONB, GIN, BTree Indexing)
- **Validation:** Pydantic v2
- **Testing:** PyTest + pytest-django + factory_boy
- **Logging & Monitoring:** Python logging + structlog + Django Debug Toolbar (dev)

## 💾 Database Setup
The database runs on local PostgreSQL 18.
- Database name: `mosaic_db`
- Connection URL: `postgres://postgres:123@localhost:5432/mosaic_db`

To run database migrations:
```bash
python manage.py migrate
```
Migrations have been successfully initialized and applied to the database.

To seed the database with mock data:
```bash
python manage.py seed_db
```
The database has been successfully seeded with 25 users, 50 blog posts (with JSONB meta), and 120 comments for rich visual telemetry demonstrate.

