"""Database-isolated API fixtures, supporting SQLite and local PostgreSQL."""
import os
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema
from backend.main import app, get_db
from backend.models import Base
from backend import main
from backend.migrate import upgrade_database, ensure_database_current

@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('UDHAAR_AUTH_PROVIDER', 'local')
    test_url = os.getenv('TEST_DATABASE_URL')
    schema = None
    if test_url:
        parsed_url = make_url(test_url)
        assert parsed_url.get_backend_name() in {'postgres', 'postgresql'}, 'TEST_DATABASE_URL must use PostgreSQL'
        engine = create_engine(parsed_url.set(drivername='postgresql+psycopg'))
        schema = 'test_' + uuid.uuid4().hex
        with engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        engine = engine.execution_options(schema_translate_map={None: schema})
    else:
        engine = create_engine(f'sqlite:///{tmp_path / "test.sqlite3"}', connect_args={'check_same_thread':False})
    upgrade_database(engine, schema)
    monkeypatch.setattr(main, 'ensure_database_current', lambda: ensure_database_current(engine, schema))
    sf = sessionmaker(bind=engine, expire_on_commit=False)
    def db():
        with sf() as session:
            yield session
    app.dependency_overrides[get_db] = db
    try:
        with TestClient(app) as owner, TestClient(app) as guest, TestClient(app) as stranger:
            owner.get('/api/csrf')
            guest.get('/api/csrf')
            stranger.get('/api/csrf')
            yield owner, guest, stranger
    finally:
        app.dependency_overrides.clear()
        if schema:
            with engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()
