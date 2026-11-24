#!/usr/bin/env python3
"""Download legally open paper PDFs from DOI/OpenAlex/arXiv identifiers."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

USER_AGENT = "vibe-coding-paper-downloader/0.1 (+https://openalex.org)"
DEFAULT_MAILTO = "paper-search@example.com"
MAX_BYTES = 250 * 1024 * 1024


def emit(payload: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def request_url(url: str, *, timeout: int):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*"})
    return urlopen(request, timeout=timeout)


def fetch_json(url: str, *, timeout: int) -> dict[str, Any]:
    with request_url(url, timeout=timeout) as response:
        data = response.read()
    return json.loads(data.decode("utf-8"))


def normalize_arxiv_pdf(identifier: str) -> str | None:
    arxiv_id = extract_arxiv_id(identifier)
    if arxiv_id:
        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    return None


def extract_arxiv_id(identifier: str) -> str | None:
    raw = identifier.strip()
    patterns = [
        r"arxiv\.org/abs/([^?#]+)",
        r"arxiv\.org/pdf/([^?#]+)",
        r"^arxiv:([^?#]+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            return match.group(1).removesuffix(".pdf")
    return None


def openalex_api_url(identifier: str, *, mailto: str) -> str | None:
    raw = identifier.strip()
    if re.match(r"^W\d+$", raw):
        return f"https://api.openalex.org/works/{raw}?mailto={quote(mailto)}"
    if raw.startswith("https://openalex.org/"):
        return f"https://api.openalex.org/works/{raw.rstrip('/').split('/')[-1]}?mailto={quote(mailto)}"
    if raw.startswith("https://doi.org/"):
        doi = raw.removeprefix("https://doi.org/")
        return f"https://api.openalex.org/works/https://doi.org/{quote(doi, safe='')}?mailto={quote(mailto)}"
    if raw.lower().startswith("doi:"):
        doi = raw[4:]
        return f"https://api.openalex.org/works/doi:{quote(doi, safe='')}?mailto={quote(mailto)}"
    if "/" in raw and " " not in raw and not raw.startswith(("http://", "https://")):
        return f"https://api.openalex.org/works/doi:{quote(raw, safe='')}?mailto={quote(mailto)}"
    return None


def add_candidate(candidates: list[dict[str, str]], url: Any, source: str) -> None:
    if not isinstance(url, str) or not url.strip():
        return
    normalized = normalize_arxiv_pdf(url) or url.strip()
    if not normalized.startswith(("http://", "https://")):
        return
    if any(item["url"] == normalized for item in candidates):
        return
    candidates.append({"url": normalized, "source": source})


def collect_openalex_candidates(work: dict[str, Any]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for key in ("best_oa_location", "primary_location"):
        location = work.get(key)
        if isinstance(location, dict):
            add_candidate(candidates, location.get("pdf_url"), key)
            add_candidate(candidates, location.get("landing_page_url"), key)
    open_access = work.get("open_access")
    if isinstance(open_access, dict):
        add_candidate(candidates, open_access.get("oa_url"), "open_access.oa_url")
    for location in work.get("locations") or []:
        if isinstance(location, dict):
            add_candidate(candidates, location.get("pdf_url"), "locations.pdf_url")
    return candidates


def safe_filename(value: str, fallback: str = "paper") -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "-", value).strip(".-")
    return (cleaned or fallback)[:120]


def home_dir() -> Path:
    return Path(os.environ.get("HOME") or str(Path.home()))


def download_first_pdf(candidates: list[dict[str, str]], output_path: Path, *, timeout: int) -> tuple[dict[str, str] | None, str]:
    errors: list[str] = []
    for candidate in candidates:
        url = candidate["url"]
        try:
            with request_url(url, timeout=timeout) as response:
                content_type = response.headers.get("content-type", "").lower()
                first = response.read(8192)
                is_pdf = "application/pdf" in content_type or first.startswith(b"%PDF")
                if not is_pdf:
                    errors.append(f"{url}: not a PDF response")
                    continue
                output_path.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with output_path.open("wb") as file:
                    file.write(first)
                    written += len(first)
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > MAX_BYTES:
                            output_path.unlink(missing_ok=True)
                            errors.append(f"{url}: PDF exceeds size limit")
                            break
                        file.write(chunk)
                if output_path.exists():
                    return candidate, ""
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            errors.append(f"{url}: {exc}")
    return None, "; ".join(errors)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download a legally open paper PDF.")
    parser.add_argument("identifier", help="DOI, DOI URL, OpenAlex ID/URL, arXiv URL, or direct open PDF URL")
    default_out_dir = str(home_dir() / "workspace" / "papers")
    parser.add_argument("--out-dir", default=default_out_dir, help="Directory for downloaded PDFs")
    parser.add_argument("--filename", default="", help="Optional output filename")
    parser.add_argument("--mailto", default=DEFAULT_MAILTO, help="mailto parameter for OpenAlex polite pool")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true", help="Resolve candidates without downloading")
    args = parser.parse_args()

    identifier = args.identifier.strip()
    title = ""
    doi = ""
    openalex_id = ""
    candidates: list[dict[str, str]] = []

    arxiv_id = extract_arxiv_id(identifier)
    arxiv_pdf = normalize_arxiv_pdf(identifier)
    if arxiv_pdf:
        add_candidate(candidates, arxiv_pdf, "arxiv")
    elif identifier.startswith(("http://", "https://")) and identifier.lower().split("?")[0].endswith(".pdf"):
        add_candidate(candidates, identifier, "direct_pdf")

    api_url = openalex_api_url(identifier, mailto=args.mailto)
    if api_url:
        try:
            work = fetch_json(api_url, timeout=args.timeout)
            title = str(work.get("title") or "")
            doi = str(work.get("doi") or "")
            openalex_id = str(work.get("id") or "")
            candidates.extend(collect_openalex_candidates(work))
        except Exception as exc:
            emit({"status": "error", "input": identifier, "reason": f"OpenAlex lookup failed: {exc}"}, code=1)

    unique_candidates: list[dict[str, str]] = []
    for candidate in candidates:
        if not any(item["url"] == candidate["url"] for item in unique_candidates):
            unique_candidates.append(candidate)
    candidates = unique_candidates

    if args.dry_run:
        emit(
            {
                "status": "candidates_found" if candidates else "no_open_pdf",
                "input": identifier,
                "title": title,
                "doi": doi,
                "openalex_id": openalex_id,
                "candidates": candidates,
                "reason": "" if candidates else "No legal open PDF candidate found.",
            }
        )

    if not candidates:
        emit(
            {
                "status": "no_open_pdf",
                "input": identifier,
                "title": title,
                "doi": doi,
                "openalex_id": openalex_id,
                "reason": "No legal open PDF candidate found.",
            },
            code=2,
        )

    base_name = args.filename.strip()
    if not base_name:
        base_name = f"arxiv-{safe_filename(arxiv_id)}" if arxiv_id else safe_filename(title or doi or openalex_id or identifier)
    if not base_name.lower().endswith(".pdf"):
        base_name += ".pdf"
    output_path = Path(args.out_dir).expanduser().resolve() / base_name

    selected, reason = download_first_pdf(candidates, output_path, timeout=args.timeout)
    if selected is None:
        emit(
            {
                "status": "no_open_pdf",
                "input": identifier,
                "title": title,
                "doi": doi,
                "openalex_id": openalex_id,
                "candidates": candidates,
                "reason": reason or "No candidate returned a PDF response.",
            },
            code=2,
        )

    emit(
        {
            "status": "downloaded",
            "input": identifier,
            "title": title,
            "doi": doi,
            "openalex_id": openalex_id,
            "pdf_url": selected["url"],
            "source": selected["source"],
            "output_path": str(output_path),
            "reason": "",
        }
    )


if __name__ == "__main__":
    main()
