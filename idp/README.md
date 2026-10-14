# Mini SSO Identity Provider

This Flask application is a separate OpenID Connect provider for the Daymark client. It handles account registration, password hashing, consent, authorization codes, signed ID tokens, discovery metadata, JWKS, and logout.

Use the complete PowerShell setup and local run instructions in the project [README](../README.md). The Identity Provider runs on port 5002 and registers Daymark's exact callback at `http://localhost:8101/auth/callback`.

The RS256 private key is generated locally and ignored by Git. Keep `.env`, signing keys, client secrets, and real user data out of source control. This is a learning project for disposable test users, not a production Identity Provider.
