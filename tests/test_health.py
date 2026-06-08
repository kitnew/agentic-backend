from app.api.routes.health import health


def test_health_works():
    assert health() == {"status": "ok"}
