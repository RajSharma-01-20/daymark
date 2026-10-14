# Daymark — Personal Task Manager

Daymark is a standalone task management app with a React interface and FastAPI backend. It uses OpenID Connect for sign-in; the identity provider is a separate project. For the portfolio demonstration, use [Mini SSO](https://github.com/RajSharma-01-20/mini-sso).

## Features

- Inbox, Today, Upcoming, All Tasks, and Completed views
- Quick-add and editable tasks with notes, priorities, start and due dates
- Projects, tags, search, completion tracking, and preferences
- Per-user task data scoped to the identity provider subject

## Local setup

Run Mini SSO separately at `http://localhost:5002`. Register a Daymark client with ID `daymark-local`, a unique client secret, callback `http://localhost:8101/auth/callback`, and post-logout redirect `http://localhost:5174/`. Configure the same client values below.

From this project root, prepare Python dependencies and environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r backend\requirements.txt
$env:IDP_ISSUER = "http://localhost:5002"
$env:DAYMARK_CLIENT_ID = "daymark-local"
$env:DAYMARK_CLIENT_SECRET = "<your-client-secret>"
$env:DAYMARK_SESSION_SECRET = "<a-long-random-secret>"
$env:DAYMARK_URL = "http://localhost:8101"
$env:WEB_URL = "http://localhost:5174"
uvicorn main:app --app-dir backend --reload --port 8101
```

In a second terminal:

```powershell
cd frontend
npm install
$env:VITE_DAYMARK_URL = "http://localhost:8101"
npm run dev
```

Open http://localhost:5174. SQLite is used by default for local data. Set `DAYMARK_DATABASE_URL` to a PostgreSQL connection string for PostgreSQL. Use disposable accounts and unique random secrets. This is a learning project and is not production-ready task or identity software.
