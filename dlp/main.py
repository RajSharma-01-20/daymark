import json
import os
import re
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import urlencode

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

IDP_ISSUER = os.getenv("IDP_ISSUER", "http://localhost:5002").rstrip("/")
DLP_URL = os.getenv("DLP_URL", "http://localhost:8102").rstrip("/")
WEB_URL = os.getenv("WEB_URL", "http://localhost:5174").rstrip("/")
DATABASE_URL = os.getenv("DLP_DATABASE_URL") or os.getenv("DATABASE_URL", "sqlite:///./dlp.db")
MAX_SCAN_BYTES = 100_000
ALLOWED_SUFFIXES = {".txt", ".md", ".csv"}

engine_options = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}
engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class ScanRecord(Base):
    __tablename__ = "clearline_scan_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_sub: Mapped[str] = mapped_column(String(120), index=True)
    user_name: Mapped[str] = mapped_column(String(120))
    source_type: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(16))
    findings_json: Mapped[str] = mapped_column(Text, default="{}")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class ScanRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_SCAN_BYTES)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Clearline DLP Scanner", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("DLP_SESSION_SECRET", "local-clearline-session-secret-change-this"),
    session_cookie="clearline_session",
    same_site="lax",
    https_only=os.getenv("COOKIE_SECURE", "false").lower() == "true",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[WEB_URL],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)

oauth = OAuth()
oauth.register(
    name="mini_sso",
    client_id=os.getenv("DLP_CLIENT_ID", "clearline-local"),
    client_secret=os.getenv("DLP_CLIENT_SECRET", "local-clearline-client-secret-change-this"),
    server_metadata_url=f"{IDP_ISSUER}/.well-known/openid-configuration",
    client_kwargs={"scope": "openid profile"},
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user or not user.get("sub"):
        raise HTTPException(status_code=401, detail="Sign in to use Clearline.")
    return user


def check_csrf(request: Request):
    expected = request.session.get("csrf_token")
    supplied = request.headers.get("x-csrf-token")
    if not expected or not supplied or not secrets.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail="Your session token is missing or expired. Refresh and try again.")


def is_admin(user: dict) -> bool:
    allowed = {value.strip() for value in os.getenv("DLP_ADMIN_SUBJECTS", "").split(",") if value.strip()}
    return str(user["sub"]) in allowed


def require_admin(user: dict = Depends(current_user)) -> dict:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Your Mini SSO subject is not configured as a Clearline administrator.")
    return user


SECRET_VALUE = re.compile(r"\b(?:password|passwd|passcode|api[_-]?key|access[_-]?token|client[_-]?secret|secret)\b\s*[:=]\s*([^\s,;]+)", re.IGNORECASE)
AADHAAR = re.compile(r"(?<!\d)(?:\d{4}[ -]?){2}\d{4}(?!\d)")
CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
EMAIL = re.compile(r"(?i)(?<![\w.+-])[A-Z0-9.!#$%&'*+/=?^_{}|~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+")
PHONE = re.compile(r"(?<!\d)(?:\+91[ -]?)?[6-9]\d{9}(?!\d)")


def passes_luhn(value: str) -> bool:
    digits = [int(char) for char in value if char.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def scan_sensitive_text(text: str) -> tuple[str, dict[str, int]]:
    candidates: list[tuple[int, int, int, str]] = []
    for match in SECRET_VALUE.finditer(text):
        candidates.append((match.start(1), match.end(1), 10, "SECRET"))
    for match in AADHAAR.finditer(text):
        candidates.append((match.start(), match.end(), 9, "AADHAAR"))
    for match in CARD_CANDIDATE.finditer(text):
        if passes_luhn(match.group()):
            candidates.append((match.start(), match.end(), 8, "PAYMENT_CARD"))
    for match in EMAIL.finditer(text):
        candidates.append((match.start(), match.end(), 6, "EMAIL"))
    for match in PHONE.finditer(text):
        candidates.append((match.start(), match.end(), 5, "PHONE"))

    accepted: list[tuple[int, int, str]] = []
    occupied_until = -1
    for start, end, priority, kind in sorted(candidates, key=lambda item: (item[0], -item[2], -(item[1] - item[0]))):
        if start < occupied_until:
            continue
        accepted.append((start, end, kind))
        occupied_until = end

    output: list[str] = []
    findings: dict[str, int] = {}
    cursor = 0
    for start, end, kind in accepted:
        output.extend((text[cursor:start], f"[REDACTED:{kind}]"))
        findings[kind] = findings.get(kind, 0) + 1
        cursor = end
    output.append(text[cursor:])
    return "".join(output), findings


def store_scan(user: dict, source_type: str, findings: dict[str, int], action: str):
    with SessionLocal() as db:
        record = ScanRecord(
            user_sub=str(user["sub"]),
            user_name=str(user.get("name", "Employee"))[:120],
            source_type=source_type,
            action=action,
            findings_json=json.dumps(findings, sort_keys=True),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return {
            "id": record.id,
            "action": action,
            "findings": [{"type": kind, "count": count} for kind, count in sorted(findings.items())],
            "raw_content_saved": False,
            "created_at": record.created_at.isoformat(),
        }

@app.get("/health")
def health():
    return {"status": "ok", "service": "clearline"}


@app.get("/login")
async def login(request: Request):
    return await oauth.mini_sso.authorize_redirect(request, f"{DLP_URL}/auth/callback")


@app.get("/auth/callback")
async def auth_callback(request: Request):
    if request.query_params.get("error"):
        return RedirectResponse(f"{WEB_URL}/dlp?error=login_denied", status_code=303)
    try:
        token = await oauth.mini_sso.authorize_access_token(request)
    except Exception:
        return RedirectResponse(f"{WEB_URL}/dlp?error=login_failed", status_code=303)
    userinfo = token.get("userinfo")
    if not userinfo or not userinfo.get("sub"):
        return RedirectResponse(f"{WEB_URL}/dlp?error=identity_missing", status_code=303)
    request.session.clear()
    request.session["user"] = {"sub": str(userinfo["sub"]), "name": userinfo.get("name", "Employee")}
    request.session["csrf_token"] = secrets.token_urlsafe(32)
    return RedirectResponse(f"{WEB_URL}/dlp", status_code=303)


@app.get("/api/me")
def me(request: Request):
    user = request.session.get("user")
    if not user:
        return JSONResponse({"authenticated": False}, status_code=401)
    if not request.session.get("csrf_token"):
        request.session["csrf_token"] = secrets.token_urlsafe(32)
    return {
        "authenticated": True,
        "user": {"name": user.get("name", "Employee"), "subject": str(user["sub"])},
        "is_admin": is_admin(user),
        "csrf_token": request.session["csrf_token"],
    }


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    query = urlencode({
        "client_id": os.getenv("DLP_CLIENT_ID", "clearline-local"),
        "post_logout_redirect_uri": os.getenv("DLP_POST_LOGOUT_REDIRECT", f"{WEB_URL}/dlp"),
    })
    return RedirectResponse(f"{IDP_ISSUER}/logout?{query}", status_code=303)


@app.post("/api/scan")
def scan_text(
    payload: ScanRequest,
    request: Request,
    user: dict = Depends(current_user),
):
    check_csrf(request)
    if len(payload.text.encode("utf-8")) > MAX_SCAN_BYTES:
        raise HTTPException(status_code=413, detail="Keep each scan under 100 KB.")
    sanitized, findings = scan_sensitive_text(payload.text)
    action = "redacted" if findings else "clear"
    result = store_scan(user, "text", findings, action)
    result["sanitized_text"] = sanitized
    return result


@app.post("/api/scan-file")
async def scan_file(
    request: Request,
    file: UploadFile = File(...),
    user: dict = Depends(current_user),
):
    check_csrf(request)
    filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not filename or filename.startswith(".") or os.path.splitext(filename)[1].lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=415, detail="Upload a plain text, Markdown, or CSV file.")
    if file.size is not None and file.size > MAX_SCAN_BYTES:
        await file.close()
        raise HTTPException(status_code=413, detail="Keep each file under 100 KB.")
    content = await file.read(MAX_SCAN_BYTES + 1)
    await file.close()
    if len(content) > MAX_SCAN_BYTES:
        raise HTTPException(status_code=413, detail="Keep each file under 100 KB.")
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise HTTPException(status_code=415, detail="The file must be UTF-8 text.") from error
    sanitized, findings = await run_in_threadpool(scan_sensitive_text, decoded)
    action = "redacted" if findings else "clear"
    result = await run_in_threadpool(store_scan, user, "file", findings, action)
    result["sanitized_text"] = sanitized
    return result

@app.get("/api/audit")
def audit_log(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
):
    records = db.scalars(select(ScanRecord).order_by(ScanRecord.created_at.desc(), ScanRecord.id.desc()).offset(offset).limit(limit)).all()
    return {
        "items": [{
            "id": record.id,
            "user": record.user_name,
            "source": record.source_type,
            "action": record.action,
            "findings": json.loads(record.findings_json),
            "created_at": record.created_at.isoformat(),
        } for record in records],
        "limit": limit,
        "offset": offset,
    }