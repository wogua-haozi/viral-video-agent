import sys
import warnings
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from src import manage_users
from src.api import auth_routes
from src.auth.security import verify_password
from src.db.models import User
from tests.test_product_api import api_client


@pytest.mark.asyncio
async def test_closed_registration_cannot_create_accounts_or_obtain_cookies(api_client, monkeypatch):
    client, factory = api_client
    monkeypatch.setattr(auth_routes, "REGISTRATION_ENABLED", False)
    for email in ("pilot-one@example.com", "pilot-two@example.com"):
        response = await client.post("/auth/register", json={"email": email, "password": "fixture-password-only"})
        assert response.status_code == 403
        assert response.json()["error_code"] == "REGISTRATION_CLOSED"
        assert "set-cookie" not in response.headers
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(User)) == 0
    assert (await client.get("/jobs")).status_code == 401


@pytest.mark.asyncio
async def test_manually_created_account_can_login_while_registration_stays_closed(api_client, monkeypatch):
    client, factory = api_client
    monkeypatch.setattr(auth_routes, "REGISTRATION_ENABLED", False)
    monkeypatch.setattr(manage_users, "async_session_factory", factory)
    password = "fixture-pilot-password"
    await manage_users.create_user("Pilot@example.com", password)
    async with factory() as db:
        user = await db.scalar(select(User))
        assert user.email == "pilot@example.com"
        assert user.hashed_password != password
        assert verify_password(password, user.hashed_password)
    response = await client.post("/auth/login", json={"email": "pilot@example.com", "password": password})
    assert response.status_code == 200
    assert (await client.get("/auth/me")).status_code == 200
    with pytest.raises(ValueError, match="已存在"):
        await manage_users.create_user("pilot@example.com", "different-fixture-password")
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(User)) == 1


@pytest.mark.asyncio
async def test_manual_account_validation_does_not_echo_password():
    with pytest.raises(ValueError) as error:
        await manage_users.create_user("invalid-address", "sensitive-fixture-marker")
    assert "sensitive-fixture-marker" not in str(error.value)


def test_manual_account_database_failure_does_not_echo_connection_details(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["manage_users", "pilot@example.com"])
    monkeypatch.setattr(manage_users, "getpass", lambda _: "fixture-password-only")
    dispose = AsyncMock()
    monkeypatch.setattr(manage_users, "engine", SimpleNamespace(dispose=dispose))

    async def fail(*_):
        raise SQLAlchemyError("sensitive-database-fixture-marker")

    monkeypatch.setattr(manage_users, "create_user", fail)
    with pytest.raises(SystemExit) as error:
        manage_users.main()
    assert error.value.code == 1
    output = capsys.readouterr()
    assert "sensitive-database-fixture-marker" not in output.err
    assert "无法写入账号" in output.err
    dispose.assert_awaited_once()


def test_manual_account_refuses_echoed_password_fallback(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["manage_users", "pilot@example.com"])

    def unsafe_input(_prompt):
        warnings.warn("Cannot control echo on the terminal", manage_users.GetPassWarning)
        raise AssertionError("must stop before reading a password")

    monkeypatch.setattr(manage_users, "getpass", unsafe_input)
    with pytest.raises(SystemExit) as error:
        manage_users.main()
    assert error.value.code == 1
    assert "交互终端" in capsys.readouterr().err
