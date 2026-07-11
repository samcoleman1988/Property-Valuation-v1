"""Deployment/version diagnostics.

Lets a user (or the developer) see at a glance which release a running
instance is actually serving. This exists specifically because of a
reported Streamlit Cloud incident where the running app appeared to pair
new app.py code with an older transport.py — most likely a stale or
partially refreshed cloud runtime at the moment of the request (see
app.py's _ensure_recommendation() and _safe_assess_location() for the
defensive handling). The exact platform-side mechanism was never
confirmed, since the unredacted deployment logs weren't captured — this
diagnostic exists so that class of question can be answered by looking
at the sidebar instead of guessing from a crash.
"""

import os

from .valuation_engine_v2 import MODEL_VERSION, MODEL_VERSION_DATE

# Bump alongside RELEASE_NOTES.md entries — this is the app-level release
# tag, distinct from MODEL_VERSION (which tracks the valuation engine
# baseline specifically and lives in valuation_engine_v2.py).
APP_VERSION = "v1-beta"


def _get_deployed_commit() -> str:
    """Reads DEPLOYED_COMMIT the same way get_epc_key() reads the EPC
    key: Streamlit Cloud secrets first, then a local OS env var / .env
    file. Streamlit Cloud's only user-facing config surface is its
    Secrets box (there's no separate "environment variables" section),
    so this must check st.secrets to actually work when set there.

    Deliberately NOT shelled out to `git rev-parse HEAD` at runtime —
    that would require git to be present and reliable in the hosting
    environment, which isn't guaranteed. This value is optional and
    shows "not set" rather than being fabricated if absent.
    """
    try:
        import streamlit as st
        if hasattr(st, "secrets") and "DEPLOYED_COMMIT" in st.secrets:
            return st.secrets["DEPLOYED_COMMIT"]
    except Exception:
        pass
    return os.environ.get("DEPLOYED_COMMIT", "not set")


def get_deployment_info() -> dict:
    """Returns the app version, valuation baseline version, and (if set)
    the deployed commit hash for display in the UI.
    """
    return {
        "app_version": APP_VERSION,
        "baseline_version": MODEL_VERSION,
        "baseline_version_date": MODEL_VERSION_DATE,
        "deployed_commit": _get_deployed_commit(),
    }
