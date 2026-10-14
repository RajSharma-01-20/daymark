# Mini SSO Identity Provider

This Flask application provides the shared OpenID Connect login for Daymark and Clearline. It handles registration, password hashing, consent, authorization codes, signed ID tokens, discovery metadata, JWKS, and logout.

Use the project root README for setup instructions. The Identity Provider runs on port 5002. The initdb command registers the Daymark callback at http://localhost:8101/auth/callback and the Clearline callback at http://localhost:8102/auth/callback.

The RS256 private key is generated locally and ignored by Git. Keep .env, signing keys, client secrets, and real user data out of source control. This is a learning project for disposable test users, not a production Identity Provider.