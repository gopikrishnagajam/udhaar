"""Run: pytest -q tests — validates permissions, acknowledgment and returns."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.main import app, get_db
from backend.models import Base

@pytest.fixture
def setup(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "test.sqlite3"}', connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    sf = sessionmaker(bind=engine, expire_on_commit=False)
    def db():
        with sf() as session:
            yield session
    app.dependency_overrides[get_db] = db
    with TestClient(app) as owner, TestClient(app) as guest, TestClient(app) as stranger:
        owner.get('/api/csrf')
        guest.get('/api/csrf')
        stranger.get('/api/csrf')
        yield owner, guest, stranger
    app.dependency_overrides.clear()
    engine.dispose()

def post(client, url, payload):
    return client.post(url, json=payload, headers={'X-CSRF-Token':client.cookies.get('udhaar_csrf', '')})

def account(client, name, email):
    response=post(client,'/api/register', {'name':name,'email':email,'password':'StrongPass123!'} )
    assert response.status_code==200, response.text

def create_record(client, direction='LENT', mode='OFF', quantity=2):
    response=post(client,'/api/records', {
        'direction':direction,'mode':mode,'contact_name':'Rahul','item_name':'Cordless drill','category':'Tools',
        'quantity':quantity,'loan_date':'2026-10-15','due_date':'2026-10-25','notes':'Private purchase receipt'
    })
    assert response.status_code==201, response.text
    return response.json()

def invite(client, id):
    response=post(client,f'/api/records/{id}/share', {})
    assert response.status_code==200, response.text
    return response.json()['path']

def accept(client, path):
    response=post(client,f'/api{path}/respond', {'accept':True})
    assert response.status_code==200, response.text


def test_private_default_and_isolation(setup):
    owner, guest, stranger = setup
    account(owner,'Alex','alex@example.com')
    account(stranger,'Not Alex','not-alex@example.com')
    r=create_record(owner)
    assert r['mode']=='OFF' and r['acknowledgment']=='NONE'
    assert r['outstanding_quantity']==2
    assert guest.get(f'/api/records/{r["id"]}').status_code==401
    assert stranger.get(f'/api/records/{r["id"]}').status_code==404
    assert stranger.get('/api/records').json()==[]
    assert stranger.post(f'/api/records/{r["id"]}/share',headers={'X-CSRF-Token':stranger.cookies['udhaar_csrf']}).status_code==404
    returned=post(owner,f'/api/records/{r["id"]}/returns',{'quantity':1})
    assert returned.json()['status']=='CONFIRMED'
    info=owner.get(f'/api/records/{r["id"]}').json()
    assert info['settlement']=='PARTIAL' and info['outstanding_quantity']==1
    assert post(owner,f'/api/records/{r["id"]}/returns',{'quantity':2}).status_code==409


def test_share_acknowledgment_and_guest_lent_return(setup):
    owner, guest, stranger=setup
    account(owner,'Alex','alex@example.com')
    r=create_record(owner, mode='ON')
    path=invite(owner,r['id'])
    initial=guest.get('/api'+path).json()
    assert initial['acknowledgment']=='PENDING'
    assert 'notes' not in initial
    assert 'events' not in initial
    assert post(owner,f'/api/records/{r["id"]}/returns',{'quantity':1}).status_code==409
    assert post(guest,f'/api{path}/returns',{'quantity':1}).status_code==409
    accept(guest,path)
    assert post(guest,f'/api{path}/respond',{'accept':True}).status_code==409
    proposed=post(guest,f'/api{path}/returns',{'quantity':1}).json()
    assert proposed['status']=='PENDING'
    assert owner.get(f'/api/records/{r["id"]}').json()['outstanding_quantity']==2
    assert post(owner,f'/api/records/{r["id"]}/returns',{'quantity':2}).status_code==409
    confirmation=post(owner,f'/api/records/{r["id"]}/returns/{proposed["id"]}/confirm',{})
    assert confirmation.json()['status']=='CONFIRMED'
    assert post(owner,f'/api/records/{r["id"]}/returns/{proposed["id"]}/confirm',{}).status_code==409
    rest=post(owner,f'/api/records/{r["id"]}/returns',{'quantity':1})
    assert rest.json()['status']=='CONFIRMED'
    info=owner.get(f'/api/records/{r["id"]}').json()
    assert info['settlement']=='RETURNED' and info['acknowledgment']=='CONFIRMED'
    assert invite_error(owner, r['id']) == 409

def invite_error(client, record_id):
    return post(client,f'/api/records/{record_id}/share',{}).status_code

def test_borrowed_owner_requests_lender_confirms(setup):
    owner, guest, _=setup
    account(owner,'Alex','alex@example.com')
    r=create_record(owner,direction='BORROWED',mode='ON',quantity=3)
    path=invite(owner,r['id'])
    accept(guest,path)
    proposed=post(owner,f'/api/records/{r["id"]}/returns',{'quantity':2}).json()
    assert proposed['status']=='PENDING'
    assert post(owner,f'/api/records/{r["id"]}/returns/{proposed["id"]}/confirm',{}).status_code==403
    assert post(guest,f'/api{path}/returns/{proposed["id"]}/confirm',{}).status_code==200
    info=owner.get(f'/api/records/{r["id"]}').json()
    assert info['outstanding_quantity']==1
    assert post(guest,f'/api{path}/returns',{'quantity':1}).json()['status']=='CONFIRMED'
    assert owner.get(f'/api/records/{r["id"]}').json()['settlement']=='RETURNED'


def test_decline_invite_rotation_and_csrf(setup):
    owner, guest, _=setup
    account(owner,'Alex','alex@example.com')
    r=create_record(owner)
    assert owner.post('/api/records',json={}).status_code==403
    path1=invite(owner,r['id'])
    path2=invite(owner,r['id'])
    assert guest.get('/api'+path1).status_code==404
    denied=post(guest,f'/api{path2}/respond',{'accept':False})
    assert denied.json()['acknowledgment']=='DECLINED'
    assert guest.get('/api'+path2).status_code==404
    assert owner.get(f'/api/records/{r["id"]}').json()['acknowledgment']=='DECLINED'


def test_invalid_due_date_and_return_limits(setup):
    owner, guest, _=setup
    account(owner,'Alex','alex@example.com')
    data={'direction':'LENT','mode':'OFF','contact_name':'Priya','item_name':'Book','quantity':1,
          'loan_date':'2026-10-15','due_date':'2026-10-01'}
    assert post(owner,'/api/records',data).status_code==422
    data['due_date']='2026-10-25';data['quantity']=0
    assert post(owner,'/api/records',data).status_code==422
