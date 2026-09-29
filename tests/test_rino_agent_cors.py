from rino_agent.main import app


def test_cors_is_restricted_to_local_sillytavern_origins():
    cors = next(middleware for middleware in app.user_middleware if middleware.cls.__name__ == "CORSMiddleware")
    assert set(cors.kwargs["allow_origins"]) == {"http://127.0.0.1:8000", "http://localhost:8000"}
    assert cors.kwargs["allow_headers"] == ["Authorization", "Content-Type"]
