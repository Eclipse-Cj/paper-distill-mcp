"""
Generate all daily output files from the final selected papers.

Input:  data/tmp_selected.json (final selected papers with AI annotations)

Outputs:
  a. Append to data/pushes.jsonl
  b. Append to data/papers.jsonl
  c. Create  site/src/content/digests/YYYY-MM-DD.json (for Astro site)
  d. Create  obsidian/Paper Distill/daily-log/YYYY-MM-DD.md (daily digest note)
  e. Create  obsidian/Paper Distill/papers/<citekey>.md (per-paper notes)

CLI usage:
  python generate/daily_digest.py \
    --papers data/tmp_selected.json \
    --date   2026-02-25
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Local imports (same package)
from generate.obsidian_note import (
    generate_citekey, write_paper_notes, format_authors_short,
    write_research_notes, write_topic_learning_log,
)
from generate.telegram_message import format_daily_push
from generate.validation import ensure_within, validate_date

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("paper-distill.daily")


# ── output generators ──────────────────────────────────────────────────────

def append_pushes_jsonl(papers: list[dict], date: str, pushes_path: Path) -> None:
    """Append a push record to pushes.jsonl."""
    pushes_path.parent.mkdir(parents=True, exist_ok=True)

    paper_ids = []
    for p in papers:
        pid = p.get("id") or p.get("doi") or p.get("citekey") or ""
        paper_ids.append(pid)

    record = {
        "date": date,
        "paper_ids": paper_ids,
        "count": len(papers),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(pushes_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.info("Appended push record to %s (%d papers)", pushes_path, len(papers))


def append_papers_jsonl(papers: list[dict], date: str, papers_path: Path) -> None:
    """Append individual paper records to papers.jsonl.

    Preserves ALL fields from the paper dict (background, method, results,
    innovation, inspiration, etc.) so Obsidian notes can use them later.
    """
    papers_path.parent.mkdir(parents=True, exist_ok=True)

    # Fields that must exist (with defaults)
    REQUIRED = {
        "id": "", "doi": "", "title": "", "authors": "", "year": "",
        "journal": "", "jcr_quartile": "", "cas_zone": "", "impact_factor": "",
        "topic_tags": [], "tldr": "", "relevance_note": "", "citekey": "",
        "source": "", "citation_count": 0, "published_date": "",
        "background": "", "method": "", "results": "",
        "innovation": "", "inspiration": "",
    }

    with open(papers_path, "a", encoding="utf-8") as f:
        for paper in papers:
            # Start with all fields from paper (preserve everything AI wrote)
            record = dict(paper)
            # Ensure required keys exist
            for key, default in REQUIRED.items():
                record.setdefault(key, default)
            # Normalize
            record["id"] = record["id"] or record["doi"] or record["citekey"]
            record["push_date"] = date
            record["published_date"] = (
                record["published_date"] or paper.get("date", "")
            )
            # Remove internal keys
            for k in list(record):
                if k.startswith("_"):
                    del record[k]
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.info("Appended %d paper records to %s", len(papers), papers_path)


def create_astro_digest(papers: list[dict], date: str, site_dir: Path) -> Path:
    """
    Create a digest JSON file for the Astro site.

    Output: site/src/content/digests/YYYY-MM-DD.json
    """
    date = validate_date(date)
    digest_dir = site_dir / "src" / "content" / "digests"
    digest_dir.mkdir(parents=True, exist_ok=True)

    digest = {
        "date": date,
        "paper_count": len(papers),
        "papers": [],
    }

    for i, paper in enumerate(papers, 1):
        entry = {
            "index": i,
            "title": paper.get("title", ""),
            "authors": format_authors_short(paper),
            "year": paper.get("year", ""),
            "journal": paper.get("journal", ""),
            "doi": paper.get("doi", ""),
            "jcr_quartile": paper.get("jcr_quartile", ""),
            "cas_zone": paper.get("cas_zone", ""),
            "impact_factor": paper.get("impact_factor", ""),
            "topic_tags": paper.get("topic_tags", []),
            "tldr": paper.get("tldr", ""),
            "background": paper.get("background", ""),
            "method": paper.get("method", "") or paper.get("methods", ""),
            "results": paper.get("results", ""),
            "innovation": paper.get("innovation", ""),
            "inspiration": paper.get("inspiration", ""),
            "relevance_note": paper.get("relevance_note", ""),
            "citekey": paper.get("citekey", ""),
        }
        digest["papers"].append(entry)

    output_path = ensure_within(digest_dir, digest_dir / f"{date}.json")
    output_path.write_text(
        json.dumps(digest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Created Astro digest: %s", output_path)
    return output_path


def create_daily_obsidian_note(
    papers: list[dict],
    date: str,
    daily_log_dir: Path,
) -> Path:
    """
    Create the daily digest markdown note for Obsidian.

    This is a summary note linking to individual paper notes.
    Output: obsidian/Paper Distill/daily-log/YYYY-MM-DD.md
    """
    date = validate_date(date)
    daily_log_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "---",
        f"date: {date}",
        f"paper_count: {len(papers)}",
        "type: daily-digest",
        "source: paper-distill",
        "---",
        "",
        f"# 论文推送 {date}",
        "",
        f"共 {len(papers)} 篇论文。",
        "",
    ]

    # Group by topic
    topic_groups: dict[str, list[dict]] = {}
    for paper in papers:
        topic = paper.get("_matched_topic") or "other"
        topic_groups.setdefault(topic, []).append(paper)

    # Section labels
    topic_labels: dict[str, str] = {
        "llm-reasoning": "🤖 LLM Reasoning",
        "rag-retrieval": "🔍 RAG & Retrieval",
        "llm-news": "🤖 LLM 动态",
        "llm-agents": "🤖 LLM Agents",
        "code-generation": "💻 Code Generation",
        "multimodal": "🖼️ Multimodal",
        "diffusion-models": "🎨 Diffusion Models",
        "other": "📄 其他",
    }

    for topic_key, group in topic_groups.items():
        label = topic_labels.get(topic_key, f"📄 {topic_key}")
        lines.append(f"## {label}")
        lines.append("")

        for paper in group:
            citekey = paper.get("citekey", "")
            title = paper.get("title", "Untitled")
            authors_short = format_authors_short(paper)
            journal = paper.get("journal", "")
            year = paper.get("year", "")
            tldr = paper.get("tldr", "")
            doi = paper.get("doi", "")
            impact_factor = paper.get("impact_factor", "")
            jcr_quartile = paper.get("jcr_quartile", "")
            cas_zone = paper.get("cas_zone", "")

            # Obsidian wikilink to paper note
            lines.append(f"### [[论文阅读/{citekey}|{title}]]")

            meta_parts = []
            if authors_short and authors_short != "Unknown":
                meta_parts.append(f"**{authors_short}** ({year})")
            elif year:
                meta_parts.append(f"({year})")
            if journal:
                meta_parts.append(f"*{journal}*")
            if jcr_quartile or cas_zone:
                q_parts = [jcr_quartile, cas_zone]
                meta_parts.append(" ".join(p for p in q_parts if p))
            if impact_factor:
                meta_parts.append(f"IF {impact_factor}")
            if meta_parts:
                lines.append(" ".join(meta_parts))

            if tldr:
                lines.append(f"> {tldr}")

            if doi:
                lines.append(f"[DOI](https://doi.org/{doi})")

            lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"_Generated by Paper Distill on {date}_")

    output_path = ensure_within(daily_log_dir, daily_log_dir / f"{date}.md")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Created daily Obsidian note: %s", output_path)
    return output_path


# ── main orchestrator ──────────────────────────────────────────────────────

def generate_all(
    papers: list[dict],
    date: str,
    project_root: Path,
    topics_data: dict | None = None,
) -> dict[str, str]:
    """
    Generate all output files.  Returns a dict of output type -> path.

    If topics_data is provided (from user's research md document),
    also generates research notes and topic-based learning log.

    Raises:
        ValueError: if ``date`` is not a YYYY-MM-DD date. Nothing is written
            in that case.
    """
    date = validate_date(date)
    results: dict[str, str] = {}

    # Ensure each paper has a citekey
    for paper in papers:
        if not paper.get("citekey"):
            paper["citekey"] = generate_citekey(paper)
        # Ensure ID is set
        if not paper.get("id"):
            paper["id"] = paper.get("doi") or paper["citekey"]

    # (a) pushes.jsonl
    pushes_path = project_root / "data" / "pushes.jsonl"
    append_pushes_jsonl(papers, date, pushes_path)
    results["pushes_jsonl"] = str(pushes_path)

    # (b) papers.jsonl
    papers_path = project_root / "data" / "papers.jsonl"
    append_papers_jsonl(papers, date, papers_path)
    results["papers_jsonl"] = str(papers_path)

    # (c) Astro digest JSON
    site_dir = project_root / "site"
    astro_path = create_astro_digest(papers, date, site_dir)
    results["astro_digest"] = str(astro_path)

    # (d) Daily Obsidian note
    daily_log_dir = project_root / "obsidian" / "Paper Distill" / "daily-log"
    daily_note_path = create_daily_obsidian_note(papers, date, daily_log_dir)
    results["daily_note"] = str(daily_note_path)

    # (e) 论文卡片不再自动生成！只有用户 /collect 时才创建。

    # (f) Research notes + learning log (if topics_data provided)
    if topics_data:
        base_dir = project_root / "obsidian" / "Paper Distill"

        research_paths = write_research_notes(topics_data, date, base_dir, project_root)
        results["research_notes"] = str(len(research_paths))

        log_path = write_topic_learning_log(topics_data, date, base_dir)
        results["learning_log"] = str(log_path)

    return results


# ── CLI ────────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate all daily digest output files."
    )
    parser.add_argument(
        "--papers", required=True,
        help="Path to final selected papers JSON (data/tmp_selected.json)",
    )
    parser.add_argument(
        "--date", required=True,
        help="Date string (YYYY-MM-DD) for the digest",
    )
    parser.add_argument(
        "--topics",
        help="Path to topics JSON (from user's research md document)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path)

    args = parse_args(argv)
    project_root = Path(__file__).resolve().parent.parent

    papers_path = Path(args.papers)
    if not papers_path.is_absolute():
        papers_path = project_root / papers_path

    if not papers_path.exists():
        logger.error("Papers file not found: %s", papers_path)
        sys.exit(1)

    papers = json.loads(papers_path.read_text(encoding="utf-8"))

    if not papers:
        logger.warning("No papers in input file. Nothing to generate.")
        sys.exit(0)

    # Load topics data if provided
    topics_data = None
    if args.topics:
        topics_path = Path(args.topics)
        if not topics_path.is_absolute():
            topics_path = project_root / topics_path
        if topics_path.exists():
            topics_data = json.loads(topics_path.read_text(encoding="utf-8"))
            logger.info("Loaded topics data with %d topics", len(topics_data.get("topics", [])))

    logger.info("Generating daily digest for %s with %d papers", args.date, len(papers))

    results = generate_all(papers, args.date, project_root, topics_data=topics_data)

    # Print summary
    logger.info("=== Daily Digest Generation Complete ===")
    for key, value in results.items():
        logger.info("  %s: %s", key, value)


if __name__ == "__main__":
    main()
