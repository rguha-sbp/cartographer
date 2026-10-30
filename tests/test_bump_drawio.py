import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("bump_drawio", ROOT / "scripts" / "bump_drawio.py")
bump = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bump)

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def release(tag, published, *, draft=False, prerelease=False, assets=("draw.war",)):
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "published_at": published,
        "html_url": f"https://example.invalid/{tag}",
        "assets": [{"name": n, "browser_download_url": f"https://example.invalid/{tag}/{n}"} for n in assets],
    }


class TestVersion:
    def test_parse_strips_v_and_compares_numerically(self):
        assert bump.parse_version("v32.10.0") > bump.parse_version("32.9.9")

    def test_equal_versions(self):
        assert bump.parse_version("v1.2.3") == bump.parse_version("1.2.3")

    @pytest.mark.parametrize("tag", ["", "latest", "v1.x", "1.2-beta"])
    def test_rejects_non_numeric(self, tag):
        with pytest.raises(ValueError):
            bump.parse_version(tag)


class TestSelect:
    def test_newest_eligible(self):
        releases = [
            release("v32.5.6", "2026-10-29T00:00:00Z"),
            release("v32.5.5", "2026-09-01T00:00:00Z"),
            release("v32.5.4", "2026-08-01T00:00:00Z"),
        ]
        assert bump.select_release(releases, NOW).version == "32.5.5"

    def test_age_boundary_is_inclusive(self):
        assert bump.select_release([release("v2.0.0", "2026-10-23T12:00:00Z")], NOW).version == "2.0.0"
        assert bump.select_release([release("v2.0.0", "2026-10-23T12:00:01Z")], NOW) is None

    def test_skips_draft_prerelease_and_missing_asset(self):
        releases = [
            release("v9.0.0", "2026-01-01T00:00:00Z", draft=True),
            release("v8.0.0", "2026-01-01T00:00:00Z", prerelease=True),
            release("v7.0.0", "2026-01-01T00:00:00Z", assets=("draw.zip",)),
            release("v6.0.0", "2026-01-01T00:00:00Z"),
        ]
        picked = bump.select_release(releases, NOW)
        assert picked.version == "6.0.0"
        assert picked.url == "https://example.invalid/v6.0.0/draw.war"
        assert picked.page == "https://example.invalid/v6.0.0"

    def test_picks_highest_version_not_first_listed(self):
        releases = [release("v1.0.0", "2026-01-01T00:00:00Z"), release("v1.1.0", "2026-01-02T00:00:00Z")]
        assert bump.select_release(releases, NOW).version == "1.1.0"

    def test_ignores_unparseable_tags(self):
        assert bump.select_release([release("nightly", "2026-01-01T00:00:00Z")], NOW) is None

    def test_empty(self):
        assert bump.select_release([], NOW) is None


PIN = {"name": "n", "version": "1.0.0", "url": "u", "sha256": "s", "licence": "l", "source": "src"}


class TestRewrite:
    def test_keeps_key_order_and_trailing_newline(self):
        picked = bump.Release("1.1.0", "https://x/draw.war", "https://x/page")
        text = bump.render_pin(PIN, picked, "abc")
        assert text.endswith("}\n")
        data = json.loads(text)
        assert list(data) == list(PIN)
        assert (data["version"], data["url"], data["sha256"]) == ("1.1.0", "https://x/draw.war", "abc")
        assert data["licence"] == "l"

    def test_is_newer(self):
        assert bump.is_newer("1.0.1", "1.0.0")
        assert not bump.is_newer("1.0.0", "1.0.0")
        assert not bump.is_newer("0.9.0", "1.0.0")
