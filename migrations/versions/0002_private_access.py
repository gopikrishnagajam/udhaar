"""Restrict direct Data API access to backend-owned application tables."""
from alembic import op
import sqlalchemy as sa

revision = '0002_private_access'
down_revision = '0001_initial'
branch_labels = None
depends_on = None

TABLES = ('users', 'auth_identities', 'login_sessions', 'contacts', 'records',
          'item_loans', 'invitations', 'item_returns', 'record_events', 'alembic_version')


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name != 'postgresql':
        return
    schema = op.get_context().config.attributes.get('database_schema') or 'public'
    quote = connection.dialect.identifier_preparer.quote_identifier
    roles = ['PUBLIC'] + [quote(role) for role in ('anon', 'authenticated', 'service_role')
        if connection.scalar(sa.text('SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=:role)'), {'role': role})]
    principals = ', '.join(roles)
    if schema != 'public':
        connection.exec_driver_sql(f'REVOKE ALL ON SCHEMA {quote(schema)} FROM {principals}')
    for table in TABLES:
        name = f'{quote(schema)}.{quote(table)}'
        connection.exec_driver_sql(f'REVOKE ALL ON TABLE {name} FROM {principals}')
        connection.exec_driver_sql(f'ALTER TABLE {name} ENABLE ROW LEVEL SECURITY')
    # The table owner (backend connection) can still operate on its own tables.
    # No policies grant browser/Supabase API roles access to these tables.


def downgrade():
    raise RuntimeError('Security restrictions are not automatically removed by a downgrade')
