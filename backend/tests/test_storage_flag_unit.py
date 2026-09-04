"""
Unit tests for the new backend/storage.py feature flag (iteration 11).
Runs fully offline — no DB, no network. Verifies the module contract that
server.py relies on (is_enabled / init_storage no-op / put+get raise).
"""

import importlib
import os
import sys

import pytest

sys.path.insert(0, "/app/backend")


def _reload_storage(env: dict):
    saved = {k: os.environ.get(k) for k in ("OBJECT_STORAGE_ENABLED", "EMERGENT_LLM_KEY")}
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        import storage

        return importlib.reload(storage)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_disabled_by_default():
    st = _reload_storage({"OBJECT_STORAGE_ENABLED": None, "EMERGENT_LLM_KEY": None})
    assert st.is_enabled() is False
    assert st.init_storage() is None  # no network call, no raise
    with pytest.raises(RuntimeError):
        st.put_object("a/b.jpg", b"x", "image/jpeg")
    with pytest.raises(RuntimeError):
        st.get_object("a/b.jpg")


def test_disabled_when_flag_true_but_no_key():
    st = _reload_storage({"OBJECT_STORAGE_ENABLED": "true", "EMERGENT_LLM_KEY": None})
    assert st.is_enabled() is False


def test_enabled_only_with_flag_and_key():
    st = _reload_storage({"OBJECT_STORAGE_ENABLED": "true", "EMERGENT_LLM_KEY": "sk-test"})
    assert st.is_enabled() is True


def test_flag_is_case_insensitive_and_ignores_other_values():
    assert _reload_storage({"OBJECT_STORAGE_ENABLED": "TRUE", "EMERGENT_LLM_KEY": "k"}).is_enabled() is True
    assert _reload_storage({"OBJECT_STORAGE_ENABLED": "1", "EMERGENT_LLM_KEY": "k"}).is_enabled() is False
