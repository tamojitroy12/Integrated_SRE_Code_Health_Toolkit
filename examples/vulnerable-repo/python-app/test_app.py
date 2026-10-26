"""Minimal tests so fix proposals have a baseline to run (pytest)."""

import app


def test_hash_token_is_deterministic():
    assert app.hash_token("a") == app.hash_token("a")


def test_requests_importable():
    import requests

    assert requests.__version__
