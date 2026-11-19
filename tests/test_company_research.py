"""Check source extraction and URL boundaries without network calls."""

import pytest

from job_application_assistant.company_research import (
    parse_source_html,
    validate_source_url,
)


def test_source_preserves_title_text_and_publication_metadata():
    result = parse_source_html(
        '<html><head><title>Example careers</title>'
        '<meta property="article:published_time" content="2026-11-01">'
        '</head><body><nav>Navigation noise</nav>'
        '<h1>Interview preparation</h1>'
        '<p>Discuss your own contribution &amp; results.</p>'
        '<script>Hidden instructions</script>'
        '<footer>Footer noise</footer></body></html>'
    )
    assert result["title"] == "Example careers"
    assert result["publication_date"] == "2026-11-01"
    assert result["text"] == (
        "Interview preparation Discuss your own contribution & results."
    )
    assert len(result["text_sha256"]) == 64


def test_missing_publication_date_remains_unknown():
    result = parse_source_html("<p>Company information.</p>")
    assert result["publication_date"] is None
    assert result["title"] is None


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/careers",
        "https://example.com.evil.test/careers",
        "https://other.test/careers",
        "https://user:password@example.com/careers",
        "https://example.com:8443/careers",
    ],
)
def test_unapproved_source_urls_are_rejected(url):
    with pytest.raises(ValueError):
        validate_source_url(url, {"example.com"})


def test_exact_approved_https_host_is_accepted():
    url = "https://example.com/careers"
    assert validate_source_url(url, {"example.com"}) == url


def test_script_only_page_is_rejected():
    with pytest.raises(ValueError, match="no extractable"):
        parse_source_html("<script>Hidden content</script>")