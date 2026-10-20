"""Database configuration shared by the application and migration commands."""
import os
import re
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parent.parent


def database_settings():
    environment = os.getenv('UDHAAR_ENV', 'development')
    if environment not in {'development', 'staging', 'production'}:
        raise ValueError('UDHAAR_ENV must be development, staging, or production')
    value = os.getenv('UDHAAR_DATABASE_URL', '')
    if not value:
        if environment != 'development':
            raise ValueError('Set UDHAAR_DATABASE_URL for hosted environments')
        value = f'sqlite:///{ROOT / "udhaar.sqlite3"}'
    try:
        url = make_url(value)
    except Exception:
        raise ValueError('Invalid database URL; URL-encode special characters in the password') from None
    if url.drivername in {'postgres', 'postgresql'}:
        url = url.set(drivername='postgresql+psycopg')
    if url.drivername not in {'sqlite', 'postgresql+psycopg'}:
        raise ValueError('Use SQLite locally or PostgreSQL with the psycopg driver')
    schema = os.getenv('UDHAAR_DATABASE_SCHEMA', 'public')
    if (not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', schema)
            or schema.startswith(('pg_', 'supabase'))
            or schema in {'auth', 'storage', 'extensions', 'vault', 'graphql', 'graphql_public', 'information_schema'}):
        raise ValueError('Use a dedicated application schema such as udhaar')
    hosted = environment in {'staging', 'production'}
    supabase = bool(url.host and (url.host.endswith('.supabase.co') or url.host.endswith('.supabase.com')))
    if hosted and (url.drivername != 'postgresql+psycopg' or schema == 'public'):
        raise ValueError('Hosted environments require PostgreSQL and a private application schema')
    if (hosted or supabase) and url.query.get('sslmode') not in {'require', 'verify-ca', 'verify-full'}:
        raise ValueError('Hosted PostgreSQL requires sslmode=require or certificate verification')
    if supabase and url.port == 6543:
        raise ValueError('Use the Supabase Session pooler on port 5432 for this deployment')
    if environment == 'production':
        if os.getenv('UDHAAR_COOKIE_SECURE') != 'true' or os.getenv('UDHAAR_AUTH_PROVIDER') != 'supabase':
            raise ValueError('Production requires secure cookies and Supabase authentication')
    return url, schema if url.drivername != 'sqlite' else None


def database_engine(url, schema=None):
    if url.drivername == 'sqlite':
        return create_engine(url, connect_args={'check_same_thread': False}, pool_pre_ping=True)
    result = create_engine(url, pool_pre_ping=True, pool_size=3, max_overflow=2,
                           pool_timeout=10, connect_args={'connect_timeout': 10})
    # Qualify every ORM table reference. Do not depend on a pooled search_path.
    return result.execution_options(schema_translate_map={None: schema or 'public'})


DATABASE_URL, DATABASE_SCHEMA = database_settings()
engine = database_engine(DATABASE_URL, DATABASE_SCHEMA)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
