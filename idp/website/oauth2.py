import os
from pathlib import Path
from joserfc.jwk import RSAKey
from flask import current_app
from authlib.integrations.flask_oauth2 import AuthorizationServer, ResourceProtector
from authlib.integrations.sqla_oauth2 import (
    create_query_client_func, create_save_token_func,
    create_bearer_token_validator,
)
from authlib.oauth2.rfc6749.grants import AuthorizationCodeGrant as BaseAuthorizationCodeGrant
from authlib.oidc.core.grants import OpenIDCode as BaseOpenIDCode
from authlib.oidc.core import UserInfo
from .models import db, User, OAuth2Client, OAuth2AuthorizationCode, OAuth2Token


def signing_key():
    path = Path(current_app.config['OIDC_SIGNING_KEY_PATH']).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        key = RSAKey.generate_key(2048, {'use': 'sig', 'alg': 'RS256'})
        path.write_bytes(key.as_pem(private=True))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return path.read_text(encoding='utf-8')

def public_jwks():
    key = RSAKey.import_key(signing_key())
    return {'keys': [key.as_dict(private=False, use='sig', alg='RS256', key_ops=['verify'])]}

def generate_user_info(user, scope):
    return UserInfo(sub=str(user.id), name=user.username).filter(scope)

class AuthorizationCodeGrant(BaseAuthorizationCodeGrant):
    def save_authorization_code(self, code, request):
        item = OAuth2AuthorizationCode(
            code=code,
            client_id=request.client.client_id,
            redirect_uri=request.payload.redirect_uri,
            scope=request.scope,
            user_id=request.user.id,
            nonce=request.payload.data.get('nonce'),
        )
        db.session.add(item)
        db.session.commit()

    def query_authorization_code(self, code, client):
        item = OAuth2AuthorizationCode.query.filter_by(
            code=code, client_id=client.client_id
        ).first()
        if item and not item.is_expired():
            return item

    def delete_authorization_code(self, authorization_code):
        db.session.delete(authorization_code)
        db.session.commit()

    def authenticate_user(self, authorization_code):
        return db.session.get(User, authorization_code.user_id)

class OpenIDCode(BaseOpenIDCode):
    def exists_nonce(self, nonce, request):
        return OAuth2AuthorizationCode.query.filter_by(
            client_id=request.payload.client_id, nonce=nonce
        ).first() is not None

    def get_jwt_config(self, grant):
        return {
            'key': signing_key(),
            'alg': 'RS256',
            'iss': current_app.config['OIDC_ISSUER'],
            'exp': 300,
        }

    def generate_user_info(self, user, scope):
        return generate_user_info(user, scope)

authorization = AuthorizationServer()
require_oauth = ResourceProtector()

def config_oauth(app):
    authorization.init_app(
        app,
        query_client=create_query_client_func(db.session, OAuth2Client),
        save_token=create_save_token_func(db.session, OAuth2Token),
    )
    authorization.register_grant(AuthorizationCodeGrant, [OpenIDCode(require_nonce=True)])
    validator = create_bearer_token_validator(db.session, OAuth2Token)
    require_oauth.register_token_validator(validator())
