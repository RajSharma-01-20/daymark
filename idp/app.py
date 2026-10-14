import os
from website.app import create_app

app = create_app({
    'SECRET_KEY': os.getenv('IDP_SECRET_KEY', 'local-development-only-change-this'),
    'SQLALCHEMY_TRACK_MODIFICATIONS': False,
    'SQLALCHEMY_DATABASE_URI': os.getenv('DATABASE_URL', 'sqlite:///minisso-local.db'),
    'OIDC_ISSUER': os.getenv('IDP_ISSUER', 'http://localhost:5002').rstrip('/'),
    'OIDC_SIGNING_KEY_PATH': os.getenv('OIDC_SIGNING_KEY_PATH', 'keys/idp-rs256-private.pem'),
    'DAYMARK_CLIENT_ID': os.getenv('DAYMARK_CLIENT_ID', 'daymark-local'),
    'DAYMARK_CLIENT_SECRET': os.getenv('DAYMARK_CLIENT_SECRET', 'local-daymark-client-secret-change-this'),
    'DAYMARK_CALLBACK': os.getenv('DAYMARK_CALLBACK', 'http://localhost:8101/auth/callback'),
    'DAYMARK_POST_LOGOUT_REDIRECT': os.getenv('DAYMARK_POST_LOGOUT_REDIRECT', os.getenv('WEB_URL', 'http://localhost:5174') + '/'),
})

@app.cli.command('initdb')
def initdb():
    from website.models import db, OAuth2Client
    with app.app_context():
        db.create_all()
        client = OAuth2Client.query.filter_by(client_id=app.config['DAYMARK_CLIENT_ID']).first()
        if client is None:
            client = OAuth2Client(client_id=app.config['DAYMARK_CLIENT_ID'])
            client.client_id_issued_at = 1
            db.session.add(client)
        client.client_secret = app.config['DAYMARK_CLIENT_SECRET']
        client.set_client_metadata({
            'client_name': 'Daymark',
            'client_uri': 'http://localhost:5174/app',
            'grant_types': ['authorization_code'],
            'redirect_uris': [app.config['DAYMARK_CALLBACK']],
            'post_logout_redirect_uris': [app.config['DAYMARK_POST_LOGOUT_REDIRECT']],
            'response_types': ['code'],
            'scope': 'openid profile',
            'token_endpoint_auth_method': 'client_secret_basic',
        })
        db.session.commit()
        print('Local database ready. Registered client: Daymark.')

