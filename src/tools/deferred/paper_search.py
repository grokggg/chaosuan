from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from typing import Annotated, Any, Literal

from langchain.tools import tool

from src.tools.deferred import deferred

PaperSearchSource = Literal["both", "arxiv", "openalex"]

ARXIV_API_BASE = "https://export.arxiv.org/api/query"
OPENALEX_API_BASE = "https://api.openalex.org/works"
USER_AGENT = "vibe-coding-template-paper-search/1.0"
TITLE_KEY_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class PaperRecord:
    source: str
    source_id: str
    title: str
    authors: list[str]
    year: int | None
    published_date: str
    venue: str
    doi: str
    url: str
    abstract: str
    citation_count: int | None = None
    open_access_url: str = ""


def _normalize_space(value: str) -> str:
    return " ".join((value or "").split())


def _title_key(title: str) -> str:
    return TITLE_KEY_RE.sub(" ", title.lower()).strip()


def _year_from_date(value: str) -> int | None:
    match = re.search(r"\b(?:19|20)\d{2}\b", value or "")
    return int(match.group(0)) if match else None


def _request_json(url: str, timeout_seconds: int) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _request_xml(url: str, timeout_seconds: int) -> ET.Element:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
        return ET.fromstring(response.read())


def _in_year_range(year: int | None, from_year: int | None, to_year: int | None) -> bool:
    if from_year is not None and (year is None or year < from_year):
        return False
    if to_year is not None and (year is None or year > to_year):
        return False
    return True


def _arxiv_query(query: str) -> str:
    escaped = query.replace('"', "")
    return f'all:"{escaped}"'


def _search_arxiv(
    query: str,
    *,
    max_results: int,
    from_year: int | None,
    to_year: int | None,
    timeout_seconds: int,
    raw_arxiv_query: str | None,
) -> list[PaperRecord]:
    params = {
        "search_query": raw_arxiv_query or _arxiv_query(query),
        "start": "0",
        "max_results": str(max_results),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    root = _request_xml(f"{ARXIV_API_BASE}?{urllib.parse.urlencode(params)}", timeout_seconds)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }

    records: list[PaperRecord] = []
    for entry in root.findall("atom:entry", ns):
        published = entry.findtext("atom:published", default="", namespaces=ns)
        year = _year_from_date(published)
        if not _in_year_range(year, from_year, to_year):
            continue

        title = _normalize_space(entry.findtext("atom:title", default="", namespaces=ns))
        authors = [
            _normalize_space(author.findtext("atom:name", default="", namespaces=ns))
            for author in entry.findall("atom:author", ns)
        ]
        authors = [author for author in authors if author]

        source_id = _normalize_space(entry.findtext("atom:id", default="", namespaces=ns))
        url = source_id
        for link in entry.findall("atom:link", ns):
            if link.attrib.get("rel") == "alternate" and link.attrib.get("href"):
                url = link.attrib["href"]
                break

        category = entry.find("arxiv:primary_category", ns)
        category_name = category.attrib.get("term", "") if category is not None else ""
        venue = f"arXiv:{category_name}" if category_name else "arXiv"

        records.append(
            PaperRecord(
                source="arxiv",
                source_id=source_id,
                title=title,
                authors=authors,
                year=year,
                published_date=published,
                venue=venue,
                doi=_normalize_space(entry.findtext("arxiv:doi", default="", namespaces=ns)),
                url=url,
                abstract=_normalize_space(entry.findtext("atom:summary", default="", namespaces=ns)),
            )
        )
    return records


def _invert_openalex_abstract(index: dict[str, list[int]]) -> str:
    if not index:
        return ""
    words: list[tuple[int, str]] = []
    for word, positions in index.items():
        for position in positions:
            words.append((position, word))
    words.sort(key=lambda item: item[0])
    return _normalize_space(" ".join(word for _, word in words))


def _openalex_authors(item: dict[str, Any]) -> list[str]:
    authors: list[str] = []
    for authorship in item.get("authorships") or []:
        author = authorship.get("author") or {}
        name = _normalize_space(str(author.get("display_name") or ""))
        if name:
            authors.append(name)
    return authors


def _openalex_venue(item: dict[str, Any]) -> str:
    primary_location = item.get("primary_location") or {}
    source = primary_location.get("source") or {}
    return _normalize_space(str(source.get("display_name") or primary_location.get("landing_page_url") or ""))


def _search_openalex(
    query: str,
    *,
    max_results: int,
    from_year: int | None,
    to_year: int | None,
    timeout_seconds: int,
    openalex_email: str | None,
) -> list[PaperRecord]:
    filters: list[str] = []
    if from_year is not None:
        filters.append(f"from_publication_date:{from_year}-01-01")
    if to_year is not None:
        filters.append(f"to_publication_date:{to_year}-12-31")

    params = {
        "search": query,
        "per-page": str(max_results),
        "select": ",".join(
            [
                "id",
                "doi",
                "title",
                "display_name",
                "authorships",
                "publication_year",
                "publication_date",
                "primary_location",
                "open_access",
                "cited_by_count",
                "abstract_inverted_index",
            ]
        ),
    }
    if filters:
        params["filter"] = ",".join(filters)
    if openalex_email:
        params["mailto"] = openalex_email

    payload = _request_json(f"{OPENALEX_API_BASE}?{urllib.parse.urlencode(params)}", timeout_seconds)
    records: list[PaperRecord] = []
    for item in payload.get("results") or []:
        title = _normalize_space(str(item.get("title") or item.get("display_name") or ""))
        if not title:
            continue
        primary_location = item.get("primary_location") or {}
        open_access = item.get("open_access") or {}
        doi = str(item.get("doi") or "").removeprefix("https://doi.org/")
        open_access_url = str(open_access.get("oa_url") or "")
        source_id = str(item.get("id") or "")
        url = str(primary_location.get("landing_page_url") or open_access_url or source_id)

        records.append(
            PaperRecord(
                source="openalex",
                source_id=source_id,
                title=title,
                authors=_openalex_authors(item),
                year=item.get("publication_year"),
                published_date=str(item.get("publication_date") or ""),
                venue=_openalex_venue(item),
                doi=doi,
                url=url,
                abstract=_invert_openalex_abstract(item.get("abstract_inverted_index") or {}),
                citation_count=item.get("cited_by_count"),
                open_access_url=open_access_url,
            )
        )
    return records


def _merge_records(left: PaperRecord, right: PaperRecord) -> PaperRecord:
    primary, secondary = (right, left) if right.source == "openalex" else (left, right)
    sources = sorted({left.source, right.source})
    return PaperRecord(
        source="+".join(sources),
        source_id=primary.source_id or secondary.source_id,
        title=primary.title or secondary.title,
        authors=primary.authors or secondary.authors,
        year=primary.year or secondary.year,
        published_date=primary.published_date or secondary.published_date,
        venue=primary.venue or secondary.venue,
        doi=primary.doi or secondary.doi,
        url=primary.url or secondary.url,
        abstract=primary.abstract or secondary.abstract,
        citation_count=primary.citation_count if primary.citation_count is not None else secondary.citation_count,
        open_access_url=primary.open_access_url or secondary.open_access_url,
    )


def _deduplicate(records: list[PaperRecord]) -> list[PaperRecord]:
    by_key: dict[str, PaperRecord] = {}
    for record in records:
        key = f"doi:{record.doi.lower()}" if record.doi else f"title:{_title_key(record.title)}"
        if key == "title:":
            key = f"{record.source}:{record.source_id}"
        existing = by_key.get(key)
        by_key[key] = record if existing is None else _merge_records(existing, record)
    return list(by_key.values())


def _sort_records(records: list[PaperRecord]) -> list[PaperRecord]:
    return sorted(
        records, key=lambda record: (-(record.citation_count or 0), -(record.year or 0), record.title.lower())
    )


@deferred("paper_search")
@tool(
    "search_academic_papers",
    description=(
        "Search academic papers from arXiv and OpenAlex. Use this as the first discovery tool for literature "
        "searches, deep research, systematic review scoping, and academic-paper literature review. Returns JSON "
        "with title, authors, year, venue, DOI, URL, abstract, citation_count, and per-source errors. Prefer this "
        "before general WebSearch when the user asks to search papers or literature."
    ),
)
def search_academic_papers(
    query: Annotated[
        str,
        ("Search query, for example 'large language model citation reliability'."),
    ],
    source: Annotated[
        PaperSearchSource,
        ("Search source: both, arxiv, or openalex."),
    ] = "both",
    max_results: Annotated[
        int,
        ("Maximum results per source before deduplication."),
    ] = 20,
    from_year: Annotated[
        int | None,
        ("Earliest publication year to include."),
    ] = None,
    to_year: Annotated[
        int | None,
        ("Latest publication year to include."),
    ] = None,
    raw_arxiv_query: Annotated[
        str | None,
        ("Optional raw arXiv API query, for example 'cat:cs.CL AND all:hallucination'."),
    ] = None,
    openalex_email: Annotated[
        str | None,
        ("Optional email for OpenAlex polite pool. Leave empty if unavailable."),
    ] = None,
    timeout_seconds: Annotated[
        int,
        ("Per-source HTTP timeout in seconds."),
    ] = 15,
) -> str:
    if not query or not query.strip():
        raise ValueError("query must not be empty")
    if max_results < 1 or max_results > 100:
        raise ValueError("max_results must be between 1 and 100")
    if timeout_seconds < 3 or timeout_seconds > 120:
        raise ValueError("timeout_seconds must be between 3 and 120")

    normalized_query = _normalize_space(query)
    records: list[PaperRecord] = []
    errors: list[dict[str, str]] = []

    if source in {"both", "arxiv"}:
        try:
            records.extend(
                _search_arxiv(
                    normalized_query,
                    max_results=max_results,
                    from_year=from_year,
                    to_year=to_year,
                    timeout_seconds=timeout_seconds,
                    raw_arxiv_query=raw_arxiv_query,
                )
            )
        except (urllib.error.URLError, TimeoutError, ET.ParseError, OSError) as exc:
            errors.append({"source": "arxiv", "error": str(exc)})

    if source in {"both", "openalex"}:
        try:
            records.extend(
                _search_openalex(
                    normalized_query,
                    max_results=max_results,
                    from_year=from_year,
                    to_year=to_year,
                    timeout_seconds=timeout_seconds,
                    openalex_email=openalex_email,
                )
            )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            errors.append({"source": "openalex", "error": str(exc)})

    results = _sort_records(_deduplicate(records))
    return json.dumps(
        {
            "query": normalized_query,
            "source": source,
            "count": len(results),
            "errors": errors,
            "results": [asdict(record) for record in results],
        },
        ensure_ascii=False,
        indent=2,
    )


__all__ = ["search_academic_papers"]
