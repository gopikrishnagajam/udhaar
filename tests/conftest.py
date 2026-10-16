"""Database-isolated API fixtures, supporting SQLite and local PostgreSQL."""
import os
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema
from backend.main import app, get_db
from backend.models import Base

@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('UDHAAR_AUTH_PROVIDER', 'local')
    test_url = os.getenv('TEST_DATABASE_URL')
    schema = None
    if test_url:
        engine = create_engine(test_url)
        assert engine.dialect.name == 'postgresql', 'TEST_DATABASE_URL must use PostgreSQL'
        schema = 'test_' + uuid.uuid4().hex
        with engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        engine = engine.execution_options(schema_translate_map={None: schema})
    else:
        engine = create_engine(f'sqlite:///{tmp_path / "test.sqlite3"}', connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
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
