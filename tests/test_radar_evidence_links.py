from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
RADAR_DETAIL_SCRIPT = (
    Path(__file__).parents[1] / "src" / "litwatch" / "static" / "radar-detail.js"
)


def render_trend_evidence(
    papers: list[dict[str, str]],
    evidence_ids: list[str],
    *,
    evidence_hash: str = "",
) -> str:
    if NODE is None:
        pytest.skip("Node.js is required to exercise the browser-side Radar renderer")

    fixture = {
        "radar": {
            "name": "Evidence links",
            "topic": "underwater acoustic localization",
            "providers": ["openalex"],
            "keywords": [],
            "paper_count": len(papers),
            "start_year": 2020,
            "end_year": 2026,
            "hot_trend_count": 1,
            "analysis": {
                "annual_counts": [],
                "timeline": [],
                "periods": [],
                "representative_papers": [],
                "trends": [
                    {
                        "classification": "hot",
                        "phrase": "acoustic localization",
                        "hotness_score": 0.8,
                        "recent_count": len(evidence_ids),
                        "baseline_annual_rate": 1.0,
                        "growth_percent": 25.0,
                        "sources": ["openalex"],
                        "canonical_ids": evidence_ids,
                    }
                ],
            },
        },
        "papers": papers,
        "scans": [],
        "evidence_hash": evidence_hash,
    }
    javascript = r"""
const fixture = JSON.parse(process.argv[1]);
const scriptPath = process.argv[2];
const elements = new Map();
const eventHandlers = new Map();
const evidenceDetails = {tagName: "DETAILS", open: false};
const element = (selector) => {
  if (!elements.has(selector)) {
    elements.set(selector, {
      innerHTML: "",
      hidden: false,
      href: "",
      disabled: false,
      textContent: "",
      addEventListener: () => {},
    });
  }
  return elements.get(selector);
};

global.window = {
  LitWatchI18n: {
    t: (key) => key,
    locale: () => "en-US",
  },
  location: {hash: "", reload: () => {}},
  addEventListener: (type, handler) => eventHandlers.set(type, handler),
  setTimeout,
};
global.document = {
  body: {dataset: {radarId: "radar-test"}},
  getElementById: (id) => id === "evidence-acoustic localization" ? evidenceDetails : null,
  querySelector: element,
};
global.fetch = async (url) => {
  let payload;
  if (url.endsWith("/papers")) payload = fixture.papers;
  else if (url.endsWith("/scans")) payload = fixture.scans;
  else payload = fixture.radar;
  return {ok: true, json: async () => payload};
};

require(scriptPath);
setTimeout(() => {
  const html = element("[data-trends]").innerHTML;
  if (!fixture.evidence_hash) {
    process.stdout.write(html);
    return;
  }
  window.location.hash = fixture.evidence_hash;
  eventHandlers.get("hashchange")?.();
  process.stdout.write(JSON.stringify({html, open: evidenceDetails.open}));
}, 20);
"""
    completed = subprocess.run(
        [NODE, "-e", javascript, json.dumps(fixture), str(RADAR_DETAIL_SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return completed.stdout


@pytest.mark.parametrize(
    ("doi", "normalized"),
    [
        ("10.1234/raw", "10.1234/raw"),
        ("doi:10.1234/prefixed", "10.1234/prefixed"),
        ("https://doi.org/10.1234/https", "10.1234/https"),
        ("http://doi.org/10.1234/http", "10.1234/http"),
    ],
)
def test_trend_evidence_normalizes_doi_into_external_link(doi, normalized):
    canonical_id = f"doi:{normalized}"

    html = render_trend_evidence(
        [{"canonical_id": canonical_id, "doi": doi, "url": ""}],
        [canonical_id],
    )

    assert f'href="https://doi.org/{normalized}"' in html
    assert f">doi:{normalized}</a>" in html
    assert 'target="_blank"' in html
    assert 'rel="noopener noreferrer"' in html
    assert "#paper-doi" not in html


def test_trend_evidence_without_doi_or_url_is_plain_text():
    canonical_id = "openalex:W-no-link"

    html = render_trend_evidence(
        [{"canonical_id": canonical_id, "doi": "", "url": ""}],
        [canonical_id],
    )

    assert canonical_id in html
    assert f'href="#paper-{canonical_id}' not in html
    assert "https://doi.org/" not in html


def test_trend_evidence_without_doi_uses_valid_paper_url():
    canonical_id = "openalex:W-url"
    paper_url = "https://example.org/papers/W-url"

    html = render_trend_evidence(
        [{"canonical_id": canonical_id, "doi": "", "url": paper_url}],
        [canonical_id],
    )

    assert f'href="{paper_url}"' in html
    assert 'target="_blank"' in html
    assert 'rel="noopener noreferrer"' in html


def test_view_evidence_hash_reveals_the_doi_links():
    canonical_id = "doi:10.1234/visible"

    rendered = render_trend_evidence(
        [{"canonical_id": canonical_id, "doi": "10.1234/visible", "url": ""}],
        [canonical_id],
        evidence_hash="#evidence-acoustic%20localization",
    )
    result = json.loads(rendered)

    assert result["open"] is True
    assert 'href="https://doi.org/10.1234/visible"' in result["html"]
