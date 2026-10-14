from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from daymark import main


@pytest.fixture()
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'daymark-test.db'}", connect_args={'check_same_thread': False})
    monkeypatch.setattr(main, 'engine', engine)
    monkeypatch.setattr(main, 'SessionLocal', sessionmaker(bind=engine, expire_on_commit=False))
    main.Base.metadata.create_all(engine)
    identity = {'sub': 'user-a', 'name': 'A'}
    main.app.dependency_overrides[main.current_user] = lambda: identity
    monkeypatch.setattr(main, 'check_csrf', lambda request: None)
    with TestClient(main.app) as test_client:
        test_client.identity = identity
        yield test_client
    main.app.dependency_overrides.clear()
    main.Base.metadata.drop_all(engine)
    engine.dispose()


def test_task_crud_and_date_validation(client):
    project = client.post('/api/projects', json={'name': 'Study'}).json()
    created = client.post('/api/tasks', json={
        'title': 'Read chapter', 'notes': 'Take notes', 'priority': 3,
        'start_date': '2026-10-14', 'due_date': '2026-10-16',
        'project_id': project['id'], 'tags': ['school', 'reading'],
    })
    assert created.status_code == 200
    task = created.json()
    assert task['project_name'] == 'Study'
    assert task['tags'] == ['school', 'reading']
    assert len(client.get('/api/tasks?view=upcoming&today=2026-10-14').json()) == 0
    assert len(client.get('/api/tasks?view=today&today=2026-10-14').json()) == 1
    later = client.post('/api/tasks', json={'title': 'Later task', 'due_date': '2026-10-20'}).json()
    assert len(client.get('/api/tasks?view=upcoming&today=2026-10-14').json()) == 1
    assert client.patch(f"/api/tasks/{task['id']}", json={'completed': True}).json()['completed'] is True
    assert len(client.get('/api/tasks?view=completed').json()) == 1
    assert len(client.get('/api/tasks?view=all').json()) == 1
    invalid = client.post('/api/tasks', json={'title': 'Impossible dates', 'start_date': '2026-10-20', 'due_date': '2026-10-19'})
    assert invalid.status_code == 422
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
    assert client.delete(f"/api/tasks/{later['id']}").status_code == 204
    assert client.get('/api/tasks?view=all').json() == []


def test_task_and_project_data_are_scoped_to_identity(client):
    project = client.post('/api/projects', json={'name': 'Private'}).json()
    task = client.post('/api/tasks', json={'title': 'My private task', 'project_id': project['id']}).json()
    client.identity['sub'] = 'user-b'
    assert client.get('/api/tasks?view=all').json() == []
    assert client.get('/api/projects').json() == []
    assert client.patch(f"/api/tasks/{task['id']}", json={'title': 'Changed'}).status_code == 404
    assert client.delete(f"/api/projects/{project['id']}").status_code == 404
    assert client.post('/api/tasks', json={'title': 'Invalid project', 'project_id': project['id']}).status_code == 404


def test_api_requires_a_signed_in_user():
    with TestClient(main.app) as client:
        response = client.get('/api/tasks')
    assert response.status_code == 401
