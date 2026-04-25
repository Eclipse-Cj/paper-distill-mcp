"""
Local Library integration for Paper Distill.

Features:
  - Save papers to local file system (PDF + Markdown notes)
  - No external API keys required
  - Compatible with Obsidian/Logseq (Markdown format)

Usage:
  - Set `PAPER_DISTILL_DATA_DIR` or use default `~/.paper-distill/`
  - PDFs saved to: `<DATA_DIR>/pdfs/`
  - Notes saved to: `<DATA_DIR>/library/`
"""
from __future__ import annotations

import logging
import os
import re
import json
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

logger = logging.getLogger("paper-distill.local")

# Regex for cleaning filenames
SAFE_FILENAME_REGEX = re.compile(r'[\\/*?:"<>|]')


def sanitize_filename(filename: str) -> str:
    """Remove illegal characters from filename."""
    name = SAFE_FILENAME_REGEX.sub("", filename)
    return name.strip()[:100]  # Limit length


def _get_data_dir() -> Path:
    """Get the data directory."""
    return Path(os.getenv("PAPER_DISTILL_DATA_DIR", Path.home() / ".paper-distill"))


async def download_pdf(url: str, save_path: Path) -> bool:
    """Download a PDF from a URL."""
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(resp.content)
            logger.info("Downloaded PDF to %s", save_path)
            return True
    except Exception as e:
        logger.warning("Failed to download PDF %s: %s", url, e)
        return False


def generate_markdown_note(paper: dict[str, Any], pdf_filename: str | None = None) -> str:
    """Generate a Markdown note for a paper."""
    title = paper.get("title", "Untitled")
    authors = ", ".join(paper.get("authors", [])[:3])
    if len(paper.get("authors", [])) > 3:
        authors += " et al."
    abstract = paper.get("abstract", "No abstract available.")
    doi = paper.get("doi", "")
    url = paper.get("open_access_url", "")
    source = paper.get("source", "Unknown")
    year = paper.get("year", "Unknown")

    pdf_link = f"![PDF]({pdf_filename})" if pdf_filename else ""
    doi_link = f"[DOI](https://doi.org/{doi})" if doi else ""
    oa_link = f"[Open Access]({url})" if url and not url.endswith(".pdf") else ""

    note = f"""# {title}

> **Authors:** {authors}  
> **Year:** {year} | **Source:** {source}  
> **Links:** {doi_link} {oa_link}

---

## Abstract
{abstract}

---

## Notes
_Add your notes here..._

{pdf_link}
"""
    return note


async def save_papers_locally(papers: list[dict[str, Any]]) -> list[dict[str, str]]:
    """
    Save papers locally: download PDF (if available) and create Markdown notes.
    
    Returns a list of status messages for each paper.
    """
    data_dir = _get_data_dir()
    pdf_dir = data_dir / "pdfs"
    library_dir = data_dir / "library"
    library_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    results = []

    for paper in papers:
        title = paper.get("title", "untitled")
        doi = paper.get("doi", "")
        
        # Generate safe filenames
        safe_title = sanitize_filename(title)
        safe_name = safe_title if safe_title else sanitize_filename(doi)
        
        pdf_path = pdf_dir / f"{safe_name}.pdf"
        md_path = library_dir / f"{safe_name}.md"
        
        status = {"title": title, "doi": doi, "pdf_saved": False, "note_saved": False, "path": str(md_path)}

        # 1. Try to download PDF
        pdf_url = paper.get("open_access_url", "")
        if pdf_url and not pdf_path.exists():
            success = await download_pdf(pdf_url, pdf_path)
            if success:
                status["pdf_saved"] = True
                status["pdf_path"] = str(pdf_path)
        elif pdf_path.exists():
            status["pdf_saved"] = True
            status["pdf_path"] = str(pdf_path)

        # 2. Save Markdown Note
        if not md_path.exists():
            md_content = generate_markdown_note(paper, pdf_filename=f"../pdfs/{safe_name}.pdf" if status["pdf_saved"] else None)
            md_path.write_text(md_content, encoding="utf-8")
            status["note_saved"] = True
            logger.info("Created note: %s", md_path)
        else:
            logger.info("Note already exists: %s", md_path)

        # 3. Update Master Library Index
        index_path = data_dir / "local_library.jsonl"
        with open(index_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "title": title,
                "doi": doi,
                "pdf": status.get("pdf_path", ""),
                "note": str(md_path),
                "date_added": paper.get("date", ""),
            }, ensure_ascii=False) + "\n")
        
        results.append(status)

    return results
