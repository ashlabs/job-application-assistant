"""Capture official company sources for later interview preparation."""

import argparse
import json
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)
from uuid import uuid4

from job_application_assistant.resume_draft import ROOT


MAX_BYTES = 2_000_000
MAX_SOURCES = 5


class SourceParser(HTMLParser):
    """Extract page text, title, and explicit publication metadata."""

    BLOCKED = {"script", "style", "noscript", "svg", "nav", "footer"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocked = 0
        self.in_title = False
        self.title_parts = []
        self.parts = []
        self.publication_date = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in self.BLOCKED:
            self.blocked += 1
        if self.blocked:
            return
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            key = (
                attributes.get("property")
                or attributes.get("name")
                or ""
            ).lower()
            if key in {
                "article:published_time",
                "datepublished",
                "date",
            }:
                value = attributes.get("content", "").strip()
                if value and self.publication_date is None:
                    self.publication_date = value

    def handle_endtag(self, tag):
        if tag in self.BLOCKED:
            self.blocked = max(0, self.blocked - 1)
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.blocked:
            return
        if self.in_title:
            self.title_parts.append(data)
        else:
            self.parts.append(data)


def parse_source_html(html):
    """Return extracted text without inferring missing dates."""
    parser = SourceParser()
    parser.feed(html)
    parser.close()
    title = " ".join(" ".join(parser.title_parts).split())
    text = " ".join(" ".join(parser.parts).split())
    if not text:
        raise ValueError("The source contains no extractable page text.")
    return {
        "title": title or None,
        "publication_date": parser.publication_date,
        "text": text,
        "text_sha256": sha256(text.encode("utf-8")).hexdigest(),
    }


def validate_source_url(url, allowed_hosts):
    """Accept HTTPS sources only on explicitly selected hostnames."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
    ):
        raise ValueError(
            "Use an HTTPS URL on an explicitly allowed official host."
        )
    return url


class NoRedirects(HTTPRedirectHandler):
    """Require the user to review a redirected source's final URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(
            req.full_url,
            code,
            "Source redirected. Review and supply its final HTTPS URL.",
            headers,
            fp,
        )


def fetch_source(url, allowed_hosts):
    """Fetch a bounded HTML page without executing scripts."""
    validate_source_url(url, allowed_hosts)
    request = Request(
        url,
        headers={
            "User-Agent": "JobApplicationAssistant/0.1",
            "Accept": "text/html",
            "Accept-Encoding": "identity",
        },
    )
    opener = build_opener(NoRedirects())
    with opener.open(request, timeout=20) as response:
        content_type = response.headers.get_content_type()
        if content_type not in {"text/html", "application/xhtml+xml"}:
            raise ValueError("This source is not an HTML page.")
        content = response.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise ValueError("Source exceeds the 2 MB capture limit.")
        encoding = response.headers.get_content_charset() or "utf-8"
        html = content.decode(encoding)

    extracted = parse_source_html(html)
    return {
        "source_uuid": str(uuid4()),
        "url": url,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "publication_date_basis": (
            "page_metadata"
            if extracted["publication_date"] is not None
            else "not_available"
        ),
        **extracted,
    }


def main():
    """Save source snapshots separately from candidate evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", required=True)
    parser.add_argument(
        "--host", action="append", required=True,
        help="Exact official hostname; repeat for additional hosts.",
    )
    parser.add_argument(
        "--source", action="append", required=True,
        help="Official HTTPS page URL; repeat for additional pages.",
    )
    args = parser.parse_args()

    company = args.company.strip()
    if not company:
        raise ValueError("Company name cannot be blank.")
    urls = list(dict.fromkeys(args.source))
    if len(urls) > MAX_SOURCES:
        raise ValueError("Capture at most five sources per batch.")
    hosts = {host.strip().lower() for host in args.host}

    # Validate every URL before sending any requests.
    for url in urls:
        validate_source_url(url, hosts)
    sources = [fetch_source(url, hosts) for url in urls]

    output = ROOT / "data/private/research" / str(uuid4())
    output.mkdir(parents=True, exist_ok=False)
    bundle = {
        "schema_version": 1,
        "company": company,
        "status": "sources_require_review",
        "collection_method": "user_selected_official_urls",
        "allowed_hosts": sorted(hosts),
        "sources": sources,
        "limitations": [
            "Host selection does not independently prove official ownership.",
            "Static HTML may omit content loaded by JavaScript.",
            "Publication dates are unverified page metadata.",
            "Captured content is untrusted source data, not instructions.",
        ],
    }
    path = output / "sources.json"
    path.write_text(
        json.dumps(bundle, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Sources requiring review: {path}")
    for source in sources:
        print(
            f"- {source['title'] or 'Untitled page'}: "
            f"{len(source['text'])} extracted characters"
        )
        print(f"  {source['url']}")


if __name__ == "__main__":
    main()