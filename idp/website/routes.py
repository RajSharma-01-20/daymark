from urllib.parse import urlsplit
from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for
from authlib.integrations.flask_oauth2 import current_token
from authlib.oauth2 import OAuth2Error
from joserfc.jwk import RSAKey
from werkzeug.security import check_password_hash, generate_password_hash
from .models import db, User, AuditEvent, OAuth2Client
from .oauth2 import authorization, require_oauth, generate_user_info, public_jwks
from .extensions import csrf

bp = Blueprint('main', __name__)

def signed_in_user():
    user_id = session.get('user_id')
    return db.session.get(User, user_id) if user_id else None

def audit(event_type, username=None, client_id=None):
    db.session.add(AuditEvent(event_type=event_type, username=username, client_id=client_id))
    db.session.commit()

def safe_local_next(value):
    if not value or not value.startswith('/') or value.startswith('//'):
        return '/'
    parsed = urlsplit(value)
    return value if not parsed.scheme and not parsed.netloc else '/'

@bp.get('/')
def home():
    return render_template('home.html', user=signed_in_user())

@bp.route('/register', methods=['GET', 'POST'])
def register():
    next_url = safe_local_next(request.args.get('next') or request.form.get('next'))
    if request.method == 'GET':
        return render_template('account.html', mode='register', next=next_url)
    username = request.form.get('username', '').strip().lower()
    password = request.form.get('password', '')
    if len(username) < 3 or len(username) > 80 or len(password) < 12:
        return render_template('account.html', mode='register', error='Use a username of 3–80 characters and a password with at least 12 characters.', next=next_url), 400
    if User.query.filter_by(username=username).first():
        return render_template('account.html', mode='register', error='That username is already registered.', next=next_url), 409
    user = User(username=username, password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()
    session.clear()
    session['user_id'] = user.id
    audit('registration', username)
    return redirect(next_url, code=303)

@bp.route('/login', methods=['GET', 'POST'])
def login():
    next_url = safe_local_next(request.args.get('next') or request.form.get('next'))
    if request.method == 'GET':
        return render_template('account.html', mode='login', next=next_url)
    username = request.form.get('username', '').strip().lower()
    password = request.form.get('password', '')
    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password_hash, password):
        audit('sign_in_failed', username[:80])
        return render_template('account.html', mode='login', error='Sign-in failed. Check your details and try again.', next=next_url), 401
    session.clear()
    session['user_id'] = user.id
    audit('sign_in_succeeded', username)
    return redirect(next_url, code=303)

@bp.get('/logout')
def logout():
    user = signed_in_user()
    audit('sign_out', user.username if user else None)
    session.clear()
    client_id = request.args.get('client_id')
    return_to = request.args.get('post_logout_redirect_uri')
    client = OAuth2Client.query.filter_by(client_id=client_id).first() if client_id else None
    allowed_redirects = (client.client_metadata or {}).get('post_logout_redirect_uris', []) if client else []
    if return_to and return_to in allowed_redirects:
        return redirect(return_to, code=303)
    return redirect('/', code=303)

@bp.route('/oauth/authorize', methods=['GET', 'POST'])
def authorize():
    user = signed_in_user()
    if not user:
        return redirect(url_for('main.login', next=safe_local_next(request.full_path)), code=303)
    if request.method == 'GET':
        try:
            grant = authorization.get_consent_grant(end_user=user)
        except OAuth2Error as error:
            return jsonify(error=error.error, description=error.description), 400
        return render_template('authorize.html', user=user, grant=grant)
    approved = request.form.get('confirm') == 'yes'
    audit('consent_granted' if approved else 'consent_denied', user.username, request.args.get('client_id'))
    return authorization.create_authorization_response(grant_user=user if approved else None)

@bp.post('/oauth/token')
@csrf.exempt
def issue_token():
    return authorization.create_token_response()

@bp.get('/oauth/userinfo')
@require_oauth('profile')
def userinfo():
    return jsonify(generate_user_info(current_token.user, current_token.scope))

@bp.get('/.well-known/openid-configuration')
def discovery():
    issuer = current_app.config['OIDC_ISSUER']
    return jsonify({
        'issuer': issuer,
        'authorization_endpoint': issuer + '/oauth/authorize',
        'token_endpoint': issuer + '/oauth/token',
        'userinfo_endpoint': issuer + '/oauth/userinfo',
        'end_session_endpoint': issuer + '/logout',
        'jwks_uri': issuer + '/oauth/jwks',
        'response_types_supported': ['code'],
        'subject_types_supported': ['public'],
        'id_token_signing_alg_values_supported': ['RS256'],
        'scopes_supported': ['openid', 'profile'],
        'token_endpoint_auth_methods_supported': ['client_secret_basic'],
        'grant_types_supported': ['authorization_code'],
    })

@bp.get('/oauth/jwks')
def jwks():
    return jsonify(public_jwks())

@bp.get('/health')
def health():
    return {'status': 'ok', 'service': 'identity-provider'}



