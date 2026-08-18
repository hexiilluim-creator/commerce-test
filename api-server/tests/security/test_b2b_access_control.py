from __future__ import annotations

import asyncio

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.v1.b2b_portal import router
from middleware.tenant import current_tenant_id
from models.database import Base, Store, get_db


def test_b2b_mutations_require_manager_or_admin() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with Session() as session:
            session.add(Store(id=1, name="AC", slug="ac-sec", default_tax_country="FR", country="FR"))
            await session.commit()

    asyncio.run(prepare())

    app = FastAPI()

    @app.middleware("http")
    async def inject_viewer(request: Request, call_next):
        token = current_tenant_id.set(1)
        request.state.jwt_payload = {"role": "viewer", "user_id": 99}
        request.state.user_id = 99
        request.state.role = "viewer"
        try:
            return await call_next(request)
        finally:
            current_tenant_id.reset(token)

    async def override_get_db():
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.include_router(router)
    client = TestClient(app)

    res = client.post("/b2b/accounts", json={"account_type": "garage", "name": "Forbidden Co"})
    assert res.status_code == 403

    asyncio.run(engine.dispose())
