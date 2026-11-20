import asyncio
from datetime import datetime, timedelta

import jwt
from sqlalchemy import select, update

from app.domain import Priority, Status, today_utc
from app.models import Task, User

PASSWORD = "local-test-password-42"


async def register(client, username):
    return await client.post("/auth/register", json={"username": username, "password": PASSWORD})


async def auth_user(client, username):
    user = await register(client, username)
    assert user.status_code == 201, user.text
    login = await client.post("/auth/login", data={"username": username, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return user.json()["id"], {"Authorization": f"Bearer {login.json()['access_token']}"}


def task_payload(**overrides):
    return {
        "title": "Update the API",
        "description": "Implement task management",
        "deadline": (today_utc() + timedelta(days=3)).isoformat(),
        **overrides,
    }


async def make_task(client, headers, **overrides):
    response = await client.post("/tasks", headers=headers, json=task_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


async def set_status(client, path, headers, status):
    return await client.patch(f"{path}/status", headers=headers, json={"status": status})


async def mark_overdue(app, *ids):
    async with app.state.sessions() as session:
        await session.execute(
            update(Task).where(Task.id.in_(ids)).values(deadline=today_utc() - timedelta(days=1))
        )
        await session.commit()


async def test_registration_login_and_jwt(running_app):
    app, client = running_app
    assert (await client.get("/tasks")).status_code == 401
    uid, headers = await auth_user(client, "Alice")
    assert (await register(client, "alice")).status_code == 409
    assert (await client.get("/users/me", headers=headers)).json() == {"id": uid, "username": "alice"}
    assert (await client.get("/users", headers=headers)).json()["total"] == 1
    bad_login = await client.post("/auth/login", data={"username": "alice", "password": "wrong"})
    assert bad_login.status_code == 401

    token = headers["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(token, options={"verify_signature": False})
    claims["exp"] = claims["iat"] - 1
    expired = jwt.encode(claims, app.state.settings.jwt_secret.get_secret_value(), algorithm="HS256")
    invalid = jwt.encode(claims, "other-test-key-that-is-at-least-32-bytes", algorithm="HS256")
    for bearer in (expired, invalid, "not-a-jwt"):
        result = await client.get("/users/me", headers={"Authorization": f"Bearer {bearer}"})
        assert result.status_code == 401
    async with app.state.sessions() as session:
        password_hash = await session.scalar(select(User.password_hash).where(User.id == uid))
        assert password_hash.startswith("$argon2")


async def test_create_read_edit_delete_and_deadline(client):
    user_id, author = await auth_user(client, "author")
    _, stranger = await auth_user(client, "stranger")
    yesterday = (today_utc() - timedelta(days=1)).isoformat()
    invalid = await client.post("/tasks", headers=author, json=task_payload(deadline=yesterday))
    assert invalid.status_code == 422
    unknown_assignee = await client.post("/tasks", headers=author, json=task_payload(assignee_id=999))
    assert unknown_assignee.status_code == 404

    task = await make_task(client, author, deadline=today_utc().isoformat())
    path = f"/tasks/{task['id']}"
    assert task["author_id"] == user_id
    assert task["status"] == "backlog"
    assert (await client.get(path, headers=stranger)).json() == task
    assert (await client.patch(path, headers=stranger, json={"title": "Taken over"})).status_code == 403
    assert (await client.delete(path, headers=stranger)).status_code == 403
    assert (await client.patch(path, headers=author, json={"deadline": yesterday})).status_code == 422
    assert (await client.patch(path, headers=author, json={"status": "done"})).status_code == 422

    edited = await client.patch(path, headers=author, json={"title": "Updated task", "priority": "high"})
    assert edited.status_code == 200
    assert edited.json()["title"] == "Updated task"
    assert datetime.fromisoformat(edited.json()["updated_at"]) > datetime.fromisoformat(task["updated_at"])
    assert (await client.delete(path, headers=author)).status_code == 409
    assert (await set_status(client, path, author, "cancelled")).status_code == 200
    assert (await client.patch(path, headers=author, json={"title": "Closed"})).status_code == 409
    assert (await client.delete(path, headers=author)).status_code == 204
    assert (await client.get(path, headers=author)).status_code == 404


async def test_status_transitions_and_locked_assignee(client):
    _, author = await auth_user(client, "author")
    assignee_id, assignee = await auth_user(client, "assignee")
    _, outsider = await auth_user(client, "outsider")
    task = await make_task(client, author, assignee_id=assignee_id)
    path = f"/tasks/{task['id']}"
    assert (await set_status(client, path, outsider, "in_progress")).status_code == 403
    assert (await set_status(client, path, author, "review")).status_code == 409
    assert (await set_status(client, path, assignee, "in_progress")).status_code == 200
    assert (await set_status(client, path, author, "backlog")).status_code == 409
    assert (await client.delete(path, headers=author)).status_code == 409
    assert (await set_status(client, path, assignee, "review")).status_code == 200
    assert (await client.delete(path, headers=author)).status_code == 409
    assert (await client.patch(path, headers=author, json={"assignee_id": None})).status_code == 409
    assert (await client.patch(path, headers=author, json={"title": "Edited in review"})).status_code == 200
    assert (await set_status(client, path, author, "done")).json()["status"] == "done"
    assert (await client.patch(path, headers=author, json={"title": "Done"})).status_code == 409
    assert (await set_status(client, path, author, "review")).status_code == 409
    assert (await client.delete(path, headers=author)).status_code == 204


async def test_done_requires_assignee_and_future_or_current_deadline(running_app):
    app, client = running_app
    user_id, headers = await auth_user(client, "author")
    unassigned = await make_task(client, headers)
    overdue = await make_task(client, headers, assignee_id=user_id)
    for task in (unassigned, overdue):
        path = f"/tasks/{task['id']}"
        assert (await set_status(client, path, headers, "in_progress")).status_code == 200
        assert (await set_status(client, path, headers, "review")).status_code == 200
    await mark_overdue(app, overdue["id"])
    no_assignee = await set_status(client, f"/tasks/{unassigned['id']}", headers, "done")
    late = await set_status(client, f"/tasks/{overdue['id']}", headers, "done")
    assert no_assignee.status_code == late.status_code == 409
    assert "Assign" in no_assignee.json()["detail"]
    assert "overdue" in late.json()["detail"]


async def test_assignment_limit_also_applies_to_concurrent_requests(client):
    _, author = await auth_user(client, "author")
    assignee, _ = await auth_user(client, "assignee")
    for index in range(9):
        await make_task(client, author, title=f"Existing {index}", assignee_id=assignee)
    results = await asyncio.gather(*(
        client.post(
            "/tasks", headers=author, json=task_payload(title=f"Concurrent {i}", assignee_id=assignee)
        ) for i in range(3)
    ))
    assert sorted(result.status_code for result in results) == [201, 409, 409]
    unassigned = await make_task(client, author, title="Unassigned")
    path = f"/tasks/{unassigned['id']}"
    assert (await client.patch(path, headers=author, json={"assignee_id": assignee})).status_code == 409
    assigned = next(result.json() for result in results if result.status_code == 201)
    assert (await set_status(client, f"/tasks/{assigned['id']}", author, "cancelled")).status_code == 200
    assert (await client.patch(path, headers=author, json={"assignee_id": assignee})).status_code == 200


async def test_comments_have_authenticated_author_and_pagination(client):
    _, owner = await auth_user(client, "owner")
    commenter, headers = await auth_user(client, "commenter")
    task = await make_task(client, owner)
    path = f"/tasks/{task['id']}/comments"
    assert (await client.post(path, json={"text": "Anonymous"})).status_code == 401
    first = await client.post(path, headers=headers, json={"text": "First"})
    assert first.status_code == 201
    assert first.json()["author_id"] == commenter
    assert (await client.post(path, headers=headers, json={"text": "Second"})).status_code == 201
    page = (await client.get(path, headers=owner, params={"limit": 1, "offset": 1})).json()
    assert page["total"] == 2
    assert [item["text"] for item in page["items"]] == ["Second"]


async def test_list_search_filters_and_order(client):
    author, headers = await auth_user(client, "author")
    near = today_utc() + timedelta(days=1)
    far = today_utc() + timedelta(days=5)
    medium = await make_task(client, headers, title="Other job", priority="medium", deadline=near.isoformat())
    high_far = await make_task(
        client, headers, title="QA check", priority="high", deadline=far.isoformat(), assignee_id=author
    )
    high_near = await make_task(
        client, headers, description="QA review", priority="high", deadline=near.isoformat(),
        assignee_id=author,
    )
    low = await make_task(client, headers, priority="low", deadline=near.isoformat())

    page = (await client.get("/tasks", headers=headers, params={"limit": 2})).json()
    assert page["total"] == 4
    assert [row["id"] for row in page["items"]] == [high_near["id"], high_far["id"]]
    next_page = (await client.get("/tasks", headers=headers, params={"limit": 2, "offset": 2})).json()
    assert [row["id"] for row in next_page["items"]] == [medium["id"], low["id"]]

    params = {
        "search": "qa", "status": "backlog", "priority": "high",
        "assignee_id": author, "deadline_from": near.isoformat(), "deadline_to": near.isoformat(),
    }
    filtered = (await client.get("/tasks", headers=headers, params=params)).json()
    assert [row["id"] for row in filtered["items"]] == [high_near["id"]]
    exact = (await client.get("/tasks", headers=headers, params={"deadline": far.isoformat()})).json()
    assert [row["id"] for row in exact["items"]] == [high_far["id"]]
    for sort_by, expected in [("priority", low), ("created_at", low), ("deadline", high_far)]:
        response = await client.get(
            "/tasks", headers=headers, params={"sort_by": sort_by, "direction": "desc"}
        )
        assert response.json()["items"][0]["id"] == expected["id"]


async def test_statistics_and_overdue_exclude_closed_tasks(running_app):
    app, client = running_app
    _, headers = await auth_user(client, "author")
    late = await make_task(client, headers, priority="high")
    await make_task(client, headers, priority="medium")
    closed = await make_task(client, headers, priority="low")
    assert (await set_status(client, f"/tasks/{closed['id']}", headers, "cancelled")).status_code == 200
    await mark_overdue(app, late["id"], closed["id"])

    result = (await client.get("/tasks/overdue", headers=headers)).json()
    assert [task["id"] for task in result["items"]] == [late["id"]]
    stats = (await client.get("/tasks/stats", headers=headers)).json()
    assert stats == {
        "total": 3,
        "active": 2,
        "overdue": 1,
        "by_priority": {priority.value: 1 for priority in Priority},
        "by_status": {
            status.value: 2 if status == Status.BACKLOG else int(status == Status.CANCELLED)
            for status in Status
        },
    }


async def test_periodic_worker_cancels_overdue_review_and_keeps_done(app_factory):
    async with app_factory(worker=True) as (app, client):
        user_id, headers = await auth_user(client, "author")
        late = await make_task(client, headers, assignee_id=user_id)
        done = await make_task(client, headers, assignee_id=user_id)
        future = await make_task(client, headers)
        for task in (late, done):
            path = f"/tasks/{task['id']}"
            for status in ("in_progress", "review"):
                assert (await set_status(client, path, headers, status)).status_code == 200
        assert (await set_status(client, f"/tasks/{done['id']}", headers, "done")).status_code == 200
        await mark_overdue(app, late["id"], done["id"])

        async with asyncio.timeout(5):
            while True:
                result = (await client.get(f"/tasks/{late['id']}", headers=headers)).json()
                if result["status"] == "cancelled":
                    break
                await asyncio.sleep(0.05)
        assert (await client.get(f"/tasks/{done['id']}", headers=headers)).json()["status"] == "done"
        assert (await client.get(f"/tasks/{future['id']}", headers=headers)).json()["status"] == "backlog"
        assert (await client.get("/tasks/overdue", headers=headers)).json()["total"] == 0
