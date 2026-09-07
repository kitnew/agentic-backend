from control_plane.application.command_support import (
    opaque_concurrency_token,
    request_fingerprint,
)


def test_logical_request_fingerprint_is_deterministic() -> None:
    first = {"value": {"enabled": True, "labels": ["a", "b"]}, "version": 1}
    reordered = {"version": 1, "value": {"labels": ["a", "b"], "enabled": True}}

    assert request_fingerprint(first) == request_fingerprint(reordered)
    assert request_fingerprint(first) != request_fingerprint({**first, "version": 2})


def test_opaque_concurrency_token_tracks_only_supplied_semantic_state() -> None:
    first = opaque_concurrency_token({"active": 1, "draft": None})

    assert first == opaque_concurrency_token({"draft": None, "active": 1})
    assert first != opaque_concurrency_token({"active": 2, "draft": None})
    assert len(first) == 43
