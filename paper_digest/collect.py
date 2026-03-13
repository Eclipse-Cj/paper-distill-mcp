"""Collect flow for Zotero + optional Obsidian.

Handles the post-push user interaction:
  1. User says "collect 1 3"
  2. Papers get added to Zotero
  3. Optionally create Obsidian notes with Zotero backlinks
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

LOG = logging.getLogger("paper_digest.collect")


def resolve_papers_by_index(
    indices: list[int],
    data_dir: Path,
) -> list[dict]:
    """Look up papers from the latest push by 1-based index.

    Reads the most recent push from pushes.jsonl, then resolves
    papers from papers.jsonl.
    """
    pushes_path = data_dir / "pushes.jsonl"
    papers_path = data_dir / "papers.jsonl"

    if not pushes_path.exists() or not papers_path.exists():
        LOG.warning("Missing pushes.jsonl or papers.jsonl")
        return []

    # Get latest push
    pushes = pushes_path.read_text(encoding="utf-8").strip().splitlines()
    if not pushes:
        return []
    latest_push = json.loads(pushes[-1])
    paper_ids = latest_push.get("paper_ids", [])

    # Build lookup from papers.jsonl
    lookup: dict[str, dict] = {}
    for line in papers_path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        paper = json.loads(line)
        pid = paper.get("id") or paper.get("doi") or ""
        if pid:
            lookup[pid] = paper
            lookup[pid.lower()] = paper

    # Resolve by index
    resolved = []
    for idx in indices:
        if 1 <= idx <= len(paper_ids):
            pid = paper_ids[idx - 1]
            paper = lookup.get(pid) or lookup.get(pid.lower())
            if paper:
                resolved.append(paper)
            else:
                LOG.warning("Paper not found in history: %s", pid)
        else:
            LOG.warning("Index %d out of range (1-%d)", idx, len(paper_ids))

    return resolved


def collect_to_zotero(
    papers: list[dict],
    project_root: Path,
) -> list[dict]:
    """Add papers to Zotero with PDF attachment. Returns list of created items."""
    import asyncio
    import sys
    sys.path.insert(0, str(project_root))

    # Enrich OA links via Unpaywall before sending to Zotero
    try:
        from search.unpaywall_lookup import enrich_open_access
        papers = asyncio.run(enrich_open_access(papers))
    except Exception:
        pass

    try:
        from integrations.zotero_api import add_papers_to_zotero_by_data_sync
        return add_papers_to_zotero_by_data_sync(project_root, papers)
    except ImportError:
        LOG.warning("Zotero integration not available (pyzotero not installed)")
        return []
    except Exception as e:
        LOG.error("Zotero error: %s", e)
        return []


def prepare_obsidian_note_summary(paper: dict) -> str:
    """Generate Obsidian note with Zotero backlink and AI-generated summary."""
    citekey = paper.get("citekey", "")
    title = paper.get("title", "Untitled")
    doi = paper.get("doi", "")
    journal = paper.get("journal", "")
    year = paper.get("year", "")
    authors = paper.get("authors", [])
    if isinstance(authors, list):
        authors_str = "; ".join(authors)
    else:
        authors_str = str(authors)

    summary = paper.get("summary", {}) or {}

    lines = [
        "---",
        f"citekey: {citekey}",
        f'title: "{title}"',
        f'authors: "{authors_str}"',
        f"year: {year}",
        f'doi: "{doi}"',
        f'journal: "{journal}"',
        f"date_added: {paper.get('push_date', '')}",
        "---",
        "",
        f"# {title}",
        "",
    ]

    # Links
    link_parts = []
    if doi:
        link_parts.append(f"[DOI](https://doi.org/{doi})")
    if citekey:
        link_parts.append(f"[Zotero](zotero://select/items/@{citekey})")
    if link_parts:
        lines.append(" | ".join(link_parts))
        lines.append("")

    # TLDR
    tldr = paper.get("tldr", "")
    if tldr:
        lines.append(f"> [!tldr] {tldr}")
        lines.append("")

    # Structured summary from scraper
    if summary:
        field_labels = {
            "general": "Summary",
            "model_algorithm": "Model/Algorithm",
            "input_data": "Input Data",
            "output_prediction": "Output/Prediction",
            "problem_domain": "Problem Domain",
            "pain_point": "Pain Point Addressed",
            "key_results": "Key Results",
        }
        for field, label in field_labels.items():
            value = summary.get(field, "")
            if value:
                lines.append(f"## {label}")
                lines.append("")
                lines.append(value)
                lines.append("")

    return "\n".join(lines)


def prepare_obsidian_note_template(paper: dict) -> str:
    """Generate Obsidian note template with Zotero backlink and empty sections for user notes."""
    citekey = paper.get("citekey", "")
    title = paper.get("title", "Untitled")
    doi = paper.get("doi", "")
    journal = paper.get("journal", "")
    year = paper.get("year", "")

    lines = [
        "---",
        f"citekey: {citekey}",
        f'title: "{title}"',
        f"year: {year}",
        f'doi: "{doi}"',
        f'journal: "{journal}"',
        f"date_added: {paper.get('push_date', '')}",
        "---",
        "",
        f"# {title}",
        "",
    ]

    link_parts = []
    if doi:
        link_parts.append(f"[DOI](https://doi.org/{doi})")
    if citekey:
        link_parts.append(f"[Zotero](zotero://select/items/@{citekey})")
    if link_parts:
        lines.append(" | ".join(link_parts))
        lines.append("")

    tldr = paper.get("tldr", "")
    if tldr:
        lines.append(f"> [!tldr] {tldr}")
        lines.append("")

    lines.extend([
        "## My Notes",
        "",
        "_Write your thoughts, key takeaways, and connections to your research here._",
        "",
        "## Key Insights",
        "",
        "- ",
        "",
        "## Connections",
        "",
        "_How does this relate to your other work?_",
        "",
    ])

    return "\n".join(lines)


def collect_interactive_prompt(papers_pushed: list[dict]) -> str:
    """Generate the interactive collect prompt for the agent to send."""
    if not papers_pushed:
        return ""

    lines = [
        "Added to Zotero! Want to link to Obsidian too?",
        "",
    ]

    for i, p in enumerate(papers_pushed, 1):
        title = p.get("title", "")[:60]
        lines.append(f"  {i}. {title}")

    lines.extend([
        "",
        "Options:",
        "  1) Create note with article summary for your records",
        "  2) I want to add my own notes - create a template",
        "  3) No thanks",
    ])

    return "\n".join(lines)
