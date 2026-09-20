import asyncio

from app.main import health_check


def test_health_check() -> None:
    response = asyncio.run(health_check())
    assert response["status"] == "ok"
