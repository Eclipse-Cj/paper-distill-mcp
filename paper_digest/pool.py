"""Search pool management.

The pool stores all API search results + structured summaries.
Lifecycle is consumption-driven, NOT time-based:
  - Pool refreshes when all papers are pushed/discarded/overflow-done
  - Each day scans only a portion (batch) of the pool
  - New topic triggers immediate fresh search

Paper statuses:
  pending   - not yet reviewed
  scanned   - reviewed in this scan batch, kept for later
  overflow  - selected but overflowed, push next day
  pushed    - delivered to user
  discarded - AI decided to remove from pool

Scan schedule:
  Day 1: scan batch 1 (first half of pending)
  Day 2: scan batch 2 (second half of pending)
  Day 3: scan ALL remaining (pending + scanned from day 1&2)
  Day 4+: overflow-only push (no new scan)
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path

LOG = logging.getLogger("paper_digest.pool")

POOL_FILE = "search_pool.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _empty_pool() -> dict:
    return {
        "created_at": _now(),
        "topics_searched": [],
        "scan_day": 0,
        "total_scan_days": 3,
        "scan_history": [],
        "papers": [],
    }


def load_pool(data_dir: Path) -> dict:
    """Load pool from disk. Returns empty pool if missing."""
    pool_path = data_dir / POOL_FILE
    if not pool_path.exists():
        return _empty_pool()
    try:
        pool = json.loads(pool_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty_pool()
    return pool


def save_pool(data_dir: Path, pool: dict) -> None:
    """Save pool to disk."""
    data_dir.mkdir(parents=True, exist_ok=True)
    pool_path = data_dir / POOL_FILE
    pool_path.write_text(
        json.dumps(pool, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def is_pool_exhausted(pool: dict) -> bool:
    """Check if pool needs a fresh API search.

    Pool is exhausted when:
    - No papers at all
    - No pending/scanned/overflow papers left
    """
    papers = pool.get("papers", [])
    if not papers:
        return True
    active_statuses = {"pending", "scanned", "overflow"}
    active = [p for p in papers if p.get("pool_status") in active_statuses]
    return len(active) == 0


def _normalize_doi(doi: str) -> str:
    return doi.strip().lower() if doi else ""


def _normalize_title(title: str) -> str:
    return title.strip().lower().rstrip(".")


def add_to_pool(pool: dict, papers: list[dict], topic_key: str) -> dict:
    """Add new papers to pool, dedup by DOI/title. Tag with topic."""
    existing_dois = {_normalize_doi(p.get("doi", "")) for p in pool["papers"] if p.get("doi")}
    existing_titles = {_normalize_title(p.get("title", "")) for p in pool["papers"]}

    added = 0
    for paper in papers:
        doi = _normalize_doi(paper.get("doi", ""))
        title = _normalize_title(paper.get("title", ""))

        if doi and doi in existing_dois:
            for ep in pool["papers"]:
                if _normalize_doi(ep.get("doi", "")) == doi:
                    tags = set(ep.get("topic_tags", []))
                    tags.add(topic_key)
                    ep["topic_tags"] = list(tags)
                    break
            continue

        if title and title in existing_titles:
            continue

        paper["pool_status"] = "pending"
        paper["added_at"] = _now()
        paper.setdefault("summary", None)
        paper.setdefault("overflow_priority", 0)
        paper.setdefault("scan_batch", None)
        tags = set(paper.get("topic_tags", []))
        tags.add(topic_key)
        paper["topic_tags"] = list(tags)

        pool["papers"].append(paper)
        if doi:
            existing_dois.add(doi)
        if title:
            existing_titles.add(title)
        added += 1

    if topic_key not in pool.get("topics_searched", []):
        pool.setdefault("topics_searched", []).append(topic_key)

    LOG.info("Added %d papers for topic '%s' (pool total: %d)", added, topic_key, len(pool["papers"]))
    return pool


# ---------------------------------------------------------------------------
# Scan batch management
# ---------------------------------------------------------------------------

def assign_scan_batches(pool: dict, num_batches: int = 3) -> dict:
    """Assign pending papers to scan batches (done once after pool creation).

    Splits pending papers into `num_batches` groups.
    Day 1 scans batch 0, Day 2 scans batch 1, Day 3 scans everything remaining.
    """
    pending = [p for p in pool["papers"] if p.get("pool_status") == "pending" and p.get("scan_batch") is None]
    if not pending:
        return pool

    batch_size = math.ceil(len(pending) / num_batches)
    for i, paper in enumerate(pending):
        paper["scan_batch"] = i // batch_size

    pool["total_scan_days"] = num_batches + 1  # +1 for the "scan all remaining" day
    LOG.info("Assigned %d papers to %d scan batches (batch_size ~%d)", len(pending), num_batches, batch_size)
    return pool


def get_today_scan(pool: dict) -> list[dict]:
    """Get papers for today's scan based on current scan_day.

    Day 0: batch 0 (first half)
    Day 1: batch 1 (second half)
    Day 2+: ALL remaining (pending + scanned from previous days)

    Also always includes overflow papers (priority push).
    """
    scan_day = pool.get("scan_day", 0)
    total_days = pool.get("total_scan_days", 3)

    overflow = [p for p in pool["papers"] if p.get("pool_status") == "overflow"]

    if scan_day < total_days - 1:
        # Scan a specific batch
        batch = [p for p in pool["papers"]
                 if p.get("pool_status") == "pending" and p.get("scan_batch") == scan_day]
        LOG.info("Scan day %d: batch %d (%d papers) + %d overflow", scan_day, scan_day, len(batch), len(overflow))
    else:
        # Final scan day: everything remaining
        batch = [p for p in pool["papers"]
                 if p.get("pool_status") in ("pending", "scanned")]
        LOG.info("Scan day %d (final): %d remaining + %d overflow", scan_day, len(batch), len(overflow))

    # Overflow papers always come first
    return overflow + batch


def advance_scan_day(pool: dict) -> dict:
    """Move to next scan day. Record in history."""
    pool["scan_day"] = pool.get("scan_day", 0) + 1
    pool.setdefault("scan_history", []).append({
        "day": pool["scan_day"],
        "date": _today(),
    })
    return pool


def is_overflow_only(pool: dict) -> bool:
    """Check if we're past all scan days (only overflow papers left to push)."""
    scan_day = pool.get("scan_day", 0)
    total_days = pool.get("total_scan_days", 3)
    return scan_day >= total_days


# ---------------------------------------------------------------------------
# Paper status transitions
# ---------------------------------------------------------------------------

def mark_pushed(pool: dict, dois: list[str]) -> dict:
    """Mark papers as 'pushed' by DOI."""
    doi_set = {_normalize_doi(d) for d in dois}
    for paper in pool["papers"]:
        if _normalize_doi(paper.get("doi", "")) in doi_set:
            paper["pool_status"] = "pushed"
            paper["pushed_at"] = _now()
    return pool


def mark_discarded(pool: dict, dois: list[str]) -> dict:
    """AI decided these papers are not relevant. Remove from active pool."""
    doi_set = {_normalize_doi(d) for d in dois}
    for paper in pool["papers"]:
        if _normalize_doi(paper.get("doi", "")) in doi_set:
            paper["pool_status"] = "discarded"
    LOG.info("Discarded %d papers", len(doi_set))
    return pool


def mark_overflow(pool: dict, dois: list[str]) -> dict:
    """Mark papers as overflow — push next day."""
    doi_set = {_normalize_doi(d) for d in dois}
    for paper in pool["papers"]:
        if _normalize_doi(paper.get("doi", "")) in doi_set:
            paper["pool_status"] = "overflow"
            paper["overflow_priority"] = paper.get("overflow_priority", 0) + 1
    LOG.info("Overflowed %d papers to next day", len(doi_set))
    return pool


def mark_scanned(pool: dict, dois: list[str]) -> dict:
    """Papers were scanned but not selected or discarded. Keep for final day."""
    doi_set = {_normalize_doi(d) for d in dois}
    for paper in pool["papers"]:
        if _normalize_doi(paper.get("doi", "")) in doi_set:
            if paper.get("pool_status") == "pending":
                paper["pool_status"] = "scanned"
    return pool


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_overflow(pool: dict) -> list[dict]:
    """Return overflow papers, highest priority first."""
    overflow = [p for p in pool["papers"] if p.get("pool_status") == "overflow"]
    overflow.sort(key=lambda p: p.get("overflow_priority", 0), reverse=True)
    return overflow


def needs_refresh(pool: dict, topics: dict) -> list[str]:
    """Return topic keys not yet searched in this pool."""
    searched = set(pool.get("topics_searched", []))
    return [key for key in topics if key not in searched]


def get_unsummarized(pool: dict) -> list[dict]:
    """Return pending papers that haven't been summarized yet."""
    return [p for p in pool["papers"]
            if p.get("pool_status") in ("pending", "scanned") and not p.get("summary")]


def mark_summarized(pool: dict, doi: str, summary: dict) -> dict:
    """Attach structured summary to a paper."""
    doi_norm = _normalize_doi(doi)
    for paper in pool["papers"]:
        if _normalize_doi(paper.get("doi", "")) == doi_norm:
            paper["summary"] = summary
            break
    return pool


def pool_stats(pool: dict) -> dict:
    """Return pool statistics."""
    papers = pool.get("papers", [])
    status_counts = {}
    for p in papers:
        s = p.get("pool_status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    return {
        "total": len(papers),
        "by_status": status_counts,
        "summarized": sum(1 for p in papers if p.get("summary")),
        "scan_day": pool.get("scan_day", 0),
        "total_scan_days": pool.get("total_scan_days", 3),
        "topics_searched": pool.get("topics_searched", []),
        "exhausted": is_pool_exhausted(pool),
        "overflow_only": is_overflow_only(pool),
    }
