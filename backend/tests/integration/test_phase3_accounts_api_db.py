from __future__ import annotations

import os

import pytest
from httpx import AsyncClient

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.skip("Set TEST_DATABASE_URL to run real PostgreSQL API integration tests.", allow_module_level=True)

os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app.db.postgres import close_db, create_all_tables  # noqa: E402
from app.main import app  # noqa: E402

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_import_facebook_account_api_with_real_db() -> None:
    await create_all_tables()
    uid = "pytest_phase3_10001"
    async with AsyncClient(app=app, base_url="http://testserver") as client:
        import_response = await client.post(
            "/api/facebook-accounts/import",
            json={"raw_text": f"{uid}|EAATEST_TOKEN"},
        )
        list_response = await client.get("/api/facebook-accounts")

    await close_db()

    assert import_response.status_code == 200
    assert import_response.json()["total"] == 1
    assert list_response.status_code == 200
    accounts = list_response.json()
    assert any(account["uid"] == uid for account in accounts)
