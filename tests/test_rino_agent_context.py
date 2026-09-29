from rino_agent.context import build_context


def test_context_builder_allows_only_known_bounded_sources():
    context = build_context({"memory": "remember", "unknown": "drop", "vision": "screen"})
    assert "remember" in context and "screen" in context and "drop" not in context


def test_context_builder_removes_nulls_and_bounds_size():
    context = build_context({"memory": "a\0" + "x" * 3_000})
    assert "\0" not in context and len(context) < 2_100
