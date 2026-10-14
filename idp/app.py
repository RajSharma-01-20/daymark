import os
from website.app import create_app

app = create_app({
    "SECRET_KEY": os.getenv("IDP_SECRET_KEY", "local-development-only-change-this"),
    "SQLALCHEMY_TRACK_MODIFICATIONS": False,
    "SQLALCHEMY_DATABASE_URI": os.getenv("DATABASE_URL", "sqlite:///minisso-local.db"),
    "OIDC_ISSUER": os.getenv("IDP_ISSUER", "http://localhost:5002").rstrip("/"),
    "OIDC_SIGNING_KEY_PATH": os.getenv("OIDC_SIGNING_KEY_PATH", "keys/idp-rs256-private.pem"),
})

@app.cli.command("initdb")
def initdb():
    from website.models import db, OAuth2Client
    web_url = os.getenv("WEB_URL", "http://localhost:5174").rstrip("/")
    clients = [
        {
            "client_id": os.getenv("DAYMARK_CLIENT_ID", "daymark-local"),
            "client_secret": os.getenv("DAYMARK_CLIENT_SECRET", "local-daymark-client-secret-change-this"),
            "client_name": "Daymark",
            "client_uri": web_url + "/app",
            "redirect_uri": os.getenv("DAYMARK_CALLBACK", "http://localhost:8101/auth/callback"),
            "post_logout_redirect_uri": os.getenv("DAYMARK_POST_LOGOUT_REDIRECT", web_url + "/"),
        },
        {
            "client_id": os.getenv("DLP_CLIENT_ID", "clearline-local"),
            "client_secret": os.getenv("DLP_CLIENT_SECRET", "local-clearline-client-secret-change-this"),
            "client_name": "Clearline DLP",
            "client_uri": web_url + "/dlp",
            "redirect_uri": os.getenv("DLP_CALLBACK", "http://localhost:8102/auth/callback"),
            "post_logout_redirect_uri": os.getenv("DLP_POST_LOGOUT_REDIRECT", web_url + "/dlp"),
        },
    ]
    with app.app_context():
        db.create_all()
        for config in clients:
            client = OAuth2Client.query.filter_by(client_id=config["client_id"]).first()
            if client is None:
                client = OAuth2Client(client_id=config["client_id"])
                client.client_id_issued_at = 1
                db.session.add(client)
            client.client_secret = config["client_secret"]
            client.set_client_metadata({
                "client_name": config["client_name"],
                "client_uri": config["client_uri"],
                "grant_types": ["authorization_code"],
                "redirect_uris": [config["redirect_uri"]],
                "post_logout_redirect_uris": [config["post_logout_redirect_uri"]],
                "response_types": ["code"],
                "scope": "openid profile",
                "token_endpoint_auth_method": "client_secret_basic",
            })
        db.session.commit()
    print("Local database ready. Registered clients: Daymark, Clearline DLP.")