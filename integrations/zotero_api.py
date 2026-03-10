"""
Zotero Web API integration via pyzotero.

Features:
  - Add papers to a Zotero library from papers.jsonl
  - Auto-categorise into collections by topic tag
  - Create journal-article items with full metadata
  - Auto-enrich incomplete metadata via CrossRef/DataCite DOI resolution

Requires ZOTERO_LIBRARY_ID and ZOTERO_API_KEY in .env.

CLI usage:
  python integrations/zotero_api.py \
    --paper-ids "10.1234/abc" "10.5678/xyz" \
    --history   data/papers.jsonl
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

try:
    from pyzotero import zotero
except ImportError:
    zotero = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("paper-distill.zotero")

# Topic -> Zotero collection name mapping (for pushed papers)
# Matches user's actual Zotero folders; new folders auto-created if needed
TOPIC_COLLECTION_MAP: dict[str, str] = {
    "llm-reasoning":       "LLM",
    "rag-retrieval":       "LLM",
    "llm-agents":          "LLM",
    "code-generation":     "LLM",
    "multimodal":          "Multimodal",
    "diffusion-models":    "Generative Models",
    "reinforcement-learning": "RL",
}

# Research area -> Zotero collection name mapping (for non-pushed papers)
AREA_COLLECTION_MAP: dict[str, str] = {
    "LLM":              "LLM",
    "RAG":              "LLM",
    "Agents":           "LLM",
    "Code Generation":  "LLM",
    "Multimodal":       "Multimodal",
    "Diffusion":        "Generative Models",
    "RL":               "RL",
}


# ── DOI metadata enrichment ─────────────────────────────────────────────────

def _enrich_from_crossref(doi: str) -> dict:
    """Resolve full metadata from a DOI via CrossRef API.

    Returns a dict with title, authors, journal, year, abstract (if available).
    Returns empty dict on failure.
    """
    if not doi:
        return {}

    url = f"https://api.crossref.org/works/{doi}"
    headers = {"User-Agent": "paper-distill/1.0 (https://github.com/Eclipse-Cj/paper-distill-mcp)"}

    try:
        with httpx.Client(timeout=15.0, headers=headers) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                logger.debug("CrossRef lookup failed for %s: HTTP %d", doi, resp.status_code)
                return {}
            item = resp.json().get("message", {})
    except (httpx.RequestError, Exception) as e:
        logger.debug("CrossRef lookup error for %s: %s", doi, e)
        return {}

    # Parse authors
    authors = []
    for author in item.get("author", []):
        given = author.get("given", "")
        family = author.get("family", "")
        if family:
            authors.append(f"{given} {family}".strip())

    # Parse year from date fields
    year = None
    for date_field in ("published-print", "published-online", "created"):
        date_parts = item.get(date_field, {}).get("date-parts", [[]])
        if date_parts and date_parts[0] and date_parts[0][0]:
            year = date_parts[0][0]
            break

    # Parse journal
    container = item.get("container-title", [])
    journal = container[0] if container else ""

    # Parse abstract (strip JATS XML tags)
    abstract = item.get("abstract", "")
    if abstract:
        abstract = re.sub(r"<[^>]+>", "", abstract)

    # Parse title
    title_list = item.get("title", [])
    title = title_list[0] if title_list else ""

    result = {}
    if title:
        result["title"] = title
    if authors:
        result["authors"] = authors
    if journal:
        result["journal"] = journal
    if year:
        result["year"] = year
    if abstract:
        result["abstract"] = abstract

    if result:
        logger.info("Enriched metadata from CrossRef for DOI %s: got %s",
                     doi, ", ".join(result.keys()))

    return result


def _ensure_metadata(paper: dict) -> dict:
    """Ensure a paper dict has complete metadata.

    If critical fields (title, authors) are missing but DOI is present,
    fetches metadata from CrossRef and fills in the gaps.

    Returns the (possibly enriched) paper dict (mutated in place).
    """
    doi = paper.get("doi", "")
    title = (paper.get("title") or "").strip()

    # Only enrich if we have a DOI but missing critical metadata
    if doi and not title:
        logger.info("Paper has DOI (%s) but no title — enriching from CrossRef", doi)
        enriched = _enrich_from_crossref(doi)
        for key, value in enriched.items():
            # Only fill in missing fields, don't overwrite existing data
            if not paper.get(key):
                paper[key] = value

    return paper


# ── Zotero client ──────────────────────────────────────────────────────────

class ZoteroClient:
    """Wrapper around pyzotero for Paper Distill operations."""

    def __init__(
        self,
        library_id: str,
        api_key: str,
        library_type: str = "user",
    ):
        if zotero is None:
            raise ImportError(
                "pyzotero is not installed. Run: pip install pyzotero"
            )
        self.zot = zotero.Zotero(library_id, library_type, api_key)
        self._collections_cache: dict[str, str] | None = None

    # ── collections ────────────────────────────────────────────────────

    def _load_collections(self) -> dict[str, str]:
        """Load all collections as {name: key} mapping."""
        if self._collections_cache is not None:
            return self._collections_cache

        collections = self.zot.collections()
        mapping: dict[str, str] = {}
        for coll in collections:
            data = coll.get("data", {})
            mapping[data.get("name", "")] = data.get("key", "")

        self._collections_cache = mapping
        return mapping

    def get_or_create_collection(self, name: str) -> str:
        """Get collection key by name, creating it if it doesn't exist."""
        mapping = self._load_collections()

        if name in mapping:
            return mapping[name]

        # Create new collection
        logger.info("Creating Zotero collection: %s", name)
        payload = [{"name": name}]
        resp = self.zot.create_collections(payload)

        # pyzotero returns the created collection data
        if isinstance(resp, dict) and "successful" in resp:
            for _idx, item in resp["successful"].items():
                key = item.get("data", {}).get("key", item.get("key", ""))
                mapping[name] = key
                self._collections_cache = mapping
                return key

        # Fallback: reload collections
        self._collections_cache = None
        mapping = self._load_collections()
        return mapping.get(name, "")

    def get_collection_for_paper(self, paper: dict) -> str | None:
        """Determine the Zotero collection for a paper based on topic tags."""
        topic_tags = paper.get("topic_tags", [])
        matched_topic = paper.get("_matched_topic", "")

        # Try matched topic first
        if matched_topic and matched_topic in TOPIC_COLLECTION_MAP:
            collection_name = TOPIC_COLLECTION_MAP[matched_topic]
            return self.get_or_create_collection(collection_name)

        # Fallback: try topic tags
        for tag in topic_tags:
            tag_key = tag.lower().replace(" ", "-")
            if tag_key in TOPIC_COLLECTION_MAP:
                collection_name = TOPIC_COLLECTION_MAP[tag_key]
                return self.get_or_create_collection(collection_name)

        return None

    # ── item creation ──────────────────────────────────────────────────

    def paper_to_zotero_item(self, paper: dict) -> dict:
        """Convert a paper dict to a Zotero journal article item template."""
        template = self.zot.item_template("journalArticle")

        template["title"] = paper.get("title", "")
        template["DOI"] = paper.get("doi", "")
        template["url"] = f"https://doi.org/{paper['doi']}" if paper.get("doi") else ""
        template["publicationTitle"] = paper.get("journal", "")
        template["date"] = (
            paper.get("published_date")
            or paper.get("date")
            or str(paper.get("year", ""))
        )
        template["abstractNote"] = paper.get("abstract", "")

        # Authors
        authors_raw = paper.get("authors", "")
        creators = _parse_authors(authors_raw)
        if creators:
            template["creators"] = creators

        # Tags
        tags = []
        for t in paper.get("topic_tags", []):
            tags.append({"tag": t})
        tags.append({"tag": "paper-distill"})
        template["tags"] = tags

        # Extra field for citekey and scores
        extra_parts = []
        citekey = paper.get("citekey", "")
        if citekey:
            extra_parts.append(f"Citation Key: {citekey}")
        if paper.get("tldr"):
            extra_parts.append(f"TLDR: {paper['tldr']}")
        if paper.get("relevance_note"):
            extra_parts.append(f"Relevance: {paper['relevance_note']}")
        if extra_parts:
            template["extra"] = "\n".join(extra_parts)

        # Collection
        collection_key = self.get_collection_for_paper(paper)
        if collection_key:
            template["collections"] = [collection_key]

        return template

    def add_items(self, papers: list[dict]) -> list[dict]:
        """
        Create Zotero items for multiple papers.

        Automatically enriches papers with incomplete metadata via CrossRef
        before creating Zotero items.

        Returns list of successfully created item data dicts.
        """
        # Enrich papers with missing metadata before creating items
        for paper in papers:
            _ensure_metadata(paper)

        items = [self.paper_to_zotero_item(p) for p in papers]

        if not items:
            return []

        # pyzotero can create up to 50 items at a time
        results: list[dict] = []
        batch_size = 50

        for i in range(0, len(items), batch_size):
            batch = items[i : i + batch_size]
            logger.info(
                "Creating Zotero items: batch %d-%d of %d",
                i + 1, min(i + batch_size, len(items)), len(items),
            )
            try:
                resp = self.zot.create_items(batch)
                if isinstance(resp, dict):
                    for _idx, item_data in resp.get("successful", {}).items():
                        results.append(item_data)
                    failed = resp.get("failed", {})
                    if failed:
                        logger.warning("Failed items: %s", failed)
                else:
                    # Some pyzotero versions return the items directly
                    if isinstance(resp, list):
                        results.extend(resp)
            except Exception as e:
                logger.error("Zotero API error: %s", e)
                raise

        logger.info("Successfully created %d Zotero items", len(results))
        return results


# ── helper functions ───────────────────────────────────────────────────────

def _parse_authors(authors_raw) -> list[dict]:
    """
    Parse author strings/lists into Zotero creator dicts.

    Handles formats:
      - list: ["John Smith", "Jane Doe"]
      - str:  "Smith, John; Doe, Jane" or "John Smith, Jane Doe"
    """
    creators: list[dict] = []

    if isinstance(authors_raw, list):
        author_list = authors_raw
    elif isinstance(authors_raw, str):
        if ";" in authors_raw:
            author_list = [a.strip() for a in authors_raw.split(";") if a.strip()]
        else:
            author_list = [a.strip() for a in authors_raw.split(",") if a.strip()]
    else:
        return creators

    for name in author_list:
        if not name:
            continue

        if "," in name:
            # "Last, First" format
            parts = name.split(",", 1)
            creators.append({
                "creatorType": "author",
                "lastName": parts[0].strip(),
                "firstName": parts[1].strip() if len(parts) > 1 else "",
            })
        else:
            # "First Last" format
            parts = name.strip().split()
            if len(parts) >= 2:
                creators.append({
                    "creatorType": "author",
                    "lastName": parts[-1],
                    "firstName": " ".join(parts[:-1]),
                })
            else:
                creators.append({
                    "creatorType": "author",
                    "name": name,
                })

    return creators


def _load_jsonl(path: Path) -> list[dict]:
    """Load a .jsonl file; return [] if missing or empty."""
    if not path.exists():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


# ── public API (called by bot/handlers.py) ─────────────────────────────────

async def add_papers_to_zotero(
    project_root: Path | str,
    paper_ids: list[str],
) -> list[dict]:
    """
    Look up papers in papers.jsonl by ID/DOI, create Zotero items.

    This is the main entry point called by the Telegram bot's /collect handler.
    Runs the sync Zotero API in an executor to avoid blocking the event loop.
    """
    import asyncio

    project_root = Path(project_root)
    env_path = project_root / ".env"
    load_dotenv(env_path)

    library_id = os.getenv("ZOTERO_LIBRARY_ID", "")
    api_key    = os.getenv("ZOTERO_API_KEY", "")

    if not library_id or not api_key:
        raise ValueError(
            "ZOTERO_LIBRARY_ID and ZOTERO_API_KEY must be set in .env"
        )

    # Load paper data
    papers_path = project_root / "data" / "papers.jsonl"
    all_papers = _load_jsonl(papers_path)

    # Build lookup by ID and DOI
    lookup: dict[str, dict] = {}
    for p in all_papers:
        pid = p.get("id", "")
        doi = p.get("doi", "")
        if pid:
            lookup[pid] = p
        if doi:
            lookup[doi.lower()] = p

    # Resolve requested papers
    papers_to_add: list[dict] = []
    for pid in paper_ids:
        paper = lookup.get(pid) or lookup.get(pid.lower())
        if paper:
            papers_to_add.append(paper)
        else:
            logger.warning("Paper not found in history: %s", pid)

    if not papers_to_add:
        logger.warning("No papers found to add to Zotero")
        return []

    # Run sync Zotero API in executor
    def _sync_add():
        client = ZoteroClient(library_id, api_key)
        return client.add_items(papers_to_add)

    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, _sync_add)
    return results


async def add_papers_to_zotero_by_data(
    project_root: Path | str,
    papers: list[dict],
) -> list[dict]:
    """
    Add papers directly (not by ID lookup) to Zotero.
    Used for non-pushed papers extracted from user's research document.
    Maps paper._area to Zotero collection via AREA_COLLECTION_MAP.
    """
    import asyncio

    project_root = Path(project_root)
    env_path = project_root / ".env"
    load_dotenv(env_path)

    library_id = os.getenv("ZOTERO_LIBRARY_ID", "")
    api_key    = os.getenv("ZOTERO_API_KEY", "")

    if not library_id or not api_key:
        raise ValueError("ZOTERO_LIBRARY_ID and ZOTERO_API_KEY must be set in .env")

    if not papers:
        return []

    def _sync_add():
        client = ZoteroClient(library_id, api_key)

        # For each paper, map _area to a collection
        for paper in papers:
            area = paper.get("_area", "")
            if area and area in AREA_COLLECTION_MAP:
                collection_name = AREA_COLLECTION_MAP[area]
                collection_key = client.get_or_create_collection(collection_name)
                if collection_key:
                    paper["_zotero_collection_key"] = collection_key

        return client.add_items(papers)

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_add)


def add_papers_to_zotero_sync(
    project_root: Path | str,
    paper_ids: list[str],
) -> list[dict]:
    """
    Synchronous version of add_papers_to_zotero for CLI usage.
    """
    project_root = Path(project_root)
    env_path = project_root / ".env"
    load_dotenv(env_path)

    library_id = os.getenv("ZOTERO_LIBRARY_ID", "")
    api_key    = os.getenv("ZOTERO_API_KEY", "")

    if not library_id or not api_key:
        raise ValueError(
            "ZOTERO_LIBRARY_ID and ZOTERO_API_KEY must be set in .env"
        )

    papers_path = project_root / "data" / "papers.jsonl"
    all_papers = _load_jsonl(papers_path)

    lookup: dict[str, dict] = {}
    for p in all_papers:
        pid = p.get("id", "")
        doi = p.get("doi", "")
        if pid:
            lookup[pid] = p
        if doi:
            lookup[doi.lower()] = p

    papers_to_add: list[dict] = []
    for pid in paper_ids:
        paper = lookup.get(pid) or lookup.get(pid.lower())
        if paper:
            papers_to_add.append(paper)
        else:
            logger.warning("Paper not found in history: %s", pid)

    if not papers_to_add:
        logger.warning("No papers found to add to Zotero")
        return []

    client = ZoteroClient(library_id, api_key)
    return client.add_items(papers_to_add)


# ── CLI ────────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add papers to Zotero via Web API."
    )
    parser.add_argument(
        "--paper-ids", nargs="+", required=True,
        help="Paper IDs or DOIs to add to Zotero",
    )
    parser.add_argument(
        "--history", default="data/papers.jsonl",
        help="Path to papers.jsonl (default: data/papers.jsonl)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path)

    args = parse_args(argv)
    project_root = Path(__file__).resolve().parent.parent

    paper_ids = args.paper_ids

    logger.info("Adding %d paper(s) to Zotero...", len(paper_ids))

    try:
        results = add_papers_to_zotero_sync(project_root, paper_ids)
        logger.info("Successfully added %d items to Zotero", len(results))
        for item in results:
            data = item.get("data", item) if isinstance(item, dict) else {}
            logger.info(
                "  - %s (key=%s)",
                data.get("title", "?")[:60],
                data.get("key", "?"),
            )
    except ImportError as e:
        logger.error("Missing dependency: %s", e)
        sys.exit(1)
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)
    except Exception as e:
        logger.error("Zotero API error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
