import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from urllib.parse import urlencode

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Table, Column, Text, and_, create_engine, or_, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from starlette.middleware.sessions import SessionMiddleware

IDP_ISSUER = os.getenv('IDP_ISSUER', 'http://localhost:5002').rstrip('/')
DAYMARK_URL = os.getenv('DAYMARK_URL', 'http://localhost:8101').rstrip('/')
WEB_URL = os.getenv('WEB_URL', 'http://localhost:5174').rstrip('/')
DATABASE_URL = os.getenv('DAYMARK_DATABASE_URL', os.getenv('DATABASE_URL', 'sqlite:///./daymark.db'))

engine_options = {'pool_pre_ping': True}
if DATABASE_URL.startswith('sqlite'):
    engine_options['connect_args'] = {'check_same_thread': False}
engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


task_tags = Table(
    'daymark_task_tags', Base.metadata,
    Column('task_id', ForeignKey('daymark_tasks.id', ondelete='CASCADE'), primary_key=True),
    Column('tag_id', ForeignKey('daymark_tags.id', ondelete='CASCADE'), primary_key=True),
)


class Project(Base):
    __tablename__ = 'daymark_projects'
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_sub: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(80))
    color: Mapped[str] = mapped_column(String(20), default='sage')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Tag(Base):
    __tablename__ = 'daymark_tags'
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_sub: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(40))


class Task(Base):
    __tablename__ = 'daymark_tasks'
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_sub: Mapped[str] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text, default='')
    priority: Mapped[int] = mapped_column(Integer, default=0)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey('daymark_projects.id', ondelete='SET NULL'), nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    project: Mapped[Project | None] = relationship()
    tags: Mapped[list[Tag]] = relationship(secondary=task_tags, lazy='selectin')


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    notes: str = Field(default='', max_length=5000)
    priority: int = Field(default=0, ge=0, le=4)
    start_date: date | None = None
    due_date: date | None = None
    project_id: int | None = None
    tags: list[str] = Field(default_factory=list, max_length=12)


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=5000)
    priority: int | None = Field(default=None, ge=0, le=4)
    start_date: date | None = None
    due_date: date | None = None
    project_id: int | None = None
    completed: bool | None = None
    tags: list[str] | None = Field(default=None, max_length=12)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    color: str = Field(default='sage', pattern='^(sage|blue|amber|rose|slate)$')


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=40)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title='Daymark Task Manager', lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv('DAYMARK_SESSION_SECRET', 'local-daymark-session-secret-change-this'),
    session_cookie='daymark_session', same_site='lax',
    https_only=os.getenv('COOKIE_SECURE', 'false').lower() == 'true',
)
app.add_middleware(
    CORSMiddleware, allow_origins=[WEB_URL], allow_credentials=True,
    allow_methods=['GET', 'POST', 'PATCH', 'DELETE'],
    allow_headers=['Content-Type', 'X-CSRF-Token'],
)

oauth = OAuth()
oauth.register(
    name='mini_sso',
    client_id=os.getenv('DAYMARK_CLIENT_ID', 'daymark-local'),
    client_secret=os.getenv('DAYMARK_CLIENT_SECRET', 'local-daymark-client-secret-change-this'),
    server_metadata_url=f'{IDP_ISSUER}/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid profile'},
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request) -> dict:
    user = request.session.get('user')
    if not user or not user.get('sub'):
        raise HTTPException(status_code=401, detail='Sign in to use Daymark.')
    return user


def check_csrf(request: Request):
    expected = request.session.get('csrf_token')
    supplied = request.headers.get('x-csrf-token')
    if not expected or not supplied or not secrets.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail='Your session token is missing or expired. Refresh and try again.')


def user_project(db: Session, project_id: int | None, owner_sub: str):
    if project_id is None:
        return None
    project = db.scalar(select(Project).where(Project.id == project_id, Project.owner_sub == owner_sub))
    if not project:
        raise HTTPException(status_code=404, detail='Project not found.')
    return project


def get_tags(db: Session, names: list[str], owner_sub: str):
    clean = list(dict.fromkeys(name.strip().lstrip('#')[:40] for name in names if name.strip().lstrip('#')))
    if len(clean) > 12:
        raise HTTPException(status_code=422, detail='A task can have up to 12 tags.')
    tags = []
    for name in clean:
        tag = db.scalar(select(Tag).where(Tag.owner_sub == owner_sub, Tag.name == name))
        if tag is None:
            tag = Tag(owner_sub=owner_sub, name=name)
            db.add(tag)
            db.flush()
        tags.append(tag)
    return tags


def task_json(task: Task):
    return {
        'id': task.id, 'title': task.title, 'notes': task.notes,
        'priority': task.priority,
        'start_date': task.start_date.isoformat() if task.start_date else None,
        'due_date': task.due_date.isoformat() if task.due_date else None,
        'project_id': task.project_id,
        'project_name': task.project.name if task.project else None,
        'completed': task.completed,
        'completed_at': task.completed_at.isoformat() if task.completed_at else None,
        'position': task.position, 'tags': [tag.name for tag in task.tags],
        'created_at': task.created_at.isoformat(),
    }


def project_json(project: Project):
    return {'id': project.id, 'name': project.name, 'color': project.color}


@app.get('/health')
def health():
    return {'status': 'ok', 'service': 'daymark'}


@app.get('/login')
async def login(request: Request):
    return await oauth.mini_sso.authorize_redirect(request, f'{DAYMARK_URL}/auth/callback')


@app.get('/auth/callback')
async def auth_callback(request: Request):
    if request.query_params.get('error'):
        return RedirectResponse(f'{WEB_URL}/app?error=login_denied', status_code=303)
    try:
        token = await oauth.mini_sso.authorize_access_token(request)
    except Exception:
        return RedirectResponse(f'{WEB_URL}/app?error=login_failed', status_code=303)
    userinfo = token.get('userinfo')
    if not userinfo or not userinfo.get('sub'):
        return RedirectResponse(f'{WEB_URL}/app?error=identity_missing', status_code=303)
    request.session.clear()
    request.session['user'] = {'sub': str(userinfo['sub']), 'name': userinfo.get('name', 'Daymark user')}
    request.session['csrf_token'] = secrets.token_urlsafe(32)
    return RedirectResponse(f'{WEB_URL}/app', status_code=303)


@app.get('/api/me')
def me(request: Request):
    user = request.session.get('user')
    if not user:
        return JSONResponse({'authenticated': False}, status_code=401)
    if not request.session.get('csrf_token'):
        request.session['csrf_token'] = secrets.token_urlsafe(32)
    return {'authenticated': True, 'user': {'name': user.get('name', 'Daymark user')}, 'csrf_token': request.session['csrf_token']}


@app.get('/logout')
def logout(request: Request):
    request.session.clear()
    query = urlencode({
        'client_id': os.getenv('DAYMARK_CLIENT_ID', 'daymark-local'),
        'post_logout_redirect_uri': WEB_URL + '/',
    })
    return RedirectResponse(f'{IDP_ISSUER}/logout?{query}', status_code=303)


@app.get('/api/tasks')
def list_tasks(
    request: Request,
    view: str = Query(default='all', pattern='^(all|inbox|today|upcoming|completed)$'),
    q: str = Query(default='', max_length=200),
    priority: int | None = Query(default=None, ge=0, le=4),
    project_id: int | None = None,
    today: date | None = None,
    db: Session = Depends(get_db), user: dict = Depends(current_user),
):
    today = today or date.today()
    statement = select(Task).where(Task.owner_sub == user['sub'])
    if view == 'completed':
        statement = statement.where(Task.completed.is_(True))
    else:
        statement = statement.where(Task.completed.is_(False))
        if view == 'inbox':
            statement = statement.where(Task.project_id.is_(None), Task.start_date.is_(None), Task.due_date.is_(None))
        elif view == 'today':
            statement = statement.where(or_(Task.start_date <= today, Task.due_date <= today))
        elif view == 'upcoming':
            statement = statement.where(or_(Task.start_date > today, and_(Task.start_date.is_(None), Task.due_date > today)))
    if q.strip():
        needle = f'%{q.strip()}%'
        statement = statement.where(or_(Task.title.ilike(needle), Task.notes.ilike(needle)))
    if priority is not None:
        statement = statement.where(Task.priority == priority)
    if project_id is not None:
        statement = statement.where(Task.project_id == project_id)
    tasks = db.scalars(statement.order_by(Task.completed, Task.due_date.is_(None), Task.due_date, Task.position, Task.created_at.desc())).all()
    return [task_json(task) for task in tasks]


@app.post('/api/tasks')
def create_task(payload: TaskCreate, request: Request, db: Session = Depends(get_db), user: dict = Depends(current_user)):
    check_csrf(request)
    if payload.due_date and payload.start_date and payload.due_date < payload.start_date:
        raise HTTPException(status_code=422, detail='The due date cannot be before the start date.')
    project = user_project(db, payload.project_id, user['sub'])
    task = Task(
        owner_sub=user['sub'], title=payload.title.strip(), notes=payload.notes.strip(),
        priority=payload.priority, start_date=payload.start_date, due_date=payload.due_date,
        project=project, position=0, tags=get_tags(db, payload.tags, user['sub']),
    )
    if not task.title:
        raise HTTPException(status_code=422, detail='Task title is required.')
    db.add(task)
    db.commit()
    db.refresh(task)
    return task_json(task)


@app.patch('/api/tasks/{task_id}')
def update_task(task_id: int, payload: TaskUpdate, request: Request, db: Session = Depends(get_db), user: dict = Depends(current_user)):
    check_csrf(request)
    task = db.scalar(select(Task).where(Task.id == task_id, Task.owner_sub == user['sub']))
    if not task:
        raise HTTPException(status_code=404, detail='Task not found.')
    fields = payload.model_dump(exclude_unset=True)
    for key in ('title', 'notes', 'priority', 'completed'):
        if key in fields and fields[key] is None:
            raise HTTPException(status_code=422, detail=f'{key.replace("_", " ").capitalize()} cannot be empty.')
    if 'title' in fields:
        fields['title'] = fields['title'].strip()
        if not fields['title']:
            raise HTTPException(status_code=422, detail='Task title is required.')
    start_date = fields.get('start_date', task.start_date)
    due_date = fields.get('due_date', task.due_date)
    if due_date and start_date and due_date < start_date:
        raise HTTPException(status_code=422, detail='The due date cannot be before the start date.')
    if 'project_id' in fields:
        task.project = user_project(db, fields.pop('project_id'), user['sub'])
    if 'tags' in fields:
        task.tags = get_tags(db, fields.pop('tags') or [], user['sub'])
    for key, value in fields.items():
        if key == 'completed':
            task.completed_at = datetime.now(timezone.utc) if value else None
        setattr(task, key, value)
    db.commit()
    db.refresh(task)
    return task_json(task)


@app.delete('/api/tasks/{task_id}', status_code=204)
def delete_task(task_id: int, request: Request, db: Session = Depends(get_db), user: dict = Depends(current_user)):
    check_csrf(request)
    task = db.scalar(select(Task).where(Task.id == task_id, Task.owner_sub == user['sub']))
    if not task:
        raise HTTPException(status_code=404, detail='Task not found.')
    db.delete(task)
    db.commit()
    return Response(status_code=204)


@app.get('/api/projects')
def list_projects(db: Session = Depends(get_db), user: dict = Depends(current_user)):
    projects = db.scalars(select(Project).where(Project.owner_sub == user['sub']).order_by(Project.name)).all()
    return [project_json(project) for project in projects]


@app.post('/api/projects')
def create_project(payload: ProjectCreate, request: Request, db: Session = Depends(get_db), user: dict = Depends(current_user)):
    check_csrf(request)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail='Project name is required.')
    existing = db.scalar(select(Project).where(Project.owner_sub == user['sub'], Project.name == name))
    if existing:
        raise HTTPException(status_code=409, detail='A project with that name already exists.')
    project = Project(owner_sub=user['sub'], name=name, color=payload.color)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project_json(project)


@app.delete('/api/projects/{project_id}', status_code=204)
def delete_project(project_id: int, request: Request, db: Session = Depends(get_db), user: dict = Depends(current_user)):
    check_csrf(request)
    project = db.scalar(select(Project).where(Project.id == project_id, Project.owner_sub == user['sub']))
    if not project:
        raise HTTPException(status_code=404, detail='Project not found.')
    db.delete(project)
    db.commit()
    return Response(status_code=204)


@app.get('/api/tags')
def list_tags(db: Session = Depends(get_db), user: dict = Depends(current_user)):
    tags = db.scalars(select(Tag).where(Tag.owner_sub == user['sub']).order_by(Tag.name)).all()
    return [{'id': tag.id, 'name': tag.name} for tag in tags]


@app.post('/api/tags')
def create_tag(payload: TagCreate, request: Request, db: Session = Depends(get_db), user: dict = Depends(current_user)):
    check_csrf(request)
    name = payload.name.strip().lstrip('#')[:40]
    if not name:
        raise HTTPException(status_code=422, detail='Tag name is required.')
    tag = db.scalar(select(Tag).where(Tag.owner_sub == user['sub'], Tag.name == name))
    if tag is None:
        tag = Tag(owner_sub=user['sub'], name=name)
        db.add(tag)
        db.commit()
        db.refresh(tag)
    return {'id': tag.id, 'name': tag.name}
