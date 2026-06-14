"""Characterization tests for the SQLite persistence layer.

These pin the public behavior of investigations.py / seeds.py / presets.py so
the Phase-3 unification (shared connection/repository layer) can be proven to
preserve it. All three modules are redirected at one temp DB by `temp_db`.
"""
import pytest

import investigations
import presets
import seeds


# ── investigations ─────────────────────────────────────────────────────────

def test_save_and_load_investigation(temp_db):
    investigations.init_db()
    inv_id = investigations.save_investigation(
        query="q", refined_query="rq", model="m", preset_label="p",
        sources=[{"title": "t", "link": "http://l.onion"}],
        summary="s", status="active", tags="alpha, beta",
    )
    inv = investigations.load_one(inv_id)
    assert inv["query"] == "q"
    assert inv["sources"] == [{"title": "t", "link": "http://l.onion"}]
    assert inv["tags_list"] == ["alpha", "beta"]
    assert inv["status"] == "active"


def test_update_status_validates(temp_db):
    investigations.init_db()
    inv_id = investigations.save_investigation("q", "", "", "", [], "")
    investigations.update_status(inv_id, "closed")
    assert investigations.load_one(inv_id)["status"] == "closed"
    with pytest.raises(ValueError):
        investigations.update_status(inv_id, "not-a-status")


def test_tags_roundtrip_and_aggregate(temp_db):
    investigations.init_db()
    inv_id = investigations.save_investigation("q", "", "", "", [], "")
    investigations.update_tags(inv_id, "x, y")
    assert investigations.load_one(inv_id)["tags_list"] == ["x", "y"]
    assert investigations.get_all_tags() == ["x", "y"]


def test_delete_investigation(temp_db):
    investigations.init_db()
    inv_id = investigations.save_investigation("q", "", "", "", [], "")
    investigations.delete_investigation(inv_id)
    assert investigations.load_one(inv_id) is None


# ── seeds ──────────────────────────────────────────────────────────────────

def test_add_seed_normalizes_and_is_idempotent(temp_db):
    s1 = seeds.add_seed("http://x.onion/", "Name")
    assert s1["url"] == "http://x.onion"   # trailing slash stripped
    assert s1["name"] == "Name"
    assert s1["crawled"] == 0
    s2 = seeds.add_seed("http://x.onion", "Different")
    assert s2["id"] == s1["id"]            # same row returned, not duplicated


def test_mark_crawled_with_content_sets_loaded(temp_db):
    s = seeds.add_seed("http://y.onion", "Y")
    seeds.mark_crawled(s["id"], status_code=200, content="hello")
    refreshed = seeds.get_seed_by_url("http://y.onion")
    assert refreshed["crawled"] == 1
    assert refreshed["loaded"] == 1
    assert refreshed["content"] == "hello"


def test_delete_seed(temp_db):
    s = seeds.add_seed("http://z.onion", "Z")
    seeds.delete_seed(s["id"])
    assert seeds.get_seed_by_url("http://z.onion") is None


# ── presets ────────────────────────────────────────────────────────────────

def test_create_preset_returns_custom_key(temp_db):
    p = presets.create_preset("MyDomain", "You are an expert.", "desc")
    assert p["name"] == "MyDomain"
    assert p["key"] == f"custom:{p['id']}"
    assert presets.is_custom_key(p["key"]) is True


def test_create_preset_rejects_duplicate_name(temp_db):
    presets.create_preset("Dup", "prompt")
    with pytest.raises(ValueError):
        presets.create_preset("Dup", "another prompt")


def test_create_preset_rejects_empty(temp_db):
    with pytest.raises(ValueError):
        presets.create_preset("", "prompt")
    with pytest.raises(ValueError):
        presets.create_preset("Name", "")


def test_update_preset_partial(temp_db):
    p = presets.create_preset("Editable", "original prompt", "old desc")
    updated = presets.update_preset(p["id"], description="new desc")
    assert updated["description"] == "new desc"
    assert updated["name"] == "Editable"          # untouched
    assert updated["system_prompt"] == "original prompt"


def test_delete_preset(temp_db):
    p = presets.create_preset("Temp", "prompt")
    presets.delete_preset(p["id"])
    assert presets.get_preset(p["id"]) is None
