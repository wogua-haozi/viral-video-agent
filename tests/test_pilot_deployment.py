"""Resolve the actual Compose merge using only disposable configuration values."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def compose_project(tmp_path):
    if not shutil.which("docker"):
        pytest.skip("Docker Compose CLI is unavailable")
    for name in ("docker-compose.yml", "docker-compose.local.yml", "docker-compose.pilot.yml"):
        shutil.copyfile(ROOT / name, tmp_path / name)
    # The base file's env_file must never read the real working environment in this test.
    (tmp_path / ".env").write_text("", encoding="utf-8")
    (tmp_path / "fixture.env").write_text(
        "POSTGRES_PASSWORD=fixture-only-database-password\n"
        "JWT_SECRET=fixture-only-random-jwt-secret-with-enough-characters\n"
        "PILOT_DOMAIN=pilot.example.invalid\nPILOT_GATE_USER=fixture-pilot\n"
        "PILOT_GATE_HASH=fixture-only-config-placeholder\n",
        encoding="utf-8",
    )
    return tmp_path


def resolve(project, *overrides):
    command = ["docker", "compose", "--env-file", "fixture.env", "-f", "docker-compose.yml"]
    for override in overrides:
        command += ["-f", override]
    result = subprocess.run(command + ["config", "--format", "json"], cwd=project, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["services"]


@pytest.mark.parametrize("overrides", [(), ("docker-compose.local.yml",)])
def test_development_ports_bind_only_to_loopback(compose_project, overrides):
    services = resolve(compose_project, *overrides)
    for service in services.values():
        for port in service.get("ports", []):
            assert port["host_ip"] == "127.0.0.1"
    assert services["mcp-server"]["environment"]["REDIS_URL"] == "redis://redis:6379/0"
    assert services["mcp-server"]["depends_on"]["redis"]["condition"] == "service_healthy"


@pytest.mark.parametrize("overrides", [("docker-compose.pilot.yml",), ("docker-compose.local.yml", "docker-compose.pilot.yml")])
def test_pilot_merge_has_one_controlled_entry_and_no_backend_bypass(compose_project, overrides):
    services = resolve(compose_project, *overrides)
    published = {name for name, service in services.items() if service.get("ports")}
    assert published == {"pilot-entry"}
    assert {int(p["published"]) for p in services["pilot-entry"]["ports"]} == {80, 443}
    assert services["app"]["environment"]["REGISTRATION_ENABLED"] == "false"
    assert services["app"]["environment"]["APP_ENV"] == "production"
    assert services["worker"]["environment"]["APP_ENV"] == "production"
    assert services["mcp-server"]["environment"]["REDIS_URL"] == "redis://redis:6379/0"


def test_pilot_configuration_refuses_missing_entry_credentials(compose_project):
    (compose_project / "fixture.env").write_text("POSTGRES_PASSWORD=fixture-only\nJWT_SECRET=fixture-only\n", encoding="utf-8")
    command = ["docker", "compose", "--env-file", "fixture.env", "-f", "docker-compose.yml", "-f", "docker-compose.pilot.yml", "config", "--quiet"]
    result = subprocess.run(command, cwd=compose_project, capture_output=True, text=True)
    assert result.returncode != 0
    assert "PILOT_" in result.stderr


def test_pilot_can_use_an_encoded_existing_database_url(compose_project):
    encoded = "postgresql+asyncpg://fixture:fixture%40password%2F%23@postgres:5432/pilot"
    with (compose_project / "fixture.env").open("a", encoding="utf-8") as stream:
        stream.write(f"PILOT_DATABASE_URL={encoded}\n")
    services = resolve(compose_project, "docker-compose.pilot.yml")
    assert services["app"]["environment"]["DATABASE_URL"] == encoded
    assert services["worker"]["environment"]["DATABASE_URL"] == encoded
