"""Main pipeline orchestrator for Paper Distill.

Pool lifecycle (consumption-driven, NOT time-based):
  1. pool-refresh: Search 9 APIs, build pool, assign scan batches
  2. Day 1: scan batch 0 (half pool) -> AI initial review -> push/overflow/discard
  3. Day 2: scan batch 1 (other half) -> AI initial review -> push/overflow/discard
  4. Day 3: scan ALL remaining -> AI initial review -> push/overflow/discard
  5. Day 4+: overflow-only push
  6. Pool exhausted -> back to step 1

Each day max 6 papers pushed (each reviewer picks 5, final review selects ≤6).
Initial review: AI can PUSH / OVERFLOW / DISCARD
Final review: AI can only PUSH / OVERFLOW (no discard)

New topic added -> immediate fresh search for that topic only.

CLI:
    python3 -m paper_digest.pipeline pool-refresh --config <path> --data-dir <path>
    python3 -m paper_digest.pipeline prepare-review --config <path> --data-dir <path>
    python3 -m paper_digest.pipeline finalize --selections '<json>' --config <path> --data-dir <path>
    python3 -m paper_digest.pipeline collect --papers "1,3" --config <path> --data-dir <path>
    python3 -m paper_digest.pipeline summarize-prompt --config <path> --data-dir <path>
    python3 -m paper_digest.pipeline status --data-dir <path>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from paper_digest.pool import (
    load_pool, save_pool, is_pool_exhausted, add_to_pool,
    assign_scan_batches, get_today_scan, advance_scan_day,
    is_overflow_only, mark_pushed, mark_discarded, mark_overflow,
    mark_scanned, get_overflow, needs_refresh, get_unsummarized,
    mark_summarized, pool_stats,
)
from paper_digest.rotation import get_today_topics, force_topic
from paper_digest.reviewer import (
    prepare_initial_review_prompt, prepare_final_review_prompt,
    parse_initial_review, parse_final_review,
)

LOG = logging.getLogger("paper_digest.pipeline")


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_config(path: Path) -> dict:
    if not path.exists():
        LOG.error("Config not found: %s", path)
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def get_history_dois(data_dir: Path) -> set[str]:
    """Load DOIs from papers.jsonl history."""
    papers_path = data_dir / "papers.jsonl"
    if not papers_path.exists():
        return set()
    dois = set()
    for line in papers_path.read_text(encoding="utf-8").strip().splitlines():
        if line.strip():
            doi = (json.loads(line).get("doi") or "").lower()
            if doi:
                dois.add(doi)
    return dois


# ---------------------------------------------------------------------------
# Phase 1: Pool Refresh
# ---------------------------------------------------------------------------

async def _do_search(keywords: list[str], topic_key: str) -> list[dict]:
    """Search all 9 API sources for a topic's keywords."""
    from search.query_all import (
        _search_openalex, _search_s2, _search_pubmed,
        _search_arxiv, _search_pwc, _dedup_merge,
    )

    search_fns: list[tuple[str, object]] = [
        ("openalex", _search_openalex),
        ("s2", _search_s2),
        ("pubmed", _search_pubmed),
        ("arxiv", _search_arxiv),
        ("pwc", _search_pwc),
    ]

    for mod, fn_name, kwargs in [
        ("search.crossref_search", "search_crossref", {"max_results": 20}),
        ("search.europepmc_search", "search_europepmc", {"max_results": 20}),
        ("search.biorxiv_search", "search_biorxiv", {"max_results": 15}),
        ("search.dblp_search", "search_dblp", {"max_results": 20}),
    ]:
        try:
            module = __import__(mod, fromlist=[fn_name])
            fn = getattr(module, fn_name)
            search_fns.append((fn_name.replace("search_", ""), lambda q, _f=fn, _k=kwargs: _f(q, **_k)))
        except ImportError:
            pass

    query = " ".join(keywords)
    if not query.strip():
        return []

    tasks = [fn(query) for _, fn in search_fns]
    names = [name for name, _ in search_fns]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_papers = []
    for name, res in zip(names, results):
        if isinstance(res, Exception):
            LOG.warning("  x %s: %s", name, res)
        elif res:
            LOG.info("  + %s: %d papers", name, len(res))
            for rank, p in enumerate(res):
                p["_relevance_rank"] = rank
            all_papers.extend(res)
        else:
            LOG.info("  - %s: 0", name)

    merged = _dedup_merge(all_papers)
    LOG.info("Topic '%s': %d papers after merge", topic_key, len(merged))
    return merged


async def pool_refresh(config: dict, data_dir: Path, single_topic: str | None = None) -> dict:
    """Refresh the search pool. Called when pool is exhausted or new topic added."""
    pool = load_pool(data_dir)
    topics = config.get("topics", {})
    history_dois = get_history_dois(data_dir)

    if single_topic:
        # New topic: search only that topic, add to existing pool
        if single_topic in topics:
            topic = topics[single_topic]
            LOG.info("Searching new topic: %s", single_topic)
            papers = await _do_search(topic.get("keywords", []), single_topic)
            # Filter out already-pushed DOIs
            papers = [p for p in papers if (p.get("doi") or "").lower() not in history_dois]
            pool = add_to_pool(pool, papers, single_topic)
            # Re-assign scan batches to include new papers
            num_batches = config.get("scan_batches", 3)
            pool = assign_scan_batches(pool, num_batches=num_batches)
            force_topic(data_dir, single_topic)
    else:
        # Check if pool needs full refresh
        if not is_pool_exhausted(pool):
            missing = needs_refresh(pool, topics)
            if not missing:
                stats = pool_stats(pool)
                LOG.info("Pool active, no refresh needed")
                print(json.dumps({"status": "active", **stats}))
                return pool

        # Full refresh: search all topics
        from paper_digest.pool import _empty_pool
        pool = _empty_pool()

        for key, topic in topics.items():
            LOG.info("Searching topic '%s': %s", topic.get("label", key),
                     " ".join(topic.get("keywords", [])))
            papers = await _do_search(topic.get("keywords", []), key)
            papers = [p for p in papers if (p.get("doi") or "").lower() not in history_dois]
            pool = add_to_pool(pool, papers, key)

        # Assign scan batches per config (default: 2)
        num_batches = config.get("scan_batches", 3)
        pool = assign_scan_batches(pool, num_batches=num_batches)

    save_pool(data_dir, pool)
    stats = pool_stats(pool)
    LOG.info("Pool refreshed: %s", stats)
    print(json.dumps({"status": "refreshed", **stats}))
    return pool


# ---------------------------------------------------------------------------
# Phase 2: Prepare Review
# ---------------------------------------------------------------------------

def prepare_review(config: dict, data_dir: Path, dual: bool = False) -> str:
    """Prepare initial review prompt for today's scan batch."""
    pool = load_pool(data_dir)
    topics = config.get("topics", {})
    history_dois = get_history_dois(data_dir)
    custom_focus = config.get("custom_focus", "")
    picks_per_reviewer = config.get("picks_per_reviewer", 5)
    max_push = config.get("paper_count", {}).get("value", 6)

    # Check if pool is exhausted — need refresh first
    if is_pool_exhausted(pool):
        return "POOL_EXHAUSTED: Run pool-refresh to start a new search cycle."

    # Get today's scan batch
    if is_overflow_only(pool):
        # Past all scan days, only overflow left
        candidates = get_overflow(pool)
        if not candidates:
            return "POOL_EXHAUSTED: No overflow papers left. Run pool-refresh."
        is_final = True
    else:
        candidates = get_today_scan(pool)
        scan_day = pool.get("scan_day", 0)
        total_days = pool.get("total_scan_days", 3)
        is_final = scan_day >= total_days - 1

    if not candidates:
        return "NO_CANDIDATES: No papers in today's scan batch."

    prefs = {"topics": topics}

    prompt = prepare_initial_review_prompt(
        candidates, prefs, history_dois,
        custom_focus=custom_focus,
        picks_per_reviewer=picks_per_reviewer,
        is_final_scan=is_final,
    )

    if dual:
        prompt = "DUAL_REVIEW_MODE\n\n" + prompt

    print(prompt)
    return prompt


# ---------------------------------------------------------------------------
# Phase 3: Finalize
# ---------------------------------------------------------------------------

def finalize(
    selections_json: str,
    config: dict,
    data_dir: Path,
    is_final_review: bool = False,
) -> str:
    """Process AI review decisions, update pool, generate outputs."""
    pool = load_pool(data_dir)
    candidates = get_today_scan(pool)

    if is_final_review:
        # Final review: merge from dual reviewers, only push/overflow
        all_picks = [c for c in candidates if c.get("pool_status") in ("overflow", "pending", "scanned")]
        result = parse_final_review(selections_json, all_picks)
        to_push = result["push"]
        to_overflow = result["overflow"]
        to_discard = []
    else:
        # Initial review: push/overflow/discard
        result = parse_initial_review(selections_json, candidates)
        to_push = result["push"]
        to_overflow = result["overflow"]
        to_discard = result["discard"]

    # Update pool statuses
    push_dois = [p.get("doi", "") for p in to_push if p.get("doi")]
    overflow_dois = [p.get("doi", "") for p in to_overflow if p.get("doi")]
    discard_dois = [p.get("doi", "") for p in to_discard if p.get("doi")]

    # Papers not mentioned in any decision: mark as "scanned" (keep for later)
    decided_dois = set(push_dois + overflow_dois + discard_dois)
    undecided_dois = [
        p.get("doi", "") for p in candidates
        if p.get("doi") and p["doi"].lower() not in {d.lower() for d in decided_dois}
        and p.get("pool_status") == "pending"
    ]

    pool = mark_pushed(pool, push_dois)
    pool = mark_overflow(pool, overflow_dois)
    pool = mark_discarded(pool, discard_dois)
    pool = mark_scanned(pool, undecided_dois)

    # Advance scan day
    pool = advance_scan_day(pool)

    save_pool(data_dir, pool)

    # Append to papers.jsonl + pushes.jsonl
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    papers_path = data_dir / "papers.jsonl"
    pushes_path = data_dir / "pushes.jsonl"

    paper_ids = []
    with open(papers_path, "a", encoding="utf-8") as f:
        for p in to_push:
            record = {k: v for k, v in p.items() if not k.startswith("_")}
            record["push_date"] = today
            pid = record.get("doi") or record.get("title", "")
            paper_ids.append(pid)
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    push_record = {
        "date": today,
        "paper_ids": paper_ids,
        "count": len(to_push),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(pushes_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(push_record, ensure_ascii=False) + "\n")

    # Format output
    output = _format_push_message(to_push, today)

    status_parts = []
    if to_overflow:
        status_parts.append(f"{len(to_overflow)} overflow to tomorrow")
    if to_discard:
        status_parts.append(f"{len(to_discard)} discarded")

    stats = pool_stats(pool)
    status_parts.append(f"pool: {stats['by_status'].get('pending', 0)} pending, "
                        f"{stats['by_status'].get('scanned', 0)} scanned, "
                        f"{stats['by_status'].get('overflow', 0)} overflow")

    if status_parts:
        output += "\n---\n" + " | ".join(status_parts)

    if stats["exhausted"]:
        output += "\nPool exhausted. Next run will trigger fresh API search."

    LOG.info("Pushed %d, overflow %d, discard %d", len(to_push), len(to_overflow), len(to_discard))
    print(output)
    return output


def _format_push_message(papers: list[dict], date_str: str) -> str:
    """Format papers as chat message.

    Fixed format per paper:
      1. Title (Year)
         Journal
         - highlight 1
         - highlight 2
         DOI link
    """
    lines = [f"Paper Distill {date_str} | {len(papers)} papers", ""]

    for i, p in enumerate(papers, 1):
        title = p.get("title", "Untitled")
        year = p.get("year", "")
        doi = p.get("doi", "")
        journal = p.get("journal", "")
        tldr = p.get("tldr", "")
        review_reason = p.get("review_reason", "")

        lines.append(f"{i}. **{title}** ({year})")
        if journal:
            lines.append(f"   {journal}")
        # Two-point summary: tldr + review_reason
        if tldr:
            lines.append(f"   - {tldr}")
        if review_reason:
            lines.append(f"   - {review_reason}")
        if doi:
            lines.append(f"   https://doi.org/{doi}")
        lines.append("")

    lines.append('---')
    lines.append('Reply "collect 1 3" to save to Zotero')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Collect
# ---------------------------------------------------------------------------

def do_collect(paper_indices: str, config: dict, data_dir: Path, obsidian_mode: str = "none") -> str:
    """Collect papers to Zotero + optional Obsidian."""
    from paper_digest.collect import (
        resolve_papers_by_index, collect_to_zotero,
        prepare_obsidian_note_summary, prepare_obsidian_note_template,
        collect_interactive_prompt,
    )

    indices = [int(x.strip()) for x in paper_indices.split(",") if x.strip().isdigit()]
    if not indices:
        return "No valid paper indices provided."

    papers = resolve_papers_by_index(indices, data_dir)
    if not papers:
        return "No papers found for the given indices."

    mcp_dir = Path(__file__).resolve().parent.parent
    created = collect_to_zotero(papers, mcp_dir)

    result_lines = []
    if created:
        result_lines.append(f"Added {len(created)} papers to Zotero.")
    else:
        result_lines.append("Zotero integration unavailable or failed.")

    if obsidian_mode == "summary":
        for paper in papers:
            note = prepare_obsidian_note_summary(paper)
            citekey = paper.get("citekey", paper.get("doi", "paper"))
            result_lines.append(f"Created Obsidian note: [[{citekey}]]")
            print(f"OBSIDIAN_NOTE:{citekey}")
            print(note)
            print("---END_NOTE---")
    elif obsidian_mode == "template":
        for paper in papers:
            note = prepare_obsidian_note_template(paper)
            citekey = paper.get("citekey", paper.get("doi", "paper"))
            result_lines.append(f"Created Obsidian template: [[{citekey}]]")
            print(f"OBSIDIAN_NOTE:{citekey}")
            print(note)
            print("---END_NOTE---")
    elif obsidian_mode == "none":
        prompt = collect_interactive_prompt(papers)
        result_lines.append("")
        result_lines.append(prompt)

    return "\n".join(result_lines)


# ---------------------------------------------------------------------------
# Summarizer prompt
# ---------------------------------------------------------------------------

def prepare_summarize_prompt(data_dir: Path, custom_focus: str = "") -> str:
    """Generate summarization prompt for unsummarized papers in today's scan batch."""
    pool = load_pool(data_dir)
    batch = get_today_scan(pool)
    to_summarize = [p for p in batch if not p.get("summary")]

    if not to_summarize:
        return "NO_PAPERS: All papers in today's batch are already summarized."

    lines = [
        "Summarize each paper below with these structured fields.",
        "Keep each field to 1-2 sentences. Be precise and factual.",
        "",
        "Fields to extract:",
        "- general: Natural language summary",
        "- model_algorithm: What model or algorithm is used",
        "- input_data: What data goes in",
        "- output_prediction: What the model predicts or generates",
        "- problem_domain: Research field/area",
        "- pain_point: What existing limitation this addresses",
        "- key_results: Main quantitative results",
    ]

    if custom_focus:
        lines.append(f"- custom: {custom_focus}")

    lines.extend(["", "Reply as JSON array. One object per paper.", ""])

    for i, p in enumerate(to_summarize, 1):
        title = p.get("title", "")
        abstract = p.get("abstract", "")
        doi = p.get("doi", "")
        lines.append(f"### Paper {i}: {title}")
        if doi:
            lines.append(f"DOI: {doi}")
        if abstract:
            lines.append(f"Abstract: {abstract}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def show_status(data_dir: Path) -> str:
    pool = load_pool(data_dir)
    stats = pool_stats(pool)
    return json.dumps(stats, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Paper Distill Pipeline")
    parser.add_argument("action", choices=[
        "pool-refresh", "prepare-review", "finalize",
        "collect", "summarize-prompt", "status",
    ])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--topic", type=str, help="Single topic key for new topic search")
    parser.add_argument("--dual", action="store_true", help="Enable dual review mode")
    parser.add_argument("--final", action="store_true", help="Final review (no discard)")
    parser.add_argument("--selections", type=str, help="Review selections JSON")
    parser.add_argument("--papers", type=str, help="Paper indices for collect (e.g. '1,3')")
    parser.add_argument("--obsidian-mode", type=str, default="none",
                        choices=["summary", "template", "none"])
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(name)s %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    config = {}
    if args.config:
        config = load_config(args.config)

    data_dir = args.data_dir or Path.home() / ".openclaw" / "skills" / "paper-distill" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    if args.action == "pool-refresh":
        asyncio.run(pool_refresh(config, data_dir, single_topic=args.topic))

    elif args.action == "prepare-review":
        dual = args.dual or config.get("review_mode") == "dual"
        prepare_review(config, data_dir, dual=dual)

    elif args.action == "finalize":
        if not args.selections:
            parser.error("--selections required for finalize")
        finalize(args.selections, config, data_dir, is_final_review=args.final)

    elif args.action == "collect":
        if not args.papers:
            parser.error("--papers required for collect")
        result = do_collect(args.papers, config, data_dir, args.obsidian_mode)
        print(result)

    elif args.action == "summarize-prompt":
        custom_focus = config.get("custom_focus", "")
        prompt = prepare_summarize_prompt(data_dir, custom_focus)
        print(prompt)

    elif args.action == "status":
        print(show_status(data_dir))


if __name__ == "__main__":
    main()
