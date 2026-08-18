from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api.v1.social_broadcast import (
    GenerateRequest,
    ScheduleRequest,
    SocialConfigUpdate,
    _get_config,
    _get_store,
    _require_admin,
    _serialize_post,
)


def test_social_schemas_and_serializer():
    cfg = SocialConfigUpdate(brand_name="Demo", networks_enabled=["instagram"])
    assert cfg.brand_voice == "professionnel"
    req = GenerateRequest(topic="Promo", networks=["facebook"])
    assert req.generate_image is True
    schedule = ScheduleRequest(topic="Launch", networks=["instagram"], scheduled_at="2026-08-15T10:00:00Z")
    assert schedule.scheduled_at.tzinfo is not None
    now = datetime.now(timezone.utc)
    data = _serialize_post(SimpleNamespace(id=1, network="instagram", post_type="post", status="published", caption="x", image_url=None, image_prompt=None, external_post_id=None, scheduled_at=None, published_at=now, error=None, source="ai", product_id=None, created_at=now))
    assert data["id"] == 1 and data["published_at"] == now.isoformat()


def test_require_admin_rbac():
    import api.v1.social_broadcast as module
    token = module.current_user_role.set("viewer")
    try:
        with pytest.raises(HTTPException) as exc:
            _require_admin()
        assert exc.value.status_code == 403
    finally:
        module.current_user_role.reset(token)


@pytest.mark.asyncio
async def test_get_store_and_config_paths():
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = SimpleNamespace(id=5)
    db.execute.return_value = result
    with patch("api.v1.social_broadcast._sid", return_value=5):
        store = await _get_store(db)
    assert store.id == 5
    config_result = MagicMock()
    config_result.scalar_one_or_none.return_value = None
    db.execute.return_value = config_result
    assert await _get_config(db, 5) is None

    with patch("api.v1.social_broadcast._sid", return_value=None):
        with pytest.raises(HTTPException) as exc:
            await _get_store(db)
    assert exc.value.status_code == 401


def test_require_admin_accepts_admin_role():
    import api.v1.social_broadcast as module
    token = module.current_user_role.set("admin")
    try:
        assert _require_admin() is None
    finally:
        module.current_user_role.reset(token)


@pytest.mark.asyncio
async def test_get_config_returns_defaults_and_persisted_values():
    import api.v1.social_broadcast as module
    db = AsyncMock()
    store = SimpleNamespace(id=5, name="Demo")
    with patch.object(module, "_get_store", new=AsyncMock(return_value=store)), patch.object(module, "_get_config", new=AsyncMock(return_value=None)):
        default = await module.get_config(db)
    assert default["configured"] is False and default["networks_enabled"] == ["instagram", "facebook"]
    config = SimpleNamespace(brand_name="Demo", brand_voice="direct", default_language="fr", hashtags='["#auto"]', emoji_style="none", image_style="clean", image_colors="blue", watermark_text="D", networks_enabled='["instagram"]', auto_schedule=True, post_times='["10:00"]', post_days='[1]', timezone="UTC", max_posts_per_day=2)
    with patch.object(module, "_get_store", new=AsyncMock(return_value=store)), patch.object(module, "_get_config", new=AsyncMock(return_value=config)):
        saved = await module.get_config(db)
    assert saved["configured"] is True and saved["hashtags"] == ["#auto"] and saved["post_days"] == [1]


@pytest.mark.asyncio
async def test_generate_preview_uses_custom_caption_and_image_without_external_calls():
    import api.v1.social_broadcast as module
    db = AsyncMock()
    store = SimpleNamespace(id=5, name="Demo")
    body = module.GenerateRequest(topic="Promo", networks=["instagram"], custom_caption="Caption", custom_image_url="https://img.test/a.png")
    token = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_get_store", new=AsyncMock(return_value=store)), patch.object(module, "_get_config", new=AsyncMock(return_value=None)):
            result = await module.generate_preview(body, db)
    finally:
        module.current_user_role.reset(token)
    assert result["ok"] is True and result["caption"] == "Caption" and result["image_url"].endswith("a.png")
    assert result["dalle_error"] is None


@pytest.mark.asyncio
async def test_social_post_history_get_delete_and_cancel_paths():
    import api.v1.social_broadcast as module
    db = AsyncMock()
    store = SimpleNamespace(id=5)
    now = datetime.now(timezone.utc)
    post = SimpleNamespace(id=3, network="instagram", post_type="post", status="scheduled", caption="c", image_url=None, image_prompt=None, external_post_id=None, scheduled_at=now, published_at=None, error=None, source="scheduled", product_id=None, created_at=now, celery_task_id=None)
    with patch.object(module, "_get_store", new=AsyncMock(return_value=store)):
        list_result = MagicMock(); list_result.scalars.return_value.all.return_value = [post]
        db.execute.return_value = list_result
        listed = await module.list_posts(db=db)
    assert listed[0]["id"] == 3
    with patch.object(module, "_get_store", new=AsyncMock(return_value=store)):
        get_result = MagicMock(); get_result.scalar_one_or_none.return_value = post
        db.execute.return_value = get_result
        fetched = await module.get_post(3, db)
    assert fetched["network"] == "instagram"
    with patch.object(module, "_get_store", new=AsyncMock(return_value=store)):
        missing = MagicMock(); missing.scalar_one_or_none.return_value = None
        db.execute.return_value = missing
        with pytest.raises(HTTPException) as exc:
            await module.get_post(404, db)
    assert exc.value.status_code == 404
    token = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_get_store", new=AsyncMock(return_value=store)):
            db.execute.return_value = get_result
            await module.delete_post(3, db)
    finally:
        module.current_user_role.reset(token)
    db.delete.assert_awaited_once_with(post)


@pytest.mark.asyncio
async def test_cancel_scheduled_marks_post_cancelled_and_handles_missing():
    import api.v1.social_broadcast as module
    db = AsyncMock(); store = SimpleNamespace(id=5)
    now = datetime.now(timezone.utc)
    post = SimpleNamespace(id=4, network="facebook", post_type="post", status="scheduled", caption="c", image_url=None, image_prompt=None, external_post_id=None, scheduled_at=now, published_at=None, error=None, source="scheduled", product_id=None, created_at=now, celery_task_id=None)
    token = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_get_store", new=AsyncMock(return_value=store)):
            found = MagicMock(); found.scalar_one_or_none.return_value = post
            db.execute.return_value = found
            await module.cancel_scheduled(4, db)
            assert post.status == "cancelled"
            db.commit.assert_awaited()
            missing = MagicMock(); missing.scalar_one_or_none.return_value = None
            db.execute.return_value = missing
            with pytest.raises(HTTPException) as exc:
                await module.cancel_scheduled(999, db)
        assert exc.value.status_code == 404
    finally:
        module.current_user_role.reset(token)


@pytest.mark.asyncio
async def test_update_config_creates_config_and_audits():
    import api.v1.social_broadcast as module
    db = AsyncMock(); db.add = MagicMock(); store = SimpleNamespace(id=5); request = SimpleNamespace()
    config = None
    body = module.SocialConfigUpdate(brand_name="Demo", hashtags=["#x"], networks_enabled=["facebook"], auto_schedule=True, max_posts_per_day=4)
    token = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_get_store", new=AsyncMock(return_value=store)), patch.object(module, "_get_config", new=AsyncMock(return_value=config)), patch.object(module, "_audit", new=AsyncMock()) as audit:
            result = await module.update_config(body, request, db)
    finally:
        module.current_user_role.reset(token)
    assert result["ok"] is True
    created = db.add.call_args.args[0]
    assert created.store_id == 5 and created.brand_name == "Demo" and created.networks_enabled == '["facebook"]'
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_preview_reports_dalle_error_and_publish_requires_network():
    import api.v1.social_broadcast as module
    db = AsyncMock(); store = SimpleNamespace(id=5, name="Demo")
    body = module.GenerateRequest(topic="Promo", networks=["instagram"], generate_image=True)
    token = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_get_store", new=AsyncMock(return_value=store)), patch.object(module, "_get_config", new=AsyncMock(return_value=None)), patch("services.social_publisher.generate_caption", new=AsyncMock(return_value="Caption")), patch("services.social_publisher.generate_image_dalle", new=AsyncMock(side_effect=RuntimeError("image offline"))):
            result = await module.generate_preview(body, db)
        assert result["caption"] == "Caption" and result["image_url"] is None and "offline" in result["dalle_error"]
        with patch.object(module, "_get_store", new=AsyncMock(return_value=store)), patch.object(module, "_get_config", new=AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc:
                await module.publish_now(module.PublishRequest(topic="Promo", networks=[]), request=SimpleNamespace(), db=db)
    finally:
        module.current_user_role.reset(token)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_publish_now_runs_pipeline_and_audits_result():
    import api.v1.social_broadcast as module
    db = AsyncMock(); store = SimpleNamespace(id=5, name="Demo"); request = SimpleNamespace()
    body = module.PublishRequest(topic="Launch", networks=["instagram"], custom_caption="Hello", generate_image=False)
    pipeline_result = {"published": ["instagram"], "failed": []}
    token = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_get_store", new=AsyncMock(return_value=store)), patch.object(module, "_get_config", new=AsyncMock(return_value=None)), patch.object(module, "_audit", new=AsyncMock()) as audit, patch("services.social_publisher.run_publish_pipeline", new=AsyncMock(return_value=pipeline_result)) as pipeline:
            result = await module.publish_now(body, request, db)
    finally:
        module.current_user_role.reset(token)
    assert result == pipeline_result
    pipeline.assert_awaited_once()
    audit.assert_awaited_once()
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_publish_product_returns_404_when_product_is_missing():
    import api.v1.social_broadcast as module
    db = AsyncMock(); store = SimpleNamespace(id=5, name="Demo")
    result = MagicMock(); result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    body = module.ProductPublishRequest(product_id=99, networks=["facebook"], generate_image=False)
    token = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_get_store", new=AsyncMock(return_value=store)), patch.object(module, "_get_config", new=AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc:
                await module.publish_product(body, SimpleNamespace(), db)
    finally:
        module.current_user_role.reset(token)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_schedule_post_creates_entries_and_fails_open_when_celery_unavailable():
    import api.v1.social_broadcast as module
    from datetime import timedelta
    db = AsyncMock(); db.add = MagicMock(); store = SimpleNamespace(id=5, name="Demo")
    request = SimpleNamespace()
    body = module.ScheduleRequest(topic="Launch", networks=["instagram", "facebook"], scheduled_at=datetime.now(timezone.utc) + timedelta(days=2), custom_caption="Scheduled", generate_image=False)
    token = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_get_store", new=AsyncMock(return_value=store)), patch.object(module, "_get_config", new=AsyncMock(return_value=None)), patch.object(module, "_audit", new=AsyncMock()) as audit, patch("services.social_publisher.generate_caption", new=AsyncMock(return_value="Scheduled")):
            result = await module.schedule_post(body, request, db)
    finally:
        module.current_user_role.reset(token)
    assert result["ok"] is True and result["celery_task_id"] is None
    assert result["networks"] == ["instagram", "facebook"]
    assert db.add.call_count == 2 and db.commit.await_count == 1
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_schedule_post_rejects_past_date():
    import api.v1.social_broadcast as module
    from datetime import timedelta
    db = AsyncMock(); store = SimpleNamespace(id=5, name="Demo")
    body = module.ScheduleRequest(topic="Past", networks=["instagram"], scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    token = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_get_store", new=AsyncMock(return_value=store)), patch.object(module, "_get_config", new=AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc:
                await module.schedule_post(body, SimpleNamespace(), db)
    finally:
        module.current_user_role.reset(token)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_publish_product_uses_existing_image_and_returns_product():
    import api.v1.social_broadcast as module
    db = AsyncMock(); store = SimpleNamespace(id=5, name="Demo"); request = SimpleNamespace()
    product = SimpleNamespace(id=7, name="Auto", price=100.0, description="Description", images=["https://img.test/auto.png"])
    query_result = MagicMock(); query_result.scalar_one_or_none.return_value = product
    db.execute.return_value = query_result
    body = module.ProductPublishRequest(product_id=7, networks=["instagram"], generate_image=False, custom_caption="Buy")
    pipeline_result = {"published": ["instagram"], "failed": []}
    token = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_get_store", new=AsyncMock(return_value=store)), patch.object(module, "_get_config", new=AsyncMock(return_value=None)), patch.object(module, "_audit", new=AsyncMock()) as audit, patch("services.social_publisher.run_publish_pipeline", new=AsyncMock(return_value=pipeline_result)) as pipeline:
            result = await module.publish_product(body, request, db)
    finally:
        module.current_user_role.reset(token)
    assert result["product"] == {"id": 7, "name": "Auto"}
    assert result["published"] == ["instagram"]
    assert pipeline.await_args.kwargs["custom_image_url"] == "https://img.test/auto.png"
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_posts_with_filters_and_list_scheduled_serialize_results():
    import api.v1.social_broadcast as module
    db = AsyncMock(); store = SimpleNamespace(id=5)
    now = datetime.now(timezone.utc)
    post = SimpleNamespace(id=8, network="facebook", post_type="post", status="scheduled", caption="c", image_url=None, image_prompt=None, external_post_id=None, scheduled_at=now, published_at=None, error=None, source="scheduled", product_id=None, created_at=now, celery_task_id=None)
    result = MagicMock(); result.scalars.return_value.all.return_value = [post]
    db.execute.return_value = result
    with patch.object(module, "_get_store", new=AsyncMock(return_value=store)):
        listed = await module.list_posts(status="scheduled", network="facebook", limit=10, offset=2, db=db)
        scheduled = await module.list_scheduled(db)
    assert listed[0]["id"] == 8 and scheduled[0]["status"] == "scheduled"


@pytest.mark.asyncio
async def test_cancel_scheduled_handles_revoke_failure_and_marks_cancelled():
    import api.v1.social_broadcast as module
    db = AsyncMock(); store = SimpleNamespace(id=5)
    post = SimpleNamespace(id=9, network="instagram", post_type="post", status="scheduled", caption="c", image_url=None, image_prompt=None, external_post_id=None, scheduled_at=datetime.now(timezone.utc), published_at=None, error=None, source="scheduled", product_id=None, created_at=datetime.now(timezone.utc), celery_task_id="task-9")
    result = MagicMock(); result.scalar_one_or_none.return_value = post
    db.execute.return_value = result
    token = module.current_user_role.set("admin")
    try:
        with patch.object(module, "_get_store", new=AsyncMock(return_value=store)), patch("services.celery_app.celery_app.control.revoke", side_effect=RuntimeError("broker offline")):
            await module.cancel_scheduled(9, db)
    finally:
        module.current_user_role.reset(token)
    assert post.status == "cancelled" and db.commit.await_count == 1
