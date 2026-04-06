"""Tests for near-miss detection."""

import json
import time
from dotscope.storage.near_miss import (
    extract_warning_pairs,
    detect_near_misses,
    NearMiss,
    store_near_misses,
    load_recent_near_misses,
    save_session_scopes,
    load_session_scopes,
)


class TestWarningPairExtraction:
    def test_never_use_pattern(self):
        context = "Never call .delete() on User, use .deactivate() instead"
        pairs = extract_warning_pairs("auth", context)
        assert len(pairs) == 1
        assert "delete" in pairs[0].anti_pattern
        assert "deactivate" in pairs[0].safe_pattern

    def test_dont_use_pattern(self):
        context = "Don't use raw SQL, use the ORM instead"
        pairs = extract_warning_pairs("db", context)
        assert len(pairs) == 1
        assert "raw" in pairs[0].anti_pattern.lower()

    def test_avoid_pattern(self):
        context = "Avoid force push — use --force-with-lease"
        pairs = extract_warning_pairs("git", context)
        assert len(pairs) == 1

    def test_deprecated_pattern(self):
        context = "get_user is deprecated, use fetch_user instead"
        pairs = extract_warning_pairs("api", context)
        assert len(pairs) == 1
        assert "get_user" in pairs[0].anti_pattern
        assert "fetch_user" in pairs[0].safe_pattern

    def test_no_pairs_from_normal_text(self):
        context = "This module handles authentication and session management."
        pairs = extract_warning_pairs("auth", context)
        assert len(pairs) == 0

    def test_multiple_pairs(self):
        context = (
            "Never call .delete(), use .deactivate()\n"
            "Don't use raw SQL, use ORM queries\n"
        )
        pairs = extract_warning_pairs("auth", context)
        assert len(pairs) == 2


class TestNearMissDetection:
    def test_detects_safe_pattern_used(self):
        scope_contexts = {
            "auth": "Never call .delete() on User, use .deactivate() instead",
        }
        diff = "+    user.deactivate()\n+    user.save()"
        nms = detect_near_misses(diff, scope_contexts)
        assert len(nms) == 1
        assert "deactivate" in nms[0].event
        assert "delete" in nms[0].event

    def test_no_near_miss_when_anti_pattern_present(self):
        scope_contexts = {
            "auth": "Never call .delete(), use .deactivate()",
        }
        diff = "+    user.delete()  # oops"
        nms = detect_near_misses(diff, scope_contexts)
        assert len(nms) == 0

    def test_no_near_miss_when_neither_present(self):
        scope_contexts = {
            "auth": "Never call .delete(), use .deactivate()",
        }
        diff = "+    print('hello')"
        nms = detect_near_misses(diff, scope_contexts)
        assert len(nms) == 0

    def test_empty_diff(self):
        assert detect_near_misses("", {"auth": "Never X, use Y"}) == []

    def test_multiple_scopes(self):
        scope_contexts = {
            "auth": "Never call .delete(), use .deactivate()",
            "db": "Don't use raw SQL, use ORM queries",
        }
        diff = "+    user.deactivate()\n+    db.query.filter()"
        nms = detect_near_misses(diff, scope_contexts)
        # Should detect near-misses from both scopes
        assert len(nms) >= 1


class TestNearMissStorage:
    def test_store_and_load(self, tmp_path):
        root = str(tmp_path)
        (tmp_path / ".dotscope").mkdir()

        nm = NearMiss(
            scope="auth",
            event="Agent used .deactivate() instead of .delete()",
            context_used="Never call .delete()",
            potential_impact="Would have violated soft-delete",
        )
        store_near_misses(root, [nm])

        loaded = load_recent_near_misses(root, "auth")
        assert len(loaded) == 1
        assert "deactivate" in loaded[0]["event"]

    def test_scope_filtering(self, tmp_path):
        root = str(tmp_path)
        (tmp_path / ".dotscope").mkdir()

        store_near_misses(root, [
            NearMiss("auth", "event1", "ctx1", "impact1"),
            NearMiss("api", "event2", "ctx2", "impact2"),
        ])

        assert len(load_recent_near_misses(root, "auth")) == 1
        assert len(load_recent_near_misses(root, "api")) == 1
        assert len(load_recent_near_misses(root, "payments")) == 0

    def test_age_filtering(self, tmp_path):
        root = str(tmp_path)
        path = tmp_path / ".dotscope" / "near_misses.jsonl"
        path.parent.mkdir(parents=True)
        # Write an old entry
        path.write_text(json.dumps({
            "scope": "auth",
            "event": "old",
            "context_used": "ctx",
            "potential_impact": "imp",
            "timestamp": time.time() - 200000,  # >48h ago
        }) + "\n")

        assert len(load_recent_near_misses(root, "auth")) == 0


class TestSessionScopes:
    def test_save_and_load(self, tmp_path):
        root = str(tmp_path)
        (tmp_path / ".dotscope").mkdir()

        save_session_scopes(root, ["auth", "api"])
        loaded = load_session_scopes(root)
        assert loaded == ["auth", "api"]

    def test_expired_session(self, tmp_path):
        root = str(tmp_path)
        path = tmp_path / ".dotscope" / "last_session.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "scopes": ["auth"],
            "ended_at": time.time() - 20000,  # >4h ago
        }))

        assert load_session_scopes(root) == []
