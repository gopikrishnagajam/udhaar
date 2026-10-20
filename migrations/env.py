"""Migrate only Udhaar's configured schema; never Supabase-managed schemas."""
from alembic import context
from backend.migrate import migration_metadata, migration_options

config = context.config


def run(connection, schema):
    context.configure(connection=connection, target_metadata=migration_metadata(schema),
                      **migration_options(schema))
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError('Use python -m backend.migrate; offline migrations are not configured')
elif config.attributes.get('connection') is not None:
    run(config.attributes['connection'], config.attributes.get('database_schema'))
else:
    from backend.database import engine, DATABASE_SCHEMA
    with engine.begin() as connection:
        config.attributes['database_schema'] = DATABASE_SCHEMA
        run(connection, DATABASE_SCHEMA)
