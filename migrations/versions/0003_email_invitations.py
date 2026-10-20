"""Email invitations, account recipients, and durable daily app-invite slots."""
from alembic import op
import sqlalchemy as sa

revision = '0003_email_invitations'
down_revision = '0002_private_access'
branch_labels = None
depends_on = None


def upgrade():
    schema = op.get_context().config.attributes.get('database_schema')
    with op.batch_alter_table('invitations', schema=schema) as batch:
        batch.add_column(sa.Column('recipient_email', sa.String(255)))
        batch.add_column(sa.Column('recipient_user_id', sa.String(36)))
        batch.add_column(sa.Column('delivery', sa.String(16), nullable=False, server_default='LINK'))
        batch.create_foreign_key('invitation_recipient_user', 'users', ['recipient_user_id'], ['id'], referent_schema=schema)
        batch.create_index('ix_invitations_recipient_user_id', ['recipient_user_id'])
    with op.batch_alter_table('invitations', schema=schema) as batch:
        batch.alter_column('delivery', existing_type=sa.String(16), server_default=None)
    op.create_table('app_invitations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('sender_id', sa.String(36), sa.ForeignKey(f'{schema}.users.id' if schema else 'users.id'), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('invite_day', sa.Date(), nullable=False),
        sa.Column('slot', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('message_id', sa.String(255)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('sender_id', 'invite_day', 'slot', name='app_invite_daily_slot'),
        sa.CheckConstraint('slot IN (1, 2)', name='app_invite_slot_limit'), schema=schema)
    op.create_index('ix_app_invitations_sender_id', 'app_invitations', ['sender_id'], schema=schema)
    connection = op.get_bind()
    if connection.dialect.name == 'postgresql':
        quote = connection.dialect.identifier_preparer.quote_identifier
        name = f'{quote(schema or "public")}.{quote("app_invitations")}'
        roles = ['PUBLIC'] + [quote(role) for role in ('anon', 'authenticated', 'service_role')
            if connection.scalar(sa.text('SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=:role)'), {'role': role})]
        connection.exec_driver_sql(f'REVOKE ALL ON TABLE {name} FROM {", ".join(roles)}')
        connection.exec_driver_sql(f'ALTER TABLE {name} ENABLE ROW LEVEL SECURITY')


def downgrade():
    raise RuntimeError('Email invitations contain delivery history; restore a backup to downgrade')
