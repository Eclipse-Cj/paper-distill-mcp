"""
Generate Obsidian-compatible markdown notes for papers and research.

Three output types:
  1. 论文阅读卡片：精简卡片，只存链接 + IF + 要点概括
  2. 学习日志：主题编号 + [[研究笔记/area/topic]] 跳转
  3. 研究笔记：按知识点组织，同主题追加不覆盖

CLI usage:
  # Paper notes (from push pipeline)
  python generate/obsidian_note.py \
    --papers data/tmp_selected.json --date 2026-02-25

  # Research notes + learning log (from user's md document)
  python generate/obsidian_note.py \
    --mode research --topics data/tmp_topics.json --date 2026-02-25
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

try:
    from generate.validation import ensure_within, safe_filename, safe_relative_dir, validate_date
except ModuleNotFoundError:  # run as a script: python generate/obsidian_note.py
    from validation import ensure_within, safe_filename, safe_relative_dir, validate_date

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("paper-distill.obsidian")


# ── helpers ────────────────────────────────────────────────────────────────

def generate_citekey(paper: dict) -> str:
    """Generate citekey: author2025_keyword"""
    authors = paper.get("authors", "")
    if isinstance(authors, list):
        first = authors[0] if authors else "unknown"
    else:
        first = authors.split(",")[0].strip() if authors else "unknown"

    if "," in first:
        last_name = first.split(",")[0].strip()
    else:
        parts = first.strip().split()
        last_name = parts[-1] if parts else "unknown"

    last_name = re.sub(r"[^a-zA-Z]", "", last_name).lower() or "unknown"

    year = paper.get("year", "")
    if not year:
        date_str = paper.get("published_date") or paper.get("date") or ""
        year = date_str[:4] if date_str else "0000"

    title = paper.get("title", "")
    stop_words = {
        "a", "an", "the", "of", "in", "on", "for", "and", "or", "with",
        "to", "by", "is", "at", "from", "its", "as", "are", "was", "were",
        "using", "via", "based", "through", "between", "into", "that",
        "this", "their", "new", "novel",
    }
    words = re.findall(r"[a-z]+", title.lower())
    keyword = "paper"
    for w in words:
        if w not in stop_words and len(w) >= 3:
            keyword = w
            break

    return f"{last_name}{year}_{keyword}"


def format_authors_short(paper: dict) -> str:
    """Format authors as 'Author et al.' or 'Author & Author'."""
    authors = paper.get("authors", "")
    if isinstance(authors, list):
        author_list = authors
    else:
        if ";" in authors:
            author_list = [a.strip() for a in authors.split(";")]
        elif "," in authors:
            parts = [a.strip() for a in authors.split(",")]
            author_list = parts if len(parts) > 2 else [authors]
        else:
            author_list = [authors] if authors else ["Unknown"]

    if len(author_list) == 0:
        return "Unknown"
    if len(author_list) == 1:
        return author_list[0]
    if len(author_list) == 2:
        return f"{author_list[0]} & {author_list[1]}"

    first = author_list[0].strip()
    if "," in first:
        name = first.split(",")[0].strip()
    else:
        parts = first.split()
        name = parts[-1] if parts else first
    return f"{name} et al."


def _escape_yaml(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _prev_date(date_str: str) -> str:
    from datetime import datetime, timedelta
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return (d - timedelta(days=1)).strftime("%Y-%m-%d")


def _next_date(date_str: str) -> str:
    from datetime import datetime, timedelta
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return (d + timedelta(days=1)).strftime("%Y-%m-%d")


def _safe_filename(name: str) -> str:
    """Sanitize a string for use as a filename (keep Chinese chars)."""
    # Remove characters illegal in filenames
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()


# ── 论文阅读卡片（精简版）──────────────────────────────────────────────

def render_paper_note(paper: dict, date: str) -> str:
    """
    论文阅读卡片：完整的阅读笔记，包含背景、方法、结果、启发。
    数据不全时优雅降级，不输出空节。
    """
    citekey = paper.get("citekey") or generate_citekey(paper)
    title = paper.get("title", "Untitled")
    authors_short = format_authors_short(paper)
    year = paper.get("year", "")
    doi = paper.get("doi", "")
    journal = paper.get("journal", "")
    jcr_quartile = paper.get("jcr_quartile", "")
    cas_zone = paper.get("cas_zone", "")
    impact_factor = paper.get("impact_factor", "")
    topic_tags = paper.get("topic_tags", [])

    if not year:
        date_str = paper.get("published_date") or paper.get("date") or ""
        year = date_str[:4] if date_str else ""

    authors_raw = paper.get("authors", "")
    if isinstance(authors_raw, list):
        authors_raw = [a for a in authors_raw if a and a != "Unknown"]
    authors_fm = "; ".join(authors_raw) if isinstance(authors_raw, list) else authors_raw

    # Obsidian tags: #tag format for body
    tag_str = " ".join(f"#{t}" for t in topic_tags) if topic_tags else ""
    topics_yaml = json.dumps(topic_tags, ensure_ascii=False)

    # ── frontmatter ──
    lines = [
        "---",
        f"citekey: {citekey}",
        f'title: "{_escape_yaml(title)}"',
    ]
    if authors_fm:
        lines.append(f'authors: "{_escape_yaml(authors_fm)}"')
    lines += [
        f"year: {year}",
        f'doi: "{doi}"',
        f'journal: "{_escape_yaml(journal)}"',
    ]
    if jcr_quartile:
        lines.append(f'jcr_quartile: "{jcr_quartile}"')
    if cas_zone:
        lines.append(f'cas_zone: "{cas_zone}"')
    if impact_factor:
        lines.append(f"impact_factor: {impact_factor}")
    lines += [
        f"topics: {topics_yaml}",
        f"date_added: {date}",
        "---",
        "",
    ]

    # ── title + meta ──
    lines.append(f"# {title}")
    lines.append("")

    # Meta line: author (year) | journal | Q1 一区 | IF 7.6
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
        lines.append(" | ".join(meta_parts))
        lines.append("")

    # Links
    link_parts = []
    if doi:
        link_parts.append(f"[DOI](https://doi.org/{doi})")
    link_parts.append(f"[Zotero](zotero://select/items/@{citekey})")
    lines.append(" | ".join(link_parts))
    if tag_str:
        lines.append(tag_str)
    lines.append("")

    # ── 一句话总结 ──
    tldr = paper.get("tldr", "") or paper.get("one_liner", "")
    if tldr:
        lines.append(f"> [!tldr] {tldr}")
        lines.append("")

    # ── 背景与动机 ──
    bg = paper.get("background", "")
    if bg:
        lines.append("## 背景")
        lines.append("")
        lines.append(bg)
        lines.append("")

    # ── 方法 ──
    method = paper.get("method", "") or paper.get("methods", "")
    if method:
        lines.append("## 方法")
        lines.append("")
        lines.append(method)
        lines.append("")

    # ── 结果 ──
    results = paper.get("results", "")
    if results:
        lines.append("## 结果")
        lines.append("")
        lines.append(results)
        lines.append("")

    # ── 创新点 ──
    innovation = paper.get("innovation", "")
    if innovation:
        lines.append("## 创新点")
        lines.append("")
        lines.append(innovation)
        lines.append("")

    # ── 对我的启发 ──
    inspiration = paper.get("inspiration", "") or paper.get("relevance_note", "")
    if inspiration:
        lines.append("## 启发")
        lines.append("")
        lines.append(inspiration)
        lines.append("")

    return "\n".join(lines)


# ── 学习日志（主题编号 + [[研究笔记]] 跳转）───────────────────────────

def render_topic_learning_log(topics_data: dict, date: str) -> str:
    """
    学习日志：主打跳转。编号列表 + [[研究笔记]] 双链 + #标签。
    不放论文引用（论文在研究笔记里）。
    """
    topics = topics_data.get("topics", [])

    lines = [
        "---",
        f"date: {date}",
        "type: learning-log",
        "---",
        "",
        f"# {date} 学习日志",
        "",
    ]

    for i, topic in enumerate(topics, 1):
        title = topic.get("title", "")
        area = topic.get("area", "")
        tags = topic.get("tags", [])
        sub_points = topic.get("sub_points", [])

        # 主条目：编号 + [[研究笔记/area/title|display]] #tags
        safe_title = _safe_filename(title)
        tag_str = " ".join(f"#{t}" for t in tags) if tags else ""
        lines.append(
            f"{i}. [[研究笔记/{area}/{safe_title}|{title}]] {tag_str}"
        )

        # 子要点（如有必要才展开）
        for sp in sub_points:
            lines.append(f"   - {sp}")

    lines.append("")
    lines.append("---")
    lines.append(
        f"← [[学习日志/{_prev_date(date)}|{_prev_date(date)}]] | "
        f"[[学习日志/{_next_date(date)}|{_next_date(date)}]] →"
    )

    return "\n".join(lines)


# ── 研究笔记（知识点，追加模式）──────────────────────────────────────

def _render_new_research_note(topic: dict, date: str, zotero_dois: set[str] | None = None) -> str:
    """Create a brand new research note for a topic."""
    title = topic.get("title", "")
    area = topic.get("area", "")
    tags = topic.get("tags", [])
    tags_yaml = json.dumps(tags, ensure_ascii=False)

    lines = [
        "---",
        f"area: {area}",
        f"tags: {tags_yaml}",
        f"created: {date}",
        f"updated: {date}",
        "---",
        "",
        f"# {title}",
        "",
    ]

    lines.extend(_render_date_section(topic, date, zotero_dois))

    return "\n".join(lines)


def _render_date_section(topic: dict, date: str, zotero_dois: set[str] | None = None) -> list[str]:
    """Render a single date section for a research note.

    zotero_dois: set of lowercase DOIs that exist in Zotero library.
    If a paper's DOI is in this set, use zotero:// link.
    Otherwise, use online DOI link + (未入库) label.
    """
    summary = topic.get("summary", "")
    sub_points = topic.get("sub_points", [])
    papers = topic.get("papers", [])
    zotero_dois = zotero_dois or set()

    lines = [f"## {date}", ""]

    if summary:
        lines.append(summary)
        lines.append("")

    for sp in sub_points:
        lines.append(f"- {sp}")
    if sub_points:
        lines.append("")

    if papers:
        lines.append("### 相关论文")
        for paper in papers:
            citekey = paper.get("citekey") or generate_citekey(paper)
            paper["citekey"] = citekey
            title = paper.get("title", citekey)
            authors = paper.get("authors", "")
            year = paper.get("year", "")
            journal = paper.get("journal", "")
            impact_factor = paper.get("impact_factor", "")
            jcr_quartile = paper.get("jcr_quartile", "")
            doi = paper.get("doi", "")
            paper_summary = paper.get("summary", "")

            # Author display — handle "Smith et al.", "Smith, J.", ["First Last", ...]
            display_author = ""
            if isinstance(authors, list):
                authors = [a for a in authors if a and a != "Unknown"]
                if authors:
                    first = authors[0].strip()
                    # Remove "et al." suffix if present
                    first = first.replace(" et al.", "").replace(" et al", "").strip()
                    parts = first.split()
                    display_author = parts[-1] if parts else ""
            elif authors and authors != "Unknown":
                first = authors.split(";")[0].split(",")[0].strip()
                first = first.replace(" et al.", "").replace(" et al", "").strip()
                parts = first.split()
                display_author = parts[-1] if parts else ""

            if display_author and year:
                display_name = f"{display_author} et al. ({year})"
            elif year:
                display_name = f"({year})"
            else:
                display_name = title[:40]

            # Meta: journal + quartile + IF
            meta_parts = []
            if journal:
                meta_parts.append(f"*{journal}*")
            if jcr_quartile:
                meta_parts.append(jcr_quartile)
            if impact_factor:
                meta_parts.append(f"IF {impact_factor}")
            meta_str = " ".join(meta_parts)

            # Zotero link vs DOI link
            doi_lower = doi.lower() if doi else ""
            if doi_lower and doi_lower in zotero_dois:
                # Paper in Zotero → [[论文阅读/citekey]] + zotero:// link
                link = f"[Zotero](zotero://select/items/@{citekey})"
                lines.append(f"- [[论文阅读/{citekey}|{display_name}]] {meta_str} {link}")
            elif doi:
                # Not in Zotero → DOI link + (未入库)
                link = f"[DOI](https://doi.org/{doi})"
                lines.append(f"- {display_name} {meta_str} {link} (未入库)")
            else:
                # No DOI at all
                lines.append(f"- {display_name} {meta_str}")

            if paper_summary:
                lines.append(f"  {paper_summary}")
        lines.append("")

    return lines


def _fetch_zotero_dois(project_root: Path) -> set[str]:
    """Fetch all DOIs from Zotero library. Returns lowercase DOI set."""
    try:
        import os
        from dotenv import load_dotenv
        load_dotenv(project_root / ".env")

        library_id = os.getenv("ZOTERO_LIBRARY_ID", "")
        api_key = os.getenv("ZOTERO_API_KEY", "")
        if not library_id or not api_key:
            return set()

        from pyzotero import zotero as pyzotero_mod
        zot = pyzotero_mod.Zotero(library_id, "user", api_key)
        items = zot.everything(zot.items(itemType="journalArticle"))

        dois = set()
        for item in items:
            doi = item.get("data", {}).get("DOI", "").strip().lower()
            if doi:
                dois.add(doi)
        logger.info("Fetched %d DOIs from Zotero", len(dois))
        return dois
    except Exception as e:
        logger.warning("Failed to fetch Zotero DOIs: %s", e)
        return set()


def _append_to_research_note(existing_content: str, topic: dict, date: str, zotero_dois: set[str] | None = None) -> str:
    """Append a new date section to an existing research note."""
    # Update the 'updated' field in frontmatter
    updated_content = re.sub(
        r"^(updated: ).+$",
        f"\\g<1>{date}",
        existing_content,
        count=1,
        flags=re.MULTILINE,
    )

    # Merge new tags into existing tags
    existing_tags_match = re.search(r'^tags: (.+)$', updated_content, re.MULTILINE)
    if existing_tags_match:
        try:
            existing_tags = json.loads(existing_tags_match.group(1))
        except json.JSONDecodeError:
            existing_tags = []
        new_tags = topic.get("tags", [])
        merged = list(dict.fromkeys(existing_tags + new_tags))  # dedupe, preserve order
        updated_content = updated_content.replace(
            existing_tags_match.group(0),
            f"tags: {json.dumps(merged, ensure_ascii=False)}",
        )

    # Append new date section
    new_section = "\n".join(_render_date_section(topic, date, zotero_dois))
    return updated_content.rstrip() + "\n\n---\n\n" + new_section


# ── 写入文件 ──────────────────────────────────────────────────────────

def write_paper_notes(
    papers: list[dict],
    date: str,
    output_dir: Path,
) -> list[Path]:
    """Write individual paper notes and return paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    for paper in papers:
        citekey = paper.get("citekey") or generate_citekey(paper)
        paper["citekey"] = citekey

        filename = safe_filename(citekey, default="untitled")
        filepath = ensure_within(output_dir, output_dir / f"{filename}.md")
        content = render_paper_note(paper, date)
        filepath.write_text(content, encoding="utf-8")
        paths.append(filepath)
        logger.info("Wrote paper note: %s", filepath)

    return paths


def write_research_notes(
    topics_data: dict,
    date: str,
    base_dir: Path,
    project_root: Path | None = None,
) -> list[Path]:
    """
    Write or append research notes for each topic.
    Auto-creates area directories as needed.
    Queries Zotero to determine link format for paper references.
    Returns list of written/updated file paths.
    """
    topics = topics_data.get("topics", [])
    paths: list[Path] = []

    # Fetch Zotero DOIs for link checking
    zotero_dois: set[str] = set()
    if project_root:
        zotero_dois = _fetch_zotero_dois(project_root)

    for topic in topics:
        # "area" and "title" come from the caller, so neither may leave the notes folder.
        area_dir = safe_relative_dir(topic.get("area"), default="other")
        safe_title = safe_filename(topic.get("title"), default="untitled")

        notes_root = base_dir / "研究笔记"
        note_dir = ensure_within(notes_root, notes_root / area_dir)
        note_dir.mkdir(parents=True, exist_ok=True)

        filepath = ensure_within(notes_root, note_dir / f"{safe_title}.md")

        if filepath.exists():
            existing = filepath.read_text(encoding="utf-8")
            # Check if this date section already exists
            if f"## {date}" in existing:
                logger.info("Date section already exists, skipping: %s", filepath)
                paths.append(filepath)
                continue
            content = _append_to_research_note(existing, topic, date, zotero_dois)
            logger.info("Appended to research note: %s", filepath)
        else:
            content = _render_new_research_note(topic, date, zotero_dois)
            logger.info("Created new research note: %s", filepath)

        filepath.write_text(content, encoding="utf-8")
        paths.append(filepath)

    return paths


def write_topic_learning_log(
    topics_data: dict,
    date: str,
    base_dir: Path,
) -> Path:
    """Write the topic-based daily learning log."""
    date = validate_date(date)
    log_dir = base_dir / "学习日志"
    log_dir.mkdir(parents=True, exist_ok=True)

    content = render_topic_learning_log(topics_data, date)
    filepath = ensure_within(log_dir, log_dir / f"{date}.md")
    filepath.write_text(content, encoding="utf-8")
    logger.info("Wrote learning log: %s", filepath)
    return filepath


# ── CLI ────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Obsidian notes.")
    parser.add_argument("--mode", choices=["papers", "research"], default="papers",
                        help="'papers' for push pipeline, 'research' for user's md doc")
    parser.add_argument("--papers", help="Path to selected papers JSON (mode=papers)")
    parser.add_argument("--topics", help="Path to topics JSON (mode=research)")
    parser.add_argument("--date", required=True, help="Date string (YYYY-MM-DD)")
    parser.add_argument("--output-dir", help="Override output base directory")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path)

    args = parse_args(argv)
    project_root = Path(__file__).resolve().parent.parent
    base_dir = (
        Path(args.output_dir)
        if args.output_dir
        else project_root / "obsidian" / "Paper Distill"
    )

    if args.mode == "research":
        if not args.topics:
            logger.error("--topics is required for mode=research")
            sys.exit(1)

        topics_path = Path(args.topics)
        if not topics_path.is_absolute():
            topics_path = project_root / topics_path

        if not topics_path.exists():
            logger.error("Topics file not found: %s", topics_path)
            sys.exit(1)

        topics_data = json.loads(topics_path.read_text(encoding="utf-8"))

        # 1. Write/append research notes
        research_paths = write_research_notes(
            topics_data, args.date, base_dir, project_root,
        )
        logger.info("Wrote %d research notes", len(research_paths))

        # 2. Write learning log
        log_path = write_topic_learning_log(topics_data, args.date, base_dir)
        logger.info("Wrote learning log: %s", log_path)

    else:
        # Default: paper notes from push pipeline
        if not args.papers:
            logger.error("--papers is required for mode=papers")
            sys.exit(1)

        papers_path = Path(args.papers)
        if not papers_path.is_absolute():
            papers_path = project_root / papers_path

        if not papers_path.exists():
            logger.error("Papers file not found: %s", papers_path)
            sys.exit(1)

        papers = json.loads(papers_path.read_text(encoding="utf-8"))
        output_dir = base_dir / "论文阅读"
        paths = write_paper_notes(papers, args.date, output_dir)
        logger.info("Generated %d Obsidian paper notes", len(paths))


if __name__ == "__main__":
    main()
