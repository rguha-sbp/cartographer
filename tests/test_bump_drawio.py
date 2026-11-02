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
        assert bump.select_release(releases, NOW, [], "0.0.1").version == "32.5.5"

    def test_age_boundary_is_inclusive(self):
        assert bump.select_release([release("v2.0.0", "2026-10-23T12:00:00Z")], NOW, [], "0.0.1").version == "2.0.0"
        assert bump.select_release([release("v2.0.0", "2026-10-23T12:00:01Z")], NOW, [], "0.0.1") is None

    def test_skips_draft_prerelease_and_missing_asset(self):
        releases = [
            release("v9.0.0", "2026-01-01T00:00:00Z", draft=True),
            release("v8.0.0", "2026-01-01T00:00:00Z", prerelease=True),
            release("v7.0.0", "2026-01-01T00:00:00Z", assets=("draw.zip",)),
            release("v6.0.0", "2026-01-01T00:00:00Z"),
        ]
        picked = bump.select_release(releases, NOW, [], "0.0.1")
        assert picked.version == "6.0.0"
        assert picked.url == "https://example.invalid/v6.0.0/draw.war"
        assert picked.page == "https://example.invalid/v6.0.0"

    def test_picks_highest_version_not_first_listed(self):
        releases = [release("v1.0.0", "2026-01-01T00:00:00Z"), release("v1.1.0", "2026-01-02T00:00:00Z")]
        assert bump.select_release(releases, NOW, [], "0.0.1").version == "1.1.0"

    def test_ignores_unparseable_tags(self):
        assert bump.select_release([release("nightly", "2026-01-01T00:00:00Z")], NOW, [], "0.0.1") is None

    def test_empty(self):
        assert bump.select_release([], NOW, [], "0.0.1") is None


def advisory(ghsa, *ranges, withdrawn=None):
    return {
        "ghsa_id": ghsa,
        "withdrawn_at": withdrawn,
        "vulnerabilities": [{"vulnerable_version_range": r} for r in ranges],
    }


class TestAdvisories:
    @pytest.mark.parametrize(
        ("spec", "version", "hit"),
        [
            ("<= 32.6.8", "32.6.8", True),
            ("<= 32.6.8", "32.6.9", False),
            ("<30.2.7", "30.2.7", False),
            ("< 29.7.8", "29.7.7", True),
            ("<= v30.2.6", "30.2.6", True),
            ("30.2.4", "30.2.4", True),
            ("30.2.4", "30.2.5", False),
            (">= 31.0.0, < 31.4.4", "31.2.0", True),
            (">= 31.0.0, < 31.4.4", "30.9.0", False),
            ("= 1.0.0", "1.0.0", True),
            ("> 1.0.0", "1.0.0", False),
        ],
    )
    def test_ranges_jgraph_publishes(self, spec, version, hit):
        assert bump.affects(spec, version) is hit

    @pytest.mark.parametrize("spec", ["", "all", "<= 1.x", "~1.0"])
    def test_an_unreadable_range_fails_loudly(self, spec):
        with pytest.raises(ValueError, match="range"):
            bump.affects(spec, "1.0.0")

    def test_open_advisories_skip_withdrawn_ones(self):
        advisories = [
            advisory("GHSA-a", "<= 32.6.8"),
            advisory("GHSA-b", "<= 30.2.6"),
            advisory("GHSA-c", "<= 32.6.8", withdrawn="2026-11-01T00:00:00Z"),
            advisory("GHSA-d", "< 1.0.0", ">= 32.0.0, < 33.0.0"),
        ]
        assert bump.open_advisories(advisories, "32.5.5") == ["GHSA-a", "GHSA-d"]
        assert bump.open_advisories(advisories, "33.0.0") == []


class TestSecuritySelect:
    RELEASES = (
        release("v32.6.9", "2026-10-29T00:00:00Z"),  # one day old
        release("v32.6.1", "2026-10-20T00:00:00Z"),
        release("v32.5.5", "2026-10-01T00:00:00Z"),
    )

    def test_an_affected_pin_takes_the_newest_fixed_release_at_any_age(self):
        advisories = [advisory("GHSA-a", "<= 32.6.8")]
        assert bump.select_release(self.RELEASES, NOW, advisories, "32.5.5").version == "32.6.9"

    def test_never_picks_an_affected_release(self):
        advisories = [advisory("GHSA-a", "<= 32.6.9")]
        assert bump.select_release(self.RELEASES, NOW, advisories, "32.5.5") is None
        assert bump.select_release(self.RELEASES, NOW, [advisory("GHSA-b", "= 32.6.1")], "0.0.1").version == "32.5.5"

    def test_without_an_open_advisory_on_the_pin_the_age_gate_holds(self):
        advisories = [advisory("GHSA-old", "< 30.0.0")]
        assert bump.select_release(self.RELEASES, NOW, advisories, "32.5.5").version == "32.6.1"


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
