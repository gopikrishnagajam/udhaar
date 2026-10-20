"""Udhaar MVP API and its zero-build frontend."""
import hashlib
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import FastAPI, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select, func, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from .models import Base, engine, SessionLocal, User, LoginSession, Contact, Record, ItemLoan, Invitation, ItemReturn, RecordEvent, AppInvitation, now
from . import supabase_auth, email_delivery, policies
from .migrate import ensure_database_current

@asynccontextmanager
async def lifespan(app):
    ensure_database_current()
    yield


app = FastAPI(title='Udhaar MVP', docs_url='/api/docs', openapi_url='/api/openapi.json', lifespan=lifespan)
ROOT = Path(__file__).resolve().parent.parent
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
app.include_router(policies.router)
ph = PasswordHasher()

class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=200)

    @field_validator('email')
    @classmethod
    def normalize_email(cls, value):
        if '@' not in value or value.startswith('@') or value.endswith('@'):
            raise ValueError('Enter a valid email')
        return value.strip().casefold()

class Register(Credentials):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        if not value.strip():
            raise ValueError("Name is required")
        return value.strip()

class RecordCreate(BaseModel):
    direction: Literal['LENT', 'BORROWED']
    mode: Literal['OFF', 'ON'] = 'OFF'
    contact_name: str = Field(min_length=1, max_length=100)
    contact_email: str | None = Field(default=None, max_length=255)
    item_name: str = Field(min_length=1, max_length=160)
    category: str = Field(default='Other', max_length=80)
    quantity: int = Field(default=1, ge=1, le=100000)
    loan_date: date
    due_date: date | None = None
    notes: str = Field(default='', max_length=2000)

    @field_validator('contact_email')
    @classmethod
    def valid_contact_email(cls, value):
        return email_delivery.normalize_email(value) if value else None

    @model_validator(mode='after')
    def check_dates(self):
        if self.mode == 'ON' and not self.contact_email:
            raise ValueError('An email address is required for On the Record')
        if self.due_date and self.due_date < self.loan_date:
            raise ValueError('Return date must be on or after the lending date')
        return self

class RecordEdit(BaseModel):
    item_name: str | None = Field(default=None, min_length=1, max_length=160)
    due_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)

class ShareResponse(BaseModel):
    accept: bool

class InviteEmail(BaseModel):
    email: str = Field(min_length=3, max_length=255)

    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        return email_delivery.normalize_email(value)

class QuantityBody(BaseModel):
    quantity: int = Field(ge=1, le=100000)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()

def utc(dt: datetime):
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

def auth_user(request: Request, db: Session = Depends(get_db)):
    if supabase_auth.provider() == 'supabase':
        return supabase_auth.authenticated_user(request, db)
    token = request.cookies.get('udhaar_session')
    if not token:
        raise HTTPException(401, 'Please sign in')
    session = db.get(LoginSession, digest(token))
    if not session or utc(session.expires_at) <= now():
        raise HTTPException(401, 'Session expired')
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, 'Account not found')
    return user

def require_csrf(request: Request, x_csrf_token: str | None = Header(None)):
    cookie = request.cookies.get('udhaar_csrf')
    if not cookie or not x_csrf_token or not secrets.compare_digest(cookie, x_csrf_token):
        raise HTTPException(403, 'Invalid CSRF token; refresh and retry')

app.include_router(supabase_auth.make_router(get_db, require_csrf))

def event(db: Session, rec: Record, actor: str, kind: str, description: str):
    db.add(RecordEvent(record_id=rec.id, actor=actor, event_type=kind, description=description))

def get_owned(db: Session, user: User, rid: str):
    rec = db.get(Record, rid)
    if not rec or rec.owner_id != user.id:
        raise HTTPException(404, 'Record not found')
    return rec

def summary(rec: Record):
    confirmed = sum(r.quantity for r in rec.returns if r.status == 'CONFIRMED')
    pending = sum(r.quantity for r in rec.returns if r.status == 'PENDING')
    left = rec.item.quantity - confirmed
    return {
        'id': rec.id, 'kind': rec.kind, 'direction': rec.direction, 'mode': rec.mode,
        'acknowledgment': rec.acknowledgment,
        'handover_acknowledgment': rec.acknowledgment,
        'return_acknowledgment': ('NOT_REQUIRED' if rec.mode == 'OFF' else
                                  'CONFIRMED' if left == 0 else
                                  'PENDING' if pending else
                                  'PARTIAL' if confirmed else 'NONE'),
        'contact_name': rec.contact.name, 'contact_email': rec.contact.email,
        'item_name': rec.item.item_name, 'category': rec.item.category, 'quantity': rec.item.quantity,
        'loan_date': rec.loan_date.isoformat(), 'due_date': rec.due_date.isoformat() if rec.due_date else None,
        'notes': rec.notes, 'returned_quantity': confirmed, 'pending_quantity': pending,
        'outstanding_quantity': left, 'settlement': 'RETURNED' if left == 0 else ('PARTIAL' if confirmed else 'OUTSTANDING'),
        'created_at': rec.created_at.isoformat(),
    }

def detail(rec: Record):
    result = summary(rec)
    result['returns'] = [
        {'id': r.id, 'quantity': r.quantity, 'status': r.status, 'proposed_by': r.proposed_by,
         'created_at': r.created_at.isoformat()} for r in sorted(rec.returns, key=lambda x: x.created_at, reverse=True)
    ]
    result['events'] = [
        {'type': e.event_type, 'actor': e.actor, 'description': e.description,
         'created_at': e.created_at.isoformat()} for e in sorted(rec.events, key=lambda x: x.created_at, reverse=True)
    ]
    return result

def invited(db: Session, token: str):
    inv = db.scalar(select(Invitation).where(Invitation.token_hash == digest(token)))
    if not inv or inv.delivery == 'IN_APP':
        raise HTTPException(404, 'Loan link unavailable or expired')
    return available_invitation(db, inv)


def available_invitation(db, inv):
    # Serialize handover responses and link replacement on the same loan row.
    rec = db.scalar(select(Record).where(Record.id == inv.record_id).with_for_update())
    db.refresh(inv)
    if inv.state not in {'PENDING', 'ACCEPTED'} or utc(inv.expires_at) <= now():
        raise HTTPException(404, 'Loan link unavailable or expired')
    if not rec or rec.mode != 'ON':
        raise HTTPException(404, 'Record unavailable')
    return inv, rec


def recipient_invitation(db, user, invitation_id):
    inv = db.scalar(select(Invitation).where(Invitation.id == invitation_id, Invitation.recipient_user_id == user.id))
    if not inv:
        raise HTTPException(404, 'Acknowledgment request not found')
    return available_invitation(db, inv)


def recipient_view(db, inv, rec):
    result = detail(rec)
    result.pop('notes', None)
    result.pop('events', None)
    result.pop('contact_email', None)
    result.update(owner_name=db.get(User, rec.owner_id).name, invitation_id=inv.id,
                  invitation_state=inv.state, link_expires_at=inv.expires_at.isoformat())
    return result


def deliver_record(db, rec, user, email):
    if email == user.email.casefold():
        raise HTTPException(422, 'Enter the other person\'s email address')
    recipient = db.scalar(select(User).where(func.lower(User.email) == email))
    for old in db.scalars(select(Invitation).where(Invitation.record_id == rec.id, Invitation.state.in_(['PENDING', 'ACCEPTED']))):
        old.state = 'REVOKED'
    raw = secrets.token_urlsafe(36)
    inv = Invitation(record_id=rec.id, token_hash=digest(raw), recipient_email=email,
                     recipient_user_id=recipient.id if recipient else None,
                     delivery='IN_APP' if recipient else 'EMAIL', expires_at=now() + timedelta(days=30))
    db.add(inv)
    rec.mode = 'ON'
    rec.acknowledgment = 'PENDING'
    event(db, rec, 'OWNER', 'INVITED', 'Acknowledgment requested in app' if recipient else 'Acknowledgment link emailed (identity unverified)')
    db.flush()
    path = f'/share/{raw}'
    if not recipient:
        url = email_delivery.public_url(path)
        signup_url = email_delivery.public_url('/signup')
        email_delivery.send_email(email, 'Please acknowledge an Udhaar loan',
            f'{user.name} has shared an item loan with you on Udhaar.\n\n'
            f'Review the loan and accept or decline here:\n{url}\n\n'
            'No account is needed. Keep this private link for return acknowledgments too. '
            'It expires in 30 days. Only acknowledge a loan you recognize.\n\n'
            f'Optional: create your own Udhaar account at {signup_url}', f'loan-invite/{inv.id}')
    return {'delivery': inv.delivery, 'expires_at': inv.expires_at.isoformat(), 'status': 'PENDING'}


def record_response(db, inv, rec, accept, authenticated=False):
    if inv.state != 'PENDING' or rec.acknowledgment != 'PENDING':
        raise HTTPException(409, 'Acknowledgment request already answered')
    inv.state = 'ACCEPTED' if accept else 'DECLINED'
    rec.acknowledgment = 'CONFIRMED' if accept else 'DECLINED'
    if accept:
        handover = 'Item taken / borrowed' if rec.direction == 'LENT' else 'Item given / lent'
        suffix = 'by signed-in recipient' if authenticated else 'through loan link (identity unverified)'
        event(db, rec, 'GUEST', 'ACKNOWLEDGED', f'{handover} acknowledged {suffix}')
    else:
        event(db, rec, 'GUEST', 'DECLINED', 'Recipient declined to acknowledge this record')
    inv.responded_at = now()
    db.commit()
    return {'acknowledgment': rec.acknowledgment}

def ensure_share_accepted(inv: Invitation, rec: Record):
    if inv.state != 'ACCEPTED' or rec.acknowledgment != 'CONFIRMED':
        raise HTTPException(409, 'Please acknowledge the record first')

def add_return(db: Session, rec: Record, qty: int, actor: str):
    if rec.mode == 'ON' and rec.acknowledgment != 'CONFIRMED':
        raise HTTPException(409, 'The other person must acknowledge this record first')
    reserved = sum(x.quantity for x in rec.returns if x.status in ('PENDING', 'CONFIRMED'))
    if qty > rec.item.quantity - reserved:
        raise HTTPException(409, 'Quantity exceeds available outstanding items or pending returns')
    lender = 'OWNER' if rec.direction == 'LENT' else 'GUEST'
    is_confirmed = rec.mode == 'OFF' or actor == lender
    item_return = ItemReturn(record_id=rec.id, quantity=qty, status='CONFIRMED' if is_confirmed else 'PENDING',
                             proposed_by=actor, confirmed_by=actor if is_confirmed else None,
                             confirmed_at=now() if is_confirmed else None)
    db.add(item_return)
    event(db, rec, actor, 'RETURN_CONFIRMED' if is_confirmed else 'RETURN_PROPOSED',
          f'Return acknowledged for {qty} item(s)' if is_confirmed else f'Return requested for {qty} item(s)')
    db.commit()
    return {'id': item_return.id, 'status': item_return.status}

def confirm_return(db: Session, rec: Record, r: ItemReturn, actor: str):
    lender = 'OWNER' if rec.direction == 'LENT' else 'GUEST'
    if actor != lender:
        raise HTTPException(403, 'Only the lender can confirm receipt')
    if r.status != 'PENDING':
        raise HTTPException(409, 'Return is not awaiting confirmation')
    r.status = 'CONFIRMED'
    r.confirmed_by = actor
    r.confirmed_at = now()
    event(db, rec, actor, 'RETURN_CONFIRMED', f'Return acknowledged for {r.quantity} item(s)')
    db.commit()
    return {'status': 'CONFIRMED'}

@app.middleware('http')
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Cache-Control'] = 'no-store'
    return response

@app.get('/api/csrf')
def csrf_cookie(request: Request, response: Response):
    token = request.cookies.get('udhaar_csrf') or secrets.token_urlsafe(32)
    response.set_cookie('udhaar_csrf', token, secure=(__import__('os').getenv('UDHAAR_COOKIE_SECURE') == 'true'),
                        samesite='lax', path='/', httponly=False)
    return {'csrf': token}

@app.get('/api/me')
def whoami(user: User = Depends(auth_user)):
    return {'id': user.id, 'name': user.name, 'email': user.email}


@app.get('/api/app-invites')
def app_invite_quota(user: User = Depends(auth_user), db: Session = Depends(get_db)):
    day = now().date()
    invitations = db.scalars(select(AppInvitation).where(AppInvitation.sender_id == user.id, AppInvitation.invite_day == day)
                             .order_by(AppInvitation.slot)).all()
    return {'limit': 2, 'remaining': 2 - len(invitations),
            'resets_at': datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).isoformat(),
            'invitations': [{'id': inv.id, 'email': inv.email, 'state': inv.state} for inv in invitations]}


def send_app_invitation(db, inv, user):
    # Commit the daily reservation BEFORE contacting Resend. Even a timeout or
    # process crash cannot release a slot and accidentally permit a third invite.
    try:
        inv.message_id = email_delivery.send_email(inv.email, 'You are invited to Udhaar',
            f'{user.name} invited you to Udhaar, a place to track the things you lend and borrow.\n\n'
            f'Create your account here:\n{email_delivery.public_url("/signup")}\n\n'
            'Joining is optional. You can ignore this invitation if you are not interested.', f'app-invite/{inv.id}')
    except HTTPException:
        inv.state = 'FAILED'
        db.commit()
        raise
    inv.state = 'SENT'
    db.commit()
    return {'id': inv.id, 'state': inv.state, 'message': 'Invitation sent'}


@app.post('/api/app-invites', dependencies=[Depends(require_csrf)])
def invite_to_app(body: InviteEmail, user: User = Depends(auth_user), db: Session = Depends(get_db)):
    email_delivery.public_url('/signup')
    if body.email == user.email.casefold():
        raise HTTPException(422, 'Enter someone else\'s email address')
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    day = now().date()
    existing = db.scalars(select(AppInvitation).where(AppInvitation.sender_id == user.id, AppInvitation.invite_day == day)).all()
    if any(inv.email == body.email for inv in existing):
        raise HTTPException(409, 'This email was already invited today. Retry its existing invitation if delivery failed')
    used = {inv.slot for inv in existing}
    slot = next((value for value in (1, 2) if value not in used), None)
    if slot is None:
        raise HTTPException(429, 'You have used your two app invitations today. The limit resets at midnight UTC')
    inv = AppInvitation(sender_id=user.id, email=body.email, invite_day=day, slot=slot)
    db.add(inv)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(429, 'Daily invitation slots changed. Refresh and try again') from None
    return send_app_invitation(db, inv, user)


@app.post('/api/app-invites/{invitation_id}/retry', dependencies=[Depends(require_csrf)])
def retry_app_invitation(invitation_id: str, user: User = Depends(auth_user), db: Session = Depends(get_db)):
    inv = db.scalar(select(AppInvitation).where(AppInvitation.id == invitation_id, AppInvitation.sender_id == user.id).with_for_update())
    if not inv:
        raise HTTPException(404, 'Invitation not found')
    if inv.state == 'SENT':
        return {'id': inv.id, 'state': inv.state, 'message': 'Invitation already sent'}
    # Resend retains idempotency keys for 24 hours. Never retry past that window.
    if utc(inv.created_at) + timedelta(hours=23) <= now():
        raise HTTPException(409, 'This delivery retry has expired. Send a new invitation using today\'s allowance')
    return send_app_invitation(db, inv, user)

def start_session(response: Response, db: Session, user: User):
    value = secrets.token_urlsafe(40)
    db.add(LoginSession(id_hash=digest(value), user_id=user.id, expires_at=now() + timedelta(days=14)))
    db.commit()
    response.set_cookie('udhaar_session', value, httponly=True, samesite='lax', path='/',
                        secure=(__import__('os').getenv('UDHAAR_COOKIE_SECURE') == 'true'), max_age=14*24*3600)

@app.post('/api/register', dependencies=[Depends(require_csrf)])
def register(data: Register, response: Response, db: Session = Depends(get_db)):
    if supabase_auth.provider() != 'local':
        raise HTTPException(403, 'Use email-code authentication')
    if db.scalar(select(User).where(User.email == data.email)):
        raise HTTPException(409, 'Email is already registered')
    user = User(name=data.name.strip(), email=data.email, password_hash=ph.hash(data.password))
    db.add(user)
    db.commit()
    start_session(response, db, user)
    return {'id': user.id, 'name': user.name, 'email': user.email}

@app.post('/api/login', dependencies=[Depends(require_csrf)])
def login(data: Credentials, response: Response, db: Session = Depends(get_db)):
    if supabase_auth.provider() != 'local':
        raise HTTPException(403, 'Use email-code authentication')
    user = db.scalar(select(User).where(User.email == data.email))
    try:
        if not user or not ph.verify(user.password_hash, data.password):
            raise HTTPException(401, 'Invalid email or password')
    except (VerifyMismatchError, VerificationError):
        raise HTTPException(401, 'Invalid email or password')
    start_session(response, db, user)
    return {'id': user.id, 'name': user.name, 'email': user.email}

@app.post('/api/logout', dependencies=[Depends(require_csrf)])
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    if supabase_auth.provider() == 'supabase':
        raise HTTPException(403, 'Use /api/auth/logout')
    value = request.cookies.get('udhaar_session')
    if value:
        row = db.get(LoginSession, digest(value))
        if row:
            db.delete(row)
            db.commit()
    response.delete_cookie('udhaar_session', path='/')
    return {'ok': True}

@app.get('/api/records')
def all_records(user: User = Depends(auth_user), db: Session = Depends(get_db)):
    records = db.scalars(select(Record).where(Record.owner_id == user.id).order_by(Record.created_at.desc())).all()
    return [summary(r) for r in records]

@app.post('/api/records', dependencies=[Depends(require_csrf)], status_code=201)
def create_record(body: RecordCreate, user: User = Depends(auth_user), db: Session = Depends(get_db)):
    name = body.contact_name.strip()
    item_name = body.item_name.strip()
    if not name or not item_name:
        raise HTTPException(422, 'Item and person names are required')
    contact_match = (func.lower(Contact.email) == body.contact_email if body.contact_email else
                     (Contact.name == name) & Contact.email.is_(None))
    contact = db.scalar(select(Contact).where(Contact.owner_id == user.id, contact_match))
    if not contact:
        contact = Contact(owner_id=user.id, name=name, email=body.contact_email)
        db.add(contact)
        db.flush()
    record = Record(owner_id=user.id, contact_id=contact.id, direction=body.direction,
                    mode=body.mode, acknowledgment='NONE', loan_date=body.loan_date,
                    due_date=body.due_date, notes=body.notes)
    record.item = ItemLoan(item_name=item_name, category=body.category or 'Other', quantity=body.quantity)
    db.add(record)
    db.flush()
    event(db, record, 'OWNER', 'CREATED', 'Personal record created' if body.mode == 'OFF' else 'Shared record drafted')
    delivery = deliver_record(db, record, user, body.contact_email) if body.mode == 'ON' else None
    db.commit()
    db.refresh(record)
    result = summary(record)
    if delivery:
        result['invitation_delivery'] = delivery['delivery']
    return result

@app.get('/api/records/{record_id}')
def record_details(record_id: str, user: User = Depends(auth_user), db: Session = Depends(get_db)):
    result = detail(get_owned(db, user, record_id))
    inv = db.scalar(select(Invitation).where(Invitation.record_id == record_id).order_by(Invitation.created_at.desc()))
    if inv:
        result.update(acknowledgment_email=inv.recipient_email, invitation_delivery=inv.delivery)
    return result

@app.patch('/api/records/{record_id}', dependencies=[Depends(require_csrf)])
def edit_record(record_id: str, body: RecordEdit, user: User = Depends(auth_user), db: Session = Depends(get_db)):
    rec = get_owned(db, user, record_id)
    if rec.mode == 'ON' and rec.acknowledgment != 'NONE':
        raise HTTPException(409, 'Shared records cannot be edited after sharing; create a new record for changed terms')
    if body.item_name is not None:
        if not body.item_name.strip():
            raise HTTPException(422, 'Item name cannot be blank')
        rec.item.item_name = body.item_name.strip()
    if 'due_date' in body.model_fields_set:
        if body.due_date and body.due_date < rec.loan_date:
            raise HTTPException(422, 'Due date cannot precede lending date')
        rec.due_date = body.due_date
    if body.notes is not None:
        rec.notes = body.notes
    event(db, rec, 'OWNER', 'UPDATED', 'Record updated')
    db.commit()
    return summary(rec)

@app.post('/api/records/{record_id}/share', dependencies=[Depends(require_csrf)])
def create_invitation(record_id: str, body: InviteEmail, user: User = Depends(auth_user), db: Session = Depends(get_db)):
    rec = get_owned(db, user, record_id)
    db.scalar(select(Record).where(Record.id == rec.id).with_for_update())
    if rec.returns and sum(r.quantity for r in rec.returns if r.status == 'CONFIRMED'):
        raise HTTPException(409, 'Already-returned records cannot be newly shared')
    delivery = deliver_record(db, rec, user, body.email)
    db.commit()
    return delivery


@app.get('/api/inbox')
def acknowledgment_inbox(user: User = Depends(auth_user), db: Session = Depends(get_db)):
    invitations = db.scalars(select(Invitation).where(Invitation.recipient_user_id == user.id,
        Invitation.state.in_(['PENDING', 'ACCEPTED']), Invitation.expires_at > now()).order_by(Invitation.created_at.desc())).all()
    return [recipient_view(db, inv, db.get(Record, inv.record_id)) for inv in invitations]


@app.get('/api/inbox/{invitation_id}')
def inbox_details(invitation_id: str, user: User = Depends(auth_user), db: Session = Depends(get_db)):
    inv, rec = recipient_invitation(db, user, invitation_id)
    return recipient_view(db, inv, rec)


@app.post('/api/inbox/{invitation_id}/respond', dependencies=[Depends(require_csrf)])
def inbox_respond(invitation_id: str, body: ShareResponse, user: User = Depends(auth_user), db: Session = Depends(get_db)):
    inv, rec = recipient_invitation(db, user, invitation_id)
    return record_response(db, inv, rec, body.accept, authenticated=True)


@app.post('/api/inbox/{invitation_id}/returns', dependencies=[Depends(require_csrf)])
def inbox_return(invitation_id: str, body: QuantityBody, user: User = Depends(auth_user), db: Session = Depends(get_db)):
    inv, rec = recipient_invitation(db, user, invitation_id)
    ensure_share_accepted(inv, rec)
    return add_return(db, rec, body.quantity, 'GUEST')


@app.post('/api/inbox/{invitation_id}/returns/{return_id}/confirm', dependencies=[Depends(require_csrf)])
def inbox_confirm(invitation_id: str, return_id: str, user: User = Depends(auth_user), db: Session = Depends(get_db)):
    inv, rec = recipient_invitation(db, user, invitation_id)
    ensure_share_accepted(inv, rec)
    item_return = db.get(ItemReturn, return_id)
    if not item_return or item_return.record_id != rec.id:
        raise HTTPException(404, 'Return not found')
    return confirm_return(db, rec, item_return, 'GUEST')

@app.post('/api/records/{record_id}/returns', dependencies=[Depends(require_csrf)])
def owner_return(record_id: str, body: QuantityBody, user: User = Depends(auth_user), db: Session = Depends(get_db)):
    rec = get_owned(db, user, record_id)
    return add_return(db, rec, body.quantity, 'OWNER')

@app.post('/api/records/{record_id}/returns/{return_id}/confirm', dependencies=[Depends(require_csrf)])
def owner_confirm(record_id: str, return_id: str, user: User = Depends(auth_user), db: Session = Depends(get_db)):
    rec = get_owned(db, user, record_id)
    item_return = db.get(ItemReturn, return_id)
    if not item_return or item_return.record_id != rec.id:
        raise HTTPException(404, 'Return not found')
    return confirm_return(db, rec, item_return, 'OWNER')

@app.get('/api/share/{token}')
def public_invite(token: str, db: Session = Depends(get_db)):
    inv, rec = invited(db, token)
    return recipient_view(db, inv, rec)

@app.post('/api/share/{token}/respond', dependencies=[Depends(require_csrf)])
def respond(token: str, body: ShareResponse, db: Session = Depends(get_db)):
    inv, rec = invited(db, token)
    return record_response(db, inv, rec, body.accept)

@app.post('/api/share/{token}/returns', dependencies=[Depends(require_csrf)])
def guest_return(token: str, body: QuantityBody, db: Session = Depends(get_db)):
    inv, rec = invited(db, token)
    ensure_share_accepted(inv, rec)
    return add_return(db, rec, body.quantity, 'GUEST')

@app.post('/api/share/{token}/returns/{return_id}/confirm', dependencies=[Depends(require_csrf)])
def guest_confirm(token: str, return_id: str, db: Session = Depends(get_db)):
    inv, rec = invited(db, token)
    ensure_share_accepted(inv, rec)
    item_return = db.get(ItemReturn, return_id)
    if not item_return or item_return.record_id != rec.id:
        raise HTTPException(404, 'Return not found')
    return confirm_return(db, rec, item_return, 'GUEST')

@app.get('/api/health')
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text('SELECT 1'))
    except Exception:
        raise HTTPException(503, 'Database unavailable') from None
    return {'ok': True, 'app': 'udhaar'}

@app.get('/')
@app.get('/signup')
@app.get('/share/{token}')
def frontend(token: str = ''):
    return FileResponse(ROOT / 'static' / 'index.html')
