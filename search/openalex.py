#!/usr/bin/env python3
"""OpenAlex API client for paper-distill.

Queries https://api.openalex.org/works for recent papers matching user
interests, filtered to Q1 journals listed in config/journals_q1.yaml.

CLI usage:
    python search/openalex.py \
        --interests-file data/interests.jsonl \
        --output data/tmp_openalex.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG = logging.getLogger("search.openalex")

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _load_q1_issns(yaml_path: Path | None = None) -> list[str]:
    """Return a flat list of ISSNs from journals_q1.yaml."""
    yaml_path = yaml_path or PROJECT_ROOT / "config" / "journals_q1.yaml"
    with open(yaml_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    issns: list[str] = []
    for section, journals in data.items():
        if not isinstance(journals, list):
            continue
        for journal in journals:
            if isinstance(journal, dict) and "issn" in journal:
                issns.extend(journal["issn"])
    return issns


def _load_latest_interests(path: Path) -> dict[str, Any]:
    """Read the last line from interests.jsonl and return its dict."""
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    if not lines:
        raise ValueError(f"interests file is empty: {path}")
    return json.loads(lines[-1])


def _extract_keywords(interests: dict[str, Any]) -> list[str]:
    """Extract search keywords from an interests entry."""
    keywords: list[str] = list(interests.get("keywords", []))
    topics = interests.get("topics", {})
    if isinstance(topics, dict):
        for topic_data in topics.values():
            if isinstance(topic_data, dict):
                keywords.extend(topic_data.get("keywords", []))
            elif isinstance(topic_data, list):
                keywords.extend(topic_data)
    return list(dict.fromkeys(keywords))  # deduplicate, preserve order


# ---------------------------------------------------------------------------
# Normalise a single OpenAlex Work to the project-standard paper dict
# ---------------------------------------------------------------------------

def _normalise(work: dict[str, Any]) -> dict[str, Any]:
    """Convert an OpenAlex work JSON to the unified paper schema."""
    authors = []
    for authorship in work.get("authorships", []):
        author = authorship.get("author", {})
        name = author.get("display_name")
        if name:
            authors.append(name)

    oa = work.get("open_access", {})
    oa_url = oa.get("oa_url") or work.get("primary_location", {}).get("pdf_url")

    abstract_index = work.get("abstract_inverted_index")
    abstract = _reconstruct_abstract(abstract_index) if abstract_index else ""

    doi_raw = work.get("doi") or ""
    doi = doi_raw.replace("https://doi.org/", "") if doi_raw else ""

    journal = ""
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    journal = source.get("display_name", "")

    return {
        "source": "openalex",
        "doi": doi,
        "pmid": "",
        "arxiv_id": "",
        "title": work.get("title", ""),
        "authors": authors,
        "abstract": abstract,
        "journal": journal,
        "year": work.get("publication_year"),
        "citation_count": work.get("cited_by_count", 0),
        "tldr": "",
        "open_access_url": oa_url or "",
        "mesh_terms": [],
        "categories": [],
        "topic_tags": [],
    }


def _reconstruct_abstract(inverted_index: dict[str, list[int]]) -> str:
    """Rebuild abstract text from OpenAlex inverted index."""
    if not inverted_index:
        return ""
    word_positions: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort(key=lambda x: x[0])
    return " ".join(w for _, w in word_positions)


# ---------------------------------------------------------------------------
# Async search
# ---------------------------------------------------------------------------

async def search_openalex(
    keywords: list[str],
    *,
    issns: list[str] | None = None,
    year_start: int = 2021,
    year_end: int = 2026,
    max_results: int = 20,
    email: str | None = None,
) -> list[dict[str, Any]]:
    """Query OpenAlex /works and return normalised paper dicts."""

    email = email or os.getenv("OPENALEX_EMAIL", "")
    api_key = os.getenv("OPENALEX_API_KEY", "")
    base_url = "https://api.openalex.org/works"

    # Build filter components
    filters: list[str] = [
        f"publication_year:{year_start}-{year_end}",
    ]
    if issns:
        issn_pipe = "|".join(issns)
        filters.append(f"primary_location.source.issn:{issn_pipe}")

    filter_str = ",".join(filters)

    all_papers: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    async with httpx.AsyncClient(timeout=30.0) as client:
        for kw in keywords:
            params: dict[str, Any] = {
                "search": kw,
                "filter": filter_str,
                "sort": "cited_by_count:desc",
                "per_page": min(max_results, 50),
                "page": 1,
            }
            if email:
                params["mailto"] = email

            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            LOG.info("OpenAlex query: search=%s", kw)
            try:
                resp = await client.get(base_url, params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as exc:
                LOG.warning("OpenAlex HTTP %s for keyword '%s': %s",
                            exc.response.status_code, kw, exc)
                continue
            except httpx.RequestError as exc:
                LOG.warning("OpenAlex request error for keyword '%s': %s", kw, exc)
                continue

            for work in data.get("results", []):
                oa_id = work.get("id", "")
                if oa_id in seen_ids:
                    continue
                seen_ids.add(oa_id)
                all_papers.append(_normalise(work))

            if len(all_papers) >= max_results:
                break

    return all_papers[:max_results]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Search OpenAlex for papers")
    parser.add_argument(
        "--interests-file",
        type=Path,
        default=PROJECT_ROOT / "data" / "interests.jsonl",
        help="Path to interests.jsonl",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=PROJECT_ROOT / "data" / "tmp_openalex.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=20,
        help="Max papers to return",
    )
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s  %(message)s",
    )

    interests = _load_latest_interests(args.interests_file)
    keywords = _extract_keywords(interests)
    if not keywords:
        LOG.error("No keywords found in %s", args.interests_file)
        sys.exit(1)

    LOG.info("Keywords (%d): %s", len(keywords), keywords[:10])

    issns = _load_q1_issns()
    LOG.info("Loaded %d Q1 ISSNs", len(issns))

    papers = asyncio.run(
        search_openalex(
            keywords,
            issns=issns,
            max_results=args.max_results,
        )
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(papers, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    LOG.info("Wrote %d papers to %s", len(papers), args.output)


if __name__ == "__main__":
    main()
