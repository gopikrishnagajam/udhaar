"""Configuration, real DDL, legacy adoption, and PostgreSQL access boundaries."""
import os
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from backend.database import database_engine, database_settings
from backend.migrate import (baseline_database, ensure_database_current,
                             schema_differences, upgrade_database)
from backend.models import Base, User, Invitation, AppInvitation
from alembic import command
from backend.migrate import configuration
from alembic.script import ScriptDirectory


def create_original_schema(engine):
    frozen = ScriptDirectory.from_config(configuration()).get_revision('0001_initial').module.initial_metadata()
    frozen.create_all(engine)


@pytest.fixture
def database_config(monkeypatch):
    for key in ('UDHAAR_DATABASE_URL', 'UDHAAR_DATABASE_SCHEMA', 'UDHAAR_ENV',
                'UDHAAR_COOKIE_SECURE', 'UDHAAR_AUTH_PROVIDER'):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_supabase_url_normalization_and_encoded_password(database_config):
    database_config.setenv('UDHAAR_DATABASE_URL', 'postgresql://postgres.project:p%40ss%23word@aws-0-test.pooler.supabase.com:5432/postgres?sslmode=require')
    database_config.setenv('UDHAAR_DATABASE_SCHEMA', 'udhaar')
    database_config.setenv('UDHAAR_ENV', 'staging')
    url, schema = database_settings()
    assert url.drivername == 'postgresql+psycopg'
    assert url.password == 'p@ss#word'
    assert schema == 'udhaar'


@pytest.mark.parametrize('changes', [
    {'UDHAAR_ENV': 'staging'},
    {'UDHAAR_ENV': 'production'},
    {'UDHAAR_ENV': 'typo'},
    {'UDHAAR_DATABASE_SCHEMA': 'auth'},
    {'UDHAAR_DATABASE_SCHEMA': 'storage'},
    {'UDHAAR_DATABASE_SCHEMA': 'udhaar;drop schema auth'},
    {'UDHAAR_DATABASE_URL': 'mysql://user:secret@localhost/db'},
    {'UDHAAR_DATABASE_URL': 'postgresql://user:secret@db.project.supabase.co/db'},
    {'UDHAAR_DATABASE_URL': 'postgresql://user:secret@host.pooler.supabase.com:6543/db?sslmode=require'},
    {'UDHAAR_ENV': 'staging', 'UDHAAR_DATABASE_URL': 'postgresql://user:secret@localhost/db?sslmode=require'},
    {'UDHAAR_ENV': 'staging', 'UDHAAR_DATABASE_SCHEMA': 'udhaar', 'UDHAAR_DATABASE_URL': 'postgresql://user:secret@localhost/db'},
    {'UDHAAR_ENV': 'production', 'UDHAAR_DATABASE_SCHEMA': 'udhaar', 'UDHAAR_DATABASE_URL': 'postgresql://user:secret@localhost/db?sslmode=require'},
])
def test_unsafe_database_configuration_fails_without_exposing_password(database_config, changes):
    for key, value in changes.items():
        database_config.setenv(key, value)
    with pytest.raises(ValueError) as error:
        database_settings()
    assert 'secret' not in str(error.value)


def test_production_accepts_explicit_secure_configuration(database_config):
    for key, value in {'UDHAAR_ENV': 'production', 'UDHAAR_DATABASE_SCHEMA': 'udhaar',
                       'UDHAAR_DATABASE_URL': 'postgresql://user:secret@localhost/db?sslmode=require',
                       'UDHAAR_COOKIE_SECURE': 'true', 'UDHAAR_AUTH_PROVIDER': 'supabase'}.items():
        database_config.setenv(key, value)
    assert database_settings()[1] == 'udhaar'


@pytest.fixture
def isolated_database(tmp_path):
    url = os.getenv('TEST_DATABASE_URL')
    schema = None
    if url:
        schema = 'migration_' + uuid4().hex
        engine = database_engine(make_url(url).set(drivername='postgresql+psycopg'), schema)
        with engine.begin() as connection:
            connection.execute(sa.schema.CreateSchema(schema))
    else:
        engine = database_engine(make_url(f'sqlite:///{tmp_path / "migrations.sqlite3"}'))
    try:
        yield engine, schema
    finally:
        if schema:
            with engine.begin() as connection:
                connection.execute(sa.schema.DropSchema(schema, cascade=True))
        engine.dispose()


def test_fresh_migrations_match_models_and_repeat_without_losing_data(isolated_database):
    engine, schema = isolated_database
    with pytest.raises(RuntimeError, match='migrations are missing'):
        ensure_database_current(engine, schema)
    upgrade_database(engine, schema)
    with engine.begin() as connection:
        connection.execute(sa.insert(User).values(id=str(uuid4()), name='Preserved', email='preserved@example.com', password_hash=''))
        assert schema_differences(connection, schema) == []
    upgrade_database(engine, schema)
    ensure_database_current(engine, schema)
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(User)) == 1


def test_email_upgrade_preserves_existing_loans_and_guest_links(isolated_database):
    engine, schema = isolated_database
    instant = datetime.now(timezone.utc)
    user_id, contact_id, record_id, invitation_id = [str(uuid4()) for _ in range(4)]
    token_hash = hashlib.sha256(b'existing-private-link').hexdigest()
    frozen = ScriptDirectory.from_config(configuration()).get_revision('0001_initial').module.initial_metadata()
    with engine.begin() as connection:
        command.upgrade(configuration(connection, schema), '0002_private_access')
        connection.execute(frozen.tables['users'].insert().values(id=user_id, name='Existing', email='old@example.com', password_hash='', created_at=instant))
        connection.execute(frozen.tables['contacts'].insert().values(id=contact_id, owner_id=user_id, name='Guest'))
        connection.execute(frozen.tables['records'].insert().values(id=record_id, owner_id=user_id,
            contact_id=contact_id, kind='ITEM', direction='LENT', mode='ON', acknowledgment='PENDING',
            loan_date=instant.date(), notes='Private', created_at=instant, updated_at=instant))
        connection.execute(frozen.tables['item_loans'].insert().values(record_id=record_id, item_name='Existing book', category='Books', quantity=1))
        connection.execute(frozen.tables['invitations'].insert().values(id=invitation_id, record_id=record_id,
            token_hash=token_hash, state='PENDING', expires_at=instant+timedelta(days=30), created_at=instant))
    upgrade_database(engine, schema)
    with engine.connect() as connection:
        inv = connection.execute(sa.select(Invitation.__table__)).mappings().one()
        assert inv['token_hash'] == token_hash and inv['state'] == 'PENDING'
        assert inv['delivery'] == 'LINK' and inv['recipient_user_id'] is None
        assert schema_differences(connection, schema) == []


def test_existing_database_baseline_preserves_users_and_requires_explicit_adoption(isolated_database):
    engine, schema = isolated_database
    create_original_schema(engine)
    with engine.begin() as connection:
        connection.execute(sa.insert(User).values(id=str(uuid4()), name='Existing', email='existing@example.com', password_hash=''))
    with pytest.raises(RuntimeError, match='unversioned'):
        upgrade_database(engine, schema)
    baseline_database(engine, schema)
    upgrade_database(engine, schema)
    ensure_database_current(engine, schema)
    with engine.connect() as connection:
        assert connection.scalar(sa.select(User.name)) == 'Existing'
        assert schema_differences(connection, schema) == []


def test_partial_schema_cannot_be_baselined(isolated_database):
    engine, schema = isolated_database
    User.__table__.create(engine)
    with pytest.raises(RuntimeError, match='all nine'):
        baseline_database(engine, schema)
    with engine.connect() as connection:
        assert 'alembic_version' not in sa.inspect(connection).get_table_names(schema=schema)


def test_schema_drift_is_refused_without_stamping(isolated_database):
    engine, schema = isolated_database
    create_original_schema(engine)
    with engine.begin() as connection:
        quote = connection.dialect.identifier_preparer.quote_identifier
        name = f'{quote(schema)}.users' if schema else 'users'
        connection.exec_driver_sql(f'ALTER TABLE {name} ADD COLUMN unexpected_column INTEGER')
    with pytest.raises(RuntimeError, match='do not match'):
        baseline_database(engine, schema)
    with engine.connect() as connection:
        assert 'alembic_version' not in sa.inspect(connection).get_table_names(schema=schema)
        assert any(column['name'] == 'unexpected_column' for column in sa.inspect(connection).get_columns('users', schema=schema))


def test_postgres_migrations_do_not_touch_other_schemas(isolated_database):
    engine, schema = isolated_database
    if engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL schemas required')
    other = 'unrelated_' + uuid4().hex
    try:
        with engine.begin() as connection:
            connection.execute(sa.schema.CreateSchema(other))
            connection.exec_driver_sql(f'CREATE TABLE "{other}".users (message text)')
            connection.exec_driver_sql(f'INSERT INTO "{other}".users VALUES (\'untouched\')')
        upgrade_database(engine, schema)
        with engine.connect() as connection:
            assert connection.exec_driver_sql(f'SELECT message FROM "{other}".users').scalar_one() == 'untouched'
            assert schema_differences(connection, schema) == []
    finally:
        with engine.begin() as connection:
            connection.execute(sa.schema.DropSchema(other, cascade=True))


def test_postgres_rls_hides_rows_from_non_owner_roles(isolated_database):
    engine, schema = isolated_database
    if engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL roles required')
    upgrade_database(engine, schema)
    role = 'audit_' + uuid4().hex
    try:
        with engine.begin() as connection:
            connection.execute(sa.insert(User).values(id=str(uuid4()), name='Private', email='private@example.com', password_hash=''))
            enabled = connection.execute(sa.text('SELECT c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:schema AND c.relname=:table'), {'schema': schema, 'table': 'users'}).scalar_one()
            assert enabled is True
            connection.exec_driver_sql(f'CREATE ROLE "{role}" NOLOGIN')
            connection.exec_driver_sql(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"')
            connection.exec_driver_sql(f'GRANT SELECT ON "{schema}".users TO "{role}"')
            user_id = connection.scalar(sa.select(User.id))
            connection.execute(sa.insert(AppInvitation).values(id=str(uuid4()), sender_id=user_id,
                email='private-recipient@example.com', invite_day=datetime.now(timezone.utc).date(), slot=1, state='SENT'))
            connection.exec_driver_sql(f'GRANT SELECT ON "{schema}".app_invitations TO "{role}"')
        with engine.begin() as connection:
            connection.exec_driver_sql(f'SET LOCAL ROLE "{role}"')
            assert connection.exec_driver_sql(f'SELECT count(*) FROM "{schema}".users').scalar_one() == 0
            assert connection.exec_driver_sql(f'SELECT count(*) FROM "{schema}".app_invitations').scalar_one() == 0
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'REVOKE ALL ON "{schema}".users FROM "{role}"')
            connection.exec_driver_sql(f'REVOKE ALL ON "{schema}".app_invitations FROM "{role}"')
            connection.exec_driver_sql(f'REVOKE ALL ON SCHEMA "{schema}" FROM "{role}"')
            connection.exec_driver_sql(f'DROP ROLE IF EXISTS "{role}"')
