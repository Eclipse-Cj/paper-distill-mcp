#!/usr/bin/env python3
"""Unified ad-hoc academic search for OpenClaw agents.

Queries 5 academic sources directly (no journal filter, no date limit)
and merges results with dedup.

Usage:
    python search/query_all.py "streaming multiple instance learning Wasserstein"
    python search/query_all.py -q "LLM chain-of-thought" -n 10
    python search/query_all.py -q "..." -f json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import httpx

LOG = logging.getLogger("search.query_all")
PROJECT_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(PROJECT_ROOT / "search"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


# ---------------------------------------------------------------------------
# 1. OpenAlex (no journal filter, broad year range)
# ---------------------------------------------------------------------------
async def _search_openalex(query: str, max_results: int = 30) -> list[dict]:
    email = os.getenv("OPENALEX_EMAIL", "")
    api_key = os.getenv("OPENALEX_API_KEY", "")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    papers = []
    async with httpx.AsyncClient(timeout=30) as client:
        params = {
            "search": query,
            "per_page": min(max_results, 50),
            "sort": "relevance_score:desc",
        }
        if email:
            params["mailto"] = email
        resp = await client.get("https://api.openalex.org/works", params=params, headers=headers)
        if resp.status_code != 200:
            return []
        for w in resp.json().get("results", []):
            doi = (w.get("doi") or "").replace("https://doi.org/", "")
            papers.append({
                "title": w.get("display_name", ""),
                "year": w.get("publication_year"),
                "doi": doi,
                "citation_count": w.get("cited_by_count", 0),
                "authors": [a.get("author", {}).get("display_name", "")
                            for a in (w.get("authorships") or [])[:5]],
                "abstract": (w.get("abstract_inverted_index") and "..." or ""),
                "open_access_url": (w.get("best_oa_location") or {}).get("pdf_url", ""),
                "source": "openalex",
            })
    return papers


# ---------------------------------------------------------------------------
# 2. Semantic Scholar
# ---------------------------------------------------------------------------
async def _search_s2(query: str, max_results: int = 30) -> list[dict]:
    papers = []
    fields = "title,abstract,tldr,citationCount,year,authors,externalIds,openAccessPdf,venue"
    async with httpx.AsyncClient(timeout=30) as client:
        params = {"query": query, "limit": min(max_results, 100), "fields": fields}
        api_key = os.getenv("S2_API_KEY", "")
        headers = {"x-api-key": api_key} if api_key else {}
        resp = await client.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params=params, headers=headers,
        )
        if resp.status_code != 200:
            return []
        for p in resp.json().get("data", []):
            ext = p.get("externalIds") or {}
            tldr = p.get("tldr")
            papers.append({
                "title": p.get("title", ""),
                "year": p.get("year"),
                "doi": ext.get("DOI", ""),
                "arxiv_id": ext.get("ArXiv", ""),
                "citation_count": p.get("citationCount", 0),
                "authors": [a.get("name", "") for a in (p.get("authors") or [])[:5]],
                "tldr": tldr.get("text", "") if isinstance(tldr, dict) else (tldr or ""),
                "abstract": (p.get("abstract") or "")[:300],
                "venue": p.get("venue", ""),
                "open_access_url": (p.get("openAccessPdf") or {}).get("url", ""),
                "source": "s2",
            })
    return papers


# ---------------------------------------------------------------------------
# 3. PubMed (via E-utilities)
# ---------------------------------------------------------------------------
async def _search_pubmed(query: str, max_results: int = 20) -> list[dict]:
    try:
        from Bio import Entrez
    except ImportError:
        return []
    Entrez.email = os.getenv("OPENALEX_EMAIL", "user@example.com")
    try:
        handle = Entrez.esearch(db="pubmed", term=query, retmax=max_results, sort="relevance")
        record = Entrez.read(handle)
        ids = record.get("IdList", [])
        if not ids:
            return []
        handle = Entrez.efetch(db="pubmed", id=",".join(ids), rettype="xml")
        from Bio import Medline
        import xml.etree.ElementTree as ET
        xml_data = handle.read()
        root = ET.fromstring(xml_data)
        papers = []
        for article in root.findall(".//PubmedArticle"):
            mc = article.find(".//MedlineCitation")
            a = mc.find(".//Article") if mc is not None else None
            if a is None:
                continue
            title = (a.findtext("ArticleTitle") or "").strip()
            pmid = mc.findtext("PMID", "")
            year_el = a.find(".//PubDate/Year")
            year = int(year_el.text) if year_el is not None and year_el.text else None
            abstract_el = a.find(".//Abstract/AbstractText")
            abstract = (abstract_el.text or "") if abstract_el is not None else ""
            authors = []
            for au in a.findall(".//AuthorList/Author"):
                ln = au.findtext("LastName", "")
                fn = au.findtext("ForeName", "")
                if ln:
                    authors.append(f"{fn} {ln}".strip())
            doi = ""
            for eid in article.findall(".//ArticleIdList/ArticleId"):
                if eid.get("IdType") == "doi":
                    doi = eid.text or ""
            papers.append({
                "title": title,
                "year": year,
                "doi": doi,
                "pmid": pmid,
                "citation_count": 0,
                "authors": authors[:5],
                "abstract": abstract[:300],
                "source": "pubmed",
            })
        return papers
    except Exception as e:
        LOG.warning("PubMed error: %s", e)
        return []


# ---------------------------------------------------------------------------
# 4. arXiv (no date limit for ad-hoc)
# ---------------------------------------------------------------------------
async def _search_arxiv(query: str, max_results: int = 20) -> list[dict]:
    try:
        import arxiv
    except ImportError:
        return []
    papers = []
    try:
        client = arxiv.Client()
        search = arxiv.Search(query=f'all:"{query}"', max_results=max_results,
                              sort_by=arxiv.SortCriterion.Relevance)
        for r in client.results(search):
            papers.append({
                "title": r.title,
                "year": r.published.year if r.published else None,
                "arxiv_id": r.get_short_id(),
                "doi": r.doi or "",
                "citation_count": 0,
                "authors": [a.name for a in (r.authors or [])[:5]],
                "abstract": (r.summary or "")[:300],
                "open_access_url": r.pdf_url or "",
                "categories": list(r.categories or []),
                "source": "arxiv",
            })
    except Exception as e:
        LOG.warning("arXiv error: %s", e)
    return papers


# ---------------------------------------------------------------------------
# 5. Papers with Code (search endpoint)
# ---------------------------------------------------------------------------
async def _search_pwc(query: str, max_results: int = 20) -> list[dict]:
    papers = []
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(
            "https://paperswithcode.com/api/v1/search/",
            params={"q": query, "page": 1, "items_per_page": max_results},
        )
        if resp.status_code != 200:
            return []
        try:
            data = resp.json()
        except Exception:
            return []
        for item in data.get("results", []):
            paper = item.get("paper", {})
            if not paper:
                continue
            papers.append({
                "title": paper.get("title", ""),
                "year": None,
                "arxiv_id": paper.get("arxiv_id", ""),
                "doi": "",
                "citation_count": 0,
                "authors": [],
                "abstract": (paper.get("abstract") or "")[:300],
                "open_access_url": paper.get("url_pdf", ""),
                "source": "pwc",
            })
    return papers


# ---------------------------------------------------------------------------
# Dedup & merge
# ---------------------------------------------------------------------------
def _normalize_title(t: str) -> str:
    return t.lower().strip().rstrip(".")


def _dedup_merge(all_papers: list[dict]) -> list[dict]:
    merged: list[dict] = []
    doi_idx: dict[str, int] = {}
    title_idx: dict[str, int] = {}

    for p in all_papers:
        doi = (p.get("doi") or "").strip()
        norm = _normalize_title(p.get("title", ""))

        dup = None
        if doi and doi in doi_idx:
            dup = doi_idx[doi]
        elif norm and norm in title_idx:
            dup = title_idx[norm]

        if dup is not None:
            # Merge: keep higher citation count, combine sources, fill blanks
            existing = merged[dup]
            sources = set(existing.get("source", "").split(","))
            sources.add(p.get("source", ""))
            existing["source"] = ",".join(sorted(s for s in sources if s))
            if (p.get("citation_count") or 0) > (existing.get("citation_count") or 0):
                existing["citation_count"] = p["citation_count"]
            for field in ("tldr", "abstract", "open_access_url", "arxiv_id", "venue", "doi"):
                if not existing.get(field) and p.get(field):
                    existing[field] = p[field]
        else:
            idx = len(merged)
            merged.append(p)
            if doi:
                doi_idx[doi] = idx
            if norm:
                title_idx[norm] = idx

    return merged


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------
def _format_markdown(papers: list[dict], top: int, query: str) -> str:
    if not papers:
        return "未找到相关论文。"

    lines = [f"🔍 **\"{query}\"** — {len(papers)} 篇（top {min(top, len(papers))}）\n"]

    for i, p in enumerate(papers[:top], 1):
        title = p.get("title", "Untitled")
        year = p.get("year", "?")
        cites = p.get("citation_count", 0) or 0
        authors = p.get("authors", [])
        if authors:
            a_str = ", ".join(str(a) for a in authors[:3])
            if len(authors) > 3:
                a_str += " et al."
        else:
            a_str = ""

        url = p.get("open_access_url", "")
        if not url and p.get("arxiv_id"):
            url = f"https://arxiv.org/abs/{p['arxiv_id']}"
        if not url and p.get("doi"):
            url = f"https://doi.org/{p['doi']}"

        tldr = p.get("tldr", "") or p.get("abstract", "")
        sources = p.get("source", "")

        lines.append(f"**{i}. {title}** ({year}, {cites}× cited)")
        if a_str:
            lines.append(f"   {a_str}")
        if url:
            lines.append(f"   {url}")
        if tldr:
            lines.append(f"   > {tldr[:250]}")
        lines.append(f"   [{sources}]")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def search_all(query: str, top: int = 10) -> list[dict]:
    """Run all engines concurrently and return merged results."""
    tasks = [
        _search_openalex(query),
        _search_s2(query),
        _search_pubmed(query),
        _search_arxiv(query),
        _search_pwc(query),
    ]
    engine_names = ["openalex", "s2", "pubmed", "arxiv", "pwc"]

    # Add new API sources (graceful fallback if not installed)
    try:
        from search.crossref_search import search_crossref
        tasks.append(search_crossref(query, max_results=20))
        engine_names.append("crossref")
    except ImportError:
        pass
    try:
        from search.europepmc_search import search_europepmc
        tasks.append(search_europepmc(query, max_results=20))
        engine_names.append("europepmc")
    except ImportError:
        pass
    try:
        from search.biorxiv_search import search_biorxiv
        tasks.append(search_biorxiv(query, max_results=15))
        engine_names.append("biorxiv")
    except ImportError:
        pass
    try:
        from search.dblp_search import search_dblp
        tasks.append(search_dblp(query, max_results=20))
        engine_names.append("dblp")
    except ImportError:
        pass
    try:
        from search.core_search import search_core
        tasks.append(search_core(query, max_results=20))
        engine_names.append("core")
    except ImportError:
        pass

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_papers = []
    for name, res in zip(engine_names, results):
        if isinstance(res, Exception):
            print(f"  ✗ {name}: {res}", file=sys.stderr)
        elif res:
            print(f"  ✓ {name}: {len(res)}", file=sys.stderr)
            # Tag each paper with its relevance rank from the engine
            for rank, p in enumerate(res):
                p["_relevance_rank"] = rank
            all_papers.extend(res)
        else:
            print(f"  ✗ {name}: 0", file=sys.stderr)

    merged = _dedup_merge(all_papers)
    # Score: number of engines that found it (cross-source hits) + inverse rank
    # Papers found by multiple engines are most likely relevant
    for p in merged:
        n_sources = len(p.get("source", "").split(","))
        p["_score"] = n_sources * 100 - p.get("_relevance_rank", 50)
    merged.sort(key=lambda p: (p["_score"], p.get("citation_count") or 0), reverse=True)

    # Enrich: try Unpaywall for papers missing open_access_url
    try:
        from search.unpaywall_lookup import enrich_open_access
        merged = await enrich_open_access(merged)
    except ImportError:
        pass

    return merged


def main():
    parser = argparse.ArgumentParser(description="Unified academic search (5 engines)")
    parser.add_argument("query_positional", nargs="?")
    parser.add_argument("-q", "--query")
    parser.add_argument("-n", "--top", type=int, default=10)
    parser.add_argument("-f", "--format", choices=["markdown", "json"], default="markdown",
                        dest="fmt")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    query = args.query or args.query_positional
    if not query:
        print("Usage: query_all.py 'your search query'", file=sys.stderr)
        sys.exit(1)

    merged = asyncio.run(search_all(query, args.top))

    if args.fmt == "json":
        print(json.dumps(merged[:args.top], ensure_ascii=False, indent=2))
    else:
        print(_format_markdown(merged, args.top, query))


if __name__ == "__main__":
    main()
