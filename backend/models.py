"""Udhaar schema. Common records can support future MoneyLoan rows."""
import uuid
from datetime import date, datetime, timezone
from sqlalchemy import String, Integer, ForeignKey, Date, DateTime, Text, CheckConstraint, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .database import DATABASE_URL, engine, SessionLocal

def uid():
    return str(uuid.uuid4())

def now():
    return datetime.now(timezone.utc)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)

class LoginSession(Base):
    __tablename__ = 'login_sessions'
    id_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class AuthIdentity(Base):
    """Provider identities map to local profiles; tokens are never stored here."""
    __tablename__ = 'auth_identities'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    __table_args__ = (UniqueConstraint('issuer', 'subject', name='auth_identity_issuer_subject'),)

class Contact(Base):
    __tablename__ = 'contacts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

class Record(Base):
    __tablename__ = 'records'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True, nullable=False)
    contact_id: Mapped[str] = mapped_column(ForeignKey('contacts.id'), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default='ITEM', nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)  # LENT/BORROWED relative to owner
    mode: Mapped[str] = mapped_column(String(16), default='OFF', nullable=False)  # OFF/ON
    acknowledgment: Mapped[str] = mapped_column(String(16), default='NONE', nullable=False)
    loan_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    due_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default='', nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    contact: Mapped[Contact] = relationship()
    item: Mapped['ItemLoan'] = relationship(back_populates='record', uselist=False, cascade='all,delete-orphan')
    returns: Mapped[list['ItemReturn']] = relationship(back_populates='record', cascade='all,delete-orphan')
    events: Mapped[list['RecordEvent']] = relationship(back_populates='record', cascade='all,delete-orphan')

class ItemLoan(Base):
    __tablename__ = 'item_loans'
    record_id: Mapped[str] = mapped_column(ForeignKey('records.id', ondelete='CASCADE'), primary_key=True)
    item_name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(80), default='Other', nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    record: Mapped[Record] = relationship(back_populates='item')
    __table_args__ = (CheckConstraint('quantity > 0', name='item_quantity_positive'),)

class Invitation(Base):
    __tablename__ = 'invitations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    record_id: Mapped[str] = mapped_column(ForeignKey('records.id'), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    state: Mapped[str] = mapped_column(String(20), default='PENDING', nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recipient_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipient_user_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'), index=True, nullable=True)
    delivery: Mapped[str] = mapped_column(String(16), default='LINK', nullable=False)

class AppInvitation(Base):
    """Two durable delivery slots per sender per UTC calendar day."""
    __tablename__ = 'app_invitations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    sender_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    invite_day: Mapped[date] = mapped_column(Date, nullable=False)
    slot: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), default='RESERVED', nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    __table_args__ = (
        UniqueConstraint('sender_id', 'invite_day', 'slot', name='app_invite_daily_slot'),
        CheckConstraint('slot IN (1, 2)', name='app_invite_slot_limit'),
    )

class ItemReturn(Base):
    __tablename__ = 'item_returns'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    record_id: Mapped[str] = mapped_column(ForeignKey('records.id'), index=True, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # PENDING/CONFIRMED/CANCELLED
    proposed_by: Mapped[str] = mapped_column(String(16), nullable=False)  # OWNER/GUEST
    confirmed_by: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    record: Mapped[Record] = relationship(back_populates='returns')
    __table_args__ = (CheckConstraint('quantity > 0', name='return_quantity_positive'),)

class RecordEvent(Base):
    __tablename__ = 'record_events'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    record_id: Mapped[str] = mapped_column(ForeignKey('records.id'), index=True, nullable=False)
    actor: Mapped[str] = mapped_column(String(16), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    record: Mapped[Record] = relationship(back_populates='events')
