"""Frozen baseline of the original nine application tables."""
from alembic import op
import sqlalchemy as sa

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def initial_metadata(schema=None):
    # Frozen definitions: do not import live ORM models into a historical revision.
    metadata = sa.MetaData(schema=schema, naming_convention={'ix': 'ix_%(table_name)s_%(column_0_name)s'})
    sa.Table('users', metadata,
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('email', sa.String(255), nullable=False, unique=True, index=True),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    sa.Table('login_sessions', metadata,
        sa.Column('id_hash', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False))
    sa.Table('auth_identities', metadata,
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('issuer', sa.String(255), nullable=False),
        sa.Column('subject', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('issuer', 'subject', name='auth_identity_issuer_subject'))
    sa.Table('contacts', metadata,
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('email', sa.String(255)))
    sa.Table('records', metadata,
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('contact_id', sa.String(36), sa.ForeignKey('contacts.id'), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('direction', sa.String(16), nullable=False),
        sa.Column('mode', sa.String(16), nullable=False),
        sa.Column('acknowledgment', sa.String(16), nullable=False),
        sa.Column('loan_date', sa.Date(), nullable=False),
        sa.Column('due_date', sa.Date()),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    sa.Table('item_loans', metadata,
        sa.Column('record_id', sa.String(36), sa.ForeignKey('records.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('item_name', sa.String(160), nullable=False),
        sa.Column('category', sa.String(80), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.CheckConstraint('quantity > 0', name='item_quantity_positive'))
    sa.Table('invitations', metadata,
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('record_id', sa.String(36), sa.ForeignKey('records.id'), nullable=False, index=True),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('state', sa.String(20), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('responded_at', sa.DateTime(timezone=True)))
    sa.Table('item_returns', metadata,
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('record_id', sa.String(36), sa.ForeignKey('records.id'), nullable=False, index=True),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('proposed_by', sa.String(16), nullable=False),
        sa.Column('confirmed_by', sa.String(16)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint('quantity > 0', name='return_quantity_positive'))
    sa.Table('record_events', metadata,
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('record_id', sa.String(36), sa.ForeignKey('records.id'), nullable=False, index=True),
        sa.Column('actor', sa.String(16), nullable=False),
        sa.Column('event_type', sa.String(40), nullable=False),
        sa.Column('description', sa.String(240), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    return metadata


def upgrade():
    schema = op.get_context().config.attributes.get('database_schema')
    initial_metadata(schema).create_all(op.get_bind(), checkfirst=False)


def downgrade():
    schema = op.get_context().config.attributes.get('database_schema')
    initial_metadata(schema).drop_all(op.get_bind(), checkfirst=False)
