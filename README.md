# Mini SSO, Daymark, and Clearline

A learning portfolio project with one OpenID Connect identity provider and two separate full-stack clients:

- **Daymark** is a personal task manager.
- **Clearline** is a rule-based Data Loss Prevention (DLP) scanner for pasted text and small text documents.

The Mini SSO provider handles login and consent. Each client has its own callback, client secret, and session cookie. Neither client handles the user's Mini SSO password.

## Stack

- Identity Provider: Flask, Authlib, SQLAlchemy, PostgreSQL or SQLite.
- Daymark API: FastAPI, Authlib, SQLAlchemy, PostgreSQL or SQLite.
- Clearline API: FastAPI, Authlib, SQLAlchemy, PostgreSQL or SQLite.
- User interface: React, TypeScript, Vite, responsive CSS.

## Clearline scan behavior

Employees can paste text or submit UTF-8 TXT, Markdown, and CSV files up to 100 KB. The scanner checks for likely payment card numbers (with a Luhn check), Aadhaar-style 12-digit numbers, email addresses, Indian mobile numbers, and password/API-secret assignments.

When a pattern is found, Clearline replaces the matched value with a typed marker such as [REDACTED:EMAIL]. The employee can review, copy, or download the cleaned result. This demo does not forward content to another service.

**Submitted text and files are scanned in memory and are not retained.** The audit table stores only the employee name, source type, timestamp, action, and finding counts/categories. It does not store file names, submitted text, matched values, or network addresses.

The audit view is protected by the DLP API. Set DLP_ADMIN_SUBJECTS in the private .env to a comma-separated list of Mini SSO subject IDs. Sign in to Clearline and read the subject value from http://localhost:8102/api/me; then set the ID and restart the Clearline API. No account is an administrator by default.

Regex scanning is a small demonstration. It can miss sensitive data and can flag ordinary content. A “clear” result is not a guarantee that the content is safe. PDF and Office file parsing, background job queues, configurable policies, retention controls, and production-grade audit controls are not included.

## Run locally (PowerShell)

From the project root, prepare local configuration:

<pre><code>Copy-Item .env.example .env
Copy-Item web/.env.example web/.env</code></pre>

Replace the example secrets in .env with unique random values. Keep .env private. Start PostgreSQL if Docker Desktop is available:

<pre><code>docker compose up -d db
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r idp\requirements.txt
py -m pip install -r daymark\requirements.txt
py -m pip install -r dlp\requirements.txt
Set-Location web
npm install
Set-Location ..</code></pre>

If Docker is unavailable, set DATABASE_URL in .env to sqlite:///minisso-local.db. Leave DLP_DATABASE_URL blank so Clearline uses the same configured database. Daymark can use its local SQLite database with DAYMARK_DATABASE_URL=sqlite:///./daymark.db.

Open four PowerShell terminals from the project root.

**Terminal 1 — Mini SSO**

<pre><code>Set-Location idp
..\.venv\Scripts\Activate.ps1
flask --app app initdb
flask --app app run --port 5002</code></pre>

The initdb command creates or updates both OAuth clients: Daymark and Clearline DLP. Run it again after changing client IDs, secrets, or callback URLs.

**Terminal 2 — Daymark API**

<pre><code>.\.venv\Scripts\Activate.ps1
uvicorn main:app --app-dir daymark --reload --port 8101 --env-file .env</code></pre>

**Terminal 3 — Clearline DLP API**

<pre><code>.\.venv\Scripts\Activate.ps1
uvicorn main:app --app-dir dlp --reload --port 8102 --env-file .env</code></pre>

**Terminal 4 — React app**

<pre><code>Set-Location web
npm run dev -- --port 5174 --strictPort</code></pre>

Open http://localhost:5174 to choose Daymark or Clearline. Both use Mini SSO and consent.

The local ports are 5002 (Mini SSO), 8101 (Daymark API), 8102 (Clearline API), and 5174 (UI). If you change them, update the matching issuer, callback, logout redirect, and frontend URL in .env, then rerun flask initdb.

## Daymark features

- Inbox, Today, Upcoming, All Tasks, and Completed views.
- Quick-add and full task editor with notes, priority, dates, projects, and tags.
- Search, task completion/reopening, edit, and delete.
- Preferences for theme, density, week start, and date format.
- Tasks and projects are scoped to the authenticated OIDC subject.

## Clearline features

- Paste text or scan a small TXT, Markdown, or CSV file.
- Asynchronous request handling keeps the FastAPI event loop responsive while text is scanned.
- Automatic in-memory redaction and a cleaned preview.
- Copy or download the cleaned text for review.
- Admin-only audit dashboard with counts and categories, without content retention.
- Separate OIDC client and signed-in session from Daymark.

## Security notes and limitations

- Authlib handles the OIDC state/nonce and server-side authorization-code exchange.
- Client secrets remain in backend configuration; callbacks are registered exactly in Mini SSO.
- Write requests require session-bound CSRF tokens. Session cookies are HttpOnly and SameSite=Lax.
- The scanner uses patterns and the Luhn checksum; it is not an ML classifier, endpoint protection, or a production DLP boundary.
- Use HTTPS and secure cookies outside local development. Use disposable test accounts and synthetic sample data.
- Production readiness would require independent security review, stronger authorization administration, database migrations, rate limits, key rotation, monitoring, backups, and tested retention policies.

## Tests

Run the existing project checks with:

<pre><code>.\.venv\Scripts\python.exe -m pytest -q</code></pre>

The current tests cover Mini SSO behavior, Daymark CRUD, authentication requirements, date validation, and user data isolation.