import os
from flask import Flask
from .models import db
from .extensions import csrf
from .oauth2 import config_oauth
from .routes import bp

def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.getenv('IDP_SECRET_KEY', 'local-development-only-change-this'),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        OAUTH2_TOKEN_EXPIRES_IN={'authorization_code': 300},
        SQLALCHEMY_DATABASE_URI=os.getenv('DATABASE_URL', 'sqlite:///minisso-local.db'),
        OIDC_ISSUER=os.getenv('IDP_ISSUER', 'http://localhost:5002').rstrip('/'),
        OIDC_SIGNING_KEY_PATH=os.getenv('OIDC_SIGNING_KEY_PATH', '../keys/idp-rs256-private.pem'),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', 'false').lower() == 'true',
    )
    if config:
        app.config.update(config)
    db.init_app(app)
    csrf.init_app(app)
    config_oauth(app)
    app.register_blueprint(bp)
    return app

