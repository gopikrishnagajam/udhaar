"""Explicit, schema-scoped upgrades and safe adoption of legacy databases.

Run: python -m backend.migrate upgrade|baseline|check|current
"""
import argparse
import hashlib
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.exc import SQLAlchemyError

from .database import DATABASE_SCHEMA, engine
from .models import Base

ROOT = Path(__file__).resolve().parent.parent
INITIAL = '0001_initial'
TABLES = frozenset(Base.metadata.tables)


def configuration(connection=None, schema=None):
    config = Config(str(ROOT / 'alembic.ini'))
    config.attributes['connection'] = connection
    config.attributes['database_schema'] = schema
    return config


def migration_metadata(schema):
    # PostgreSQL reflection represents its default public schema as None.
    schema = None if schema == 'public' else schema
    metadata = sa.MetaData(naming_convention={'ix': 'ix_%(table_name)s_%(column_0_name)s'})
    for table in Base.metadata.sorted_tables:
        table.to_metadata(metadata, schema=schema)
    return metadata


def migration_options(schema):
    def include_name(name, kind, parent_names):
        if kind == 'schema':
            return name == schema or (name is None and schema in {None, 'public'})
        return kind != 'table' or name in TABLES
    return {'version_table_schema': schema, 'include_schemas': schema is not None,
            'include_name': include_name, 'compare_type': True, 'compare_server_default': True}


def lock_migrations(connection, schema):
    if connection.dialect.name == 'postgresql':
        # Transaction-scoped and per schema: concurrent deploys cannot race DDL.
        value = int.from_bytes(hashlib.sha256(f'udhaar-migrations:{schema}'.encode()).digest()[:8], signed=True)
        connection.execute(sa.text('SELECT pg_advisory_xact_lock(:value)'), {'value': value})


def schema_differences(connection, schema, metadata=None):
    context = MigrationContext.configure(connection, opts=migration_options(schema))
    return compare_metadata(context, metadata if metadata is not None else migration_metadata(schema))


def upgrade_database(database_engine=engine, schema=DATABASE_SCHEMA):
    with database_engine.begin() as connection:
        lock_migrations(connection, schema)
        if schema and connection.dialect.name == 'postgresql':
            connection.execute(sa.schema.CreateSchema(schema, if_not_exists=True))
        tables = set(sa.inspect(connection).get_table_names(schema=schema))
        if TABLES & tables and 'alembic_version' not in tables:
            raise RuntimeError('Existing unversioned Udhaar tables found. Back up the database, then run python -m backend.migrate baseline')
        command.upgrade(configuration(connection, schema), 'head')


def baseline_database(database_engine=engine, schema=DATABASE_SCHEMA):
    """Stamp only a complete, matching historical baseline; never recreate data."""
    with database_engine.begin() as connection:
        lock_migrations(connection, schema)
        tables = set(sa.inspect(connection).get_table_names(schema=schema))
        if 'alembic_version' in tables:
            raise RuntimeError('This database is already versioned; use upgrade instead')
        if not TABLES.issubset(tables):
            raise RuntimeError('Baseline requires all nine original Udhaar tables; no changes were applied')
        config = configuration(connection, schema)
        frozen = ScriptDirectory.from_config(config).get_revision(INITIAL).module.initial_metadata(None if schema == 'public' else schema)
        if schema_differences(connection, schema, frozen):
            raise RuntimeError('Existing tables do not match the original schema; baseline refused without changing data')
        command.stamp(config, INITIAL)


def ensure_database_current(database_engine=engine, schema=DATABASE_SCHEMA):
    """Read-only startup check. Schema changes belong to the release step."""
    try:
        with database_engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={'version_table_schema': schema})
            expected = set(ScriptDirectory.from_config(configuration()).get_heads())
            if set(context.get_current_heads()) != expected:
                raise RuntimeError('Database migrations are missing. Run python -m backend.migrate upgrade before starting the app')
            if not TABLES.issubset(sa.inspect(connection).get_table_names(schema=schema)):
                raise RuntimeError('Application tables are missing; check the configured database schema')
    except SQLAlchemyError:
        raise RuntimeError('Database unavailable. Check the database connection, TLS, network access, and credentials') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('upgrade', 'baseline', 'check', 'current'))
    action = parser.parse_args().action
    try:
        if action == 'upgrade':
            upgrade_database()
            print('Database migrations applied successfully')
        elif action == 'baseline':
            baseline_database()
            print('Existing database verified and baselined; run upgrade next')
        elif action == 'check':
            ensure_database_current()
            with engine.connect() as connection:
                if schema_differences(connection, DATABASE_SCHEMA):
                    raise RuntimeError('Database schema differs from the application models')
            print('Database revision and schema match the application')
        else:
            with engine.connect() as connection:
                context = MigrationContext.configure(connection, opts={'version_table_schema': DATABASE_SCHEMA})
                print('Database revision:', ', '.join(context.get_current_heads()) or 'unversioned')
    except (SQLAlchemyError, RuntimeError) as error:
        # Driver errors may contain connection details or SQL parameters.
        message = str(error) if isinstance(error, RuntimeError) else 'Database operation failed; check connection settings and database permissions'
        parser.exit(1, message + '\n')
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
