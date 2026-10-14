import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'idp'))

import pytest
from website.app import create_app
from website.models import db, User, OAuth2Client
from werkzeug.security import check_password_hash

@pytest.fixture()
def app(tmp_path):
    app = create_app({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{tmp_path / "test.db"}',
        'OIDC_ISSUER': 'http://localhost:5002',
        'OIDC_SIGNING_KEY_PATH': str(tmp_path / 'private.pem'),
        'DAYMARK_CLIENT_ID': 'daymark-local',
        'DAYMARK_CLIENT_SECRET': 'local-test-secret',
        'DAYMARK_CALLBACK': 'http://localhost:8101/auth/callback',
        'DAYMARK_POST_LOGOUT_REDIRECT': 'http://localhost:5174/',
    })
    with app.app_context():
        db.create_all()
        client = OAuth2Client(client_id='daymark-local')
        client.client_id_issued_at = 1
        client.set_client_metadata({
            'client_name': 'Daymark',
            'grant_types': ['authorization_code'],
            'redirect_uris': ['http://localhost:8101/auth/callback'],
            'post_logout_redirect_uris': ['http://localhost:5174/'],
            'response_types': ['code'],
            'scope': 'openid profile',
            'token_endpoint_auth_method': 'client_secret_basic',
        })
        db.session.add(client)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture()
def client(app):
    return app.test_client()

def test_discovery_advertises_code_flow_and_rs256(client):
    response = client.get('/.well-known/openid-configuration')
    assert response.status_code == 200
    data = response.get_json()
    assert data['authorization_endpoint'] == 'http://localhost:5002/oauth/authorize'
    assert data['response_types_supported'] == ['code']
    assert data['id_token_signing_alg_values_supported'] == ['RS256']
    assert data['jwks_uri'] == 'http://localhost:5002/oauth/jwks'
    assert data['end_session_endpoint'] == 'http://localhost:5002/logout'

def test_registration_hashes_password_and_creates_session(client, app):
    response = client.post('/register', data={
        'username': 'demo-user', 'password': 'a long demo password 42!', 'next': '/',
    })
    assert response.status_code == 303
    with app.app_context():
        user = User.query.filter_by(username='demo-user').one()
        assert user.password_hash != 'a long demo password 42!'
        assert check_password_hash(user.password_hash, 'a long demo password 42!')
    assert b'demo-user' in client.get('/').data

def test_login_rejects_bad_password_and_external_next(client):
    client.post('/register', data={
        'username': 'demo-user', 'password': 'a long demo password 42!', 'next': '/',
    })
    client.get('/logout')
    response = client.post('/login', data={
        'username': 'demo-user', 'password': 'wrong password', 'next': '//evil.example',
    })
    assert response.status_code == 401
    assert 'Location' not in response.headers

def test_jwks_publishes_public_key_only(client):
    response = client.get('/oauth/jwks')
    assert response.status_code == 200
    key = response.get_json()['keys'][0]
    assert key['kty'] == 'RSA'
    assert key['alg'] == 'RS256'
    assert key['key_ops'] == ['verify']
    assert 'd' not in key

def test_logout_only_redirects_to_the_registered_daymark_destination(client):
    allowed = client.get('/logout?client_id=daymark-local&post_logout_redirect_uri=http://localhost:5174/')
    assert allowed.status_code == 303
    assert allowed.headers['Location'] == 'http://localhost:5174/'
    rejected = client.get('/logout?client_id=daymark-local&post_logout_redirect_uri=https://untrusted.example/')
    assert rejected.status_code == 303
    assert rejected.headers['Location'] == '/'
