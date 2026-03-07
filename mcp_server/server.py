"""Paper Distill MCP Server.

Exposes paper search, curation, and push tools via MCP protocol.
No LLM calls — all intelligence is delegated to the calling AI client.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastmcp import FastMCP

from mcp_server.config import load_config

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("paper-distill-mcp")

mcp = FastMCP("paper-distill")


# ── helpers ────────────────────────────────────────────────────────────────

def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def _get_root() -> Path:
    cfg = load_config()
    return cfg.project_root


def _ensure_sys_path():
    """Ensure project root is on sys.path for imports."""
    root = str(_get_root())
    if root not in sys.path:
        sys.path.insert(0, root)


# ── MCP Tools ──────────────────────────────────────────────────────────────

@mcp.tool()
async def search_papers(query: str, max_results: int = 10) -> list[dict]:
    """Search academic papers across 9 sources (OpenAlex, Semantic Scholar, PubMed, arXiv, Papers with Code, CrossRef, Europe PMC, bioRxiv, DBLP).

    Returns deduplicated, merged results sorted by cross-source hits + citation count.
    Each paper has: title, year, doi, authors, abstract, source, citation_count, etc.

    Args:
        query: Search query string (e.g. "LLM reasoning chain-of-thought")
        max_results: Maximum number of results to return (default 10)
    """
    _ensure_sys_path()
    from search.query_all import search_all

    results = await search_all(query, top=max_results)
    return results


@mcp.tool()
def rank_papers(papers: list[dict], top_n: int = 10) -> list[dict]:
    """Score and rank papers using 4-factor weighted formula.

    Factors: relevance (0.55), recency (0.20), impact (0.15), novelty (0.10).
    Uses topic_prefs.json for relevance scoring and papers.jsonl for novelty detection.

    Args:
        papers: List of paper dicts (from search_papers)
        top_n: Return top N papers after ranking
    """
    _ensure_sys_path()
    from curate.ranker import rank_papers as _rank

    root = _get_root()
    prefs_path = root / "data" / "topic_prefs.json"
    history_path = root / "data" / "papers.jsonl"

    prefs = json.loads(prefs_path.read_text(encoding="utf-8")) if prefs_path.exists() else {"topics": {}}
    history = _load_jsonl(history_path)

    # Load user-configured ranking weights
    pcfg_path = root / "config" / "pipeline_config.json"
    pcfg = json.loads(pcfg_path.read_text(encoding="utf-8")) if pcfg_path.exists() else {}
    weights = pcfg.get("ranking_weights", {})

    ranked = _rank(
        papers, prefs, history,
        w_relevance=weights.get("relevance", 0.55),
        w_recency=weights.get("recency", 0.20),
        w_impact=weights.get("impact", 0.15),
        w_novelty=weights.get("novelty", 0.10),
    )
    return ranked[:top_n]


@mcp.tool()
def filter_duplicates(papers: list[dict]) -> list[dict]:
    """Remove papers already pushed (by DOI match against papers.jsonl).

    Args:
        papers: List of paper dicts to filter
    """
    _ensure_sys_path()
    from curate.filter import filter_papers

    root = _get_root()
    history = _load_jsonl(root / "data" / "papers.jsonl")
    history_dois = {h.get("doi", "").lower() for h in history if h.get("doi")}

    return filter_papers(papers, history_dois)


@mcp.tool()
def generate_digest(papers: list[dict], date: str, topics: dict | None = None) -> dict[str, str]:
    """Generate all daily output files (pushes.jsonl, papers.jsonl, Astro site JSON, Obsidian notes).

    Args:
        papers: Final selected papers with annotations
        date: Date string in YYYY-MM-DD format
        topics: Optional topics data for research note generation
    """
    _ensure_sys_path()
    from generate.daily_digest import generate_all

    root = _get_root()
    return generate_all(papers, date, root, topics_data=topics)


@mcp.tool()
async def send_push(date: str, papers: list[dict], platform: str = "telegram") -> str:
    """Format and send daily paper distill to a messaging platform.

    Supported platforms: telegram, discord, feishu (飞书/Lark), wecom (企业微信 webhook).

    Args:
        date: Date string in YYYY-MM-DD format
        papers: Papers to include in the push message
        platform: Target platform - "telegram", "discord", "feishu", or "wecom" (default: telegram)
    """
    _ensure_sys_path()
    from bot.notifier import format_daily_push

    cfg = load_config()
    message = format_daily_push(date, papers, cfg.site_url)

    if platform == "telegram":
        from bot.notifier import send_push as _tg_send
        token = cfg.telegram_bot_token
        chat_id = cfg.telegram_chat_id
        if not token or not chat_id:
            return "Error: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured"
        await _tg_send(token, chat_id, message)
        return f"Telegram push sent: {len(papers)} papers for {date}"

    elif platform == "discord":
        webhook_url = cfg.discord_webhook_url
        if not webhook_url:
            return "Error: DISCORD_WEBHOOK_URL not configured"
        return await _send_discord(webhook_url, date, papers, message)

    elif platform == "feishu":
        webhook_url = cfg.feishu_webhook_url
        if not webhook_url:
            return "Error: FEISHU_WEBHOOK_URL not configured"
        return await _send_feishu(webhook_url, date, papers, message)

    elif platform == "wecom":
        webhook_url = cfg.wecom_webhook_url
        if not webhook_url:
            return "Error: WECOM_WEBHOOK_URL not configured"
        return await _send_wecom(webhook_url, date, papers, message)

    else:
        return f"Error: Unknown platform '{platform}'. Use: telegram, discord, feishu, wecom"


async def _send_feishu(webhook_url: str, date: str, papers: list[dict], message: str) -> str:
    """Send push via Feishu (Lark) webhook."""
    import httpx

    # Feishu rich text card
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"📬 论文推送 {date} | {len(papers)} 篇"},
                "template": "blue",
            },
            "elements": [
                {"tag": "markdown", "content": message},
            ],
        },
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(webhook_url, json=payload, timeout=30)
        resp.raise_for_status()

    return f"Feishu push sent: {len(papers)} papers for {date}"


async def _send_wecom(webhook_url: str, date: str, papers: list[dict], message: str) -> str:
    """Send push via WeCom (企业微信) webhook."""
    import httpx

    # WeCom markdown message (max 4096 chars)
    if len(message) > 4096:
        message = message[:4090] + "\n..."

    payload = {
        "msgtype": "markdown",
        "markdown": {"content": message},
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(webhook_url, json=payload, timeout=30)
        resp.raise_for_status()

    return f"WeCom push sent: {len(papers)} papers for {date}"


async def _send_discord(webhook_url: str, date: str, papers: list[dict], message: str) -> str:
    """Send push via Discord webhook."""
    import httpx

    # Discord embed (max 4096 chars per embed description)
    if len(message) > 4096:
        message = message[:4090] + "\n..."

    payload = {
        "embeds": [{
            "title": f"📬 论文推送 {date} | {len(papers)} 篇",
            "description": message,
            "color": 3447003,  # blue
        }],
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(webhook_url, json=payload, timeout=30)
        resp.raise_for_status()

    return f"Discord push sent: {len(papers)} papers for {date}"


@mcp.tool()
async def collect_to_zotero(paper_ids: list[str]) -> list[dict]:
    """Add papers to Zotero library by their IDs/DOIs.

    Looks up papers in papers.jsonl, creates Zotero journal article items
    and maps them to collections based on topic tags.

    Args:
        paper_ids: List of paper DOIs or IDs to add to Zotero
    """
    _ensure_sys_path()
    from integrations.zotero_api import add_papers_to_zotero

    root = _get_root()
    return await add_papers_to_zotero(root, paper_ids)


@mcp.tool()
def manage_topics(action: str, topic: str | None = None, weight: float | None = None) -> dict:
    """Manage research topic preferences.

    Args:
        action: One of "list", "block", "unblock", "set_weight"
        topic: Topic key (required for block/unblock/set_weight, e.g. "llm-news")
        weight: New weight value (only for set_weight action, 0.0-1.0)
    """
    root = _get_root()
    prefs_path = root / "data" / "topic_prefs.json"

    if not prefs_path.exists():
        return {"error": "topic_prefs.json not found"}

    prefs = json.loads(prefs_path.read_text(encoding="utf-8"))

    if action == "list":
        return prefs

    if not topic:
        return {"error": f"topic parameter required for action '{action}'"}

    topics = prefs.get("topics", {})
    if topic not in topics:
        return {"error": f"Unknown topic: {topic}", "available": list(topics.keys())}

    if action == "block":
        topics[topic]["blocked"] = True
    elif action == "unblock":
        topics[topic]["blocked"] = False
    elif action == "set_weight":
        if weight is None:
            return {"error": "weight parameter required for set_weight"}
        topics[topic]["weight"] = max(0.0, min(1.0, weight))
    else:
        return {"error": f"Unknown action: {action}", "valid": ["list", "block", "unblock", "set_weight"]}

    prefs_path.write_text(json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "action": action, "topic": topic, "current": topics[topic]}


@mcp.tool()
async def ingest_research_context(
    markdown_text: str,
    session_id: str | None = None,
    search_now: bool = False,
) -> dict:
    """Ingest research context from other AI conversations for cross-AI context inheritance.

    Extracts keywords from the markdown text and appends to interests.jsonl.
    Use session_id to isolate different chat sessions (prevents context pollution
    when multiple OpenClaw/AI sessions run concurrently).

    Args:
        markdown_text: Markdown text containing research context (e.g. from another AI's summary)
        session_id: Optional session identifier to isolate contexts (e.g. "openclaw-abc123").
                    If provided, only this session's interests are used for search_now.
        search_now: If True, also run a paper search using extracted keywords
    """
    _ensure_sys_path()
    import re

    root = _get_root()
    interests_path = root / "data" / "interests.jsonl"

    # Extract simple keyword set from markdown
    text = re.sub(r'[#*_`\[\]()>]', ' ', markdown_text)
    words = set(re.findall(r'[a-zA-Z]{3,}', text))

    # Build interest record
    record = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "summary": markdown_text[:500],
        "keywords": sorted(words)[:30],
        "source": "mcp_ingest",
        "session_id": session_id or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    interests_path.parent.mkdir(parents=True, exist_ok=True)
    with open(interests_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    result: dict = {"ok": True, "keywords_extracted": len(record["keywords"]), "record": record}

    if search_now and record["keywords"]:
        # Use only this session's keywords if session_id provided
        if session_id:
            session_keywords = _collect_session_keywords(interests_path, session_id)
            query = " ".join(list(session_keywords)[:8])
        else:
            query = " ".join(record["keywords"][:5])
        from search.query_all import search_all
        papers = await search_all(query, top=10)
        result["search_results"] = papers
        result["search_query"] = query

    return result


def _collect_session_keywords(interests_path: Path, session_id: str) -> list[str]:
    """Collect all keywords from a specific session (not other sessions)."""
    all_keywords: set[str] = set()
    for line in interests_path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("session_id") == session_id:
            all_keywords.update(entry.get("keywords", []))
    return sorted(all_keywords)


# ── Session & Channel Management ──────────────────────────────────────────

@mcp.tool()
def init_session(
    session_id: str | None = None,
    platform: str | None = None,
    channel_action: str = "auto",
    load_context: str = "ask",
) -> dict:
    """Initialize a research session. Call this first to set up push channels and load context.

    Detects configured platforms, manages channels, and optionally loads previous
    research context. Returns session info for the AI client to present to the user.

    IMPORTANT for AI clients:
    - If multiple platforms are detected and no `platform` is specified, the response
      will include `ask_platform` — you MUST ask the user which platform to use,
      then call init_session again with `platform=<user_choice>`.
    - If only one platform is configured, it is auto-selected.
    - The `send_push` tool also accepts a `platform` parameter, so the user can
      override per-push even after init.

    Args:
        session_id: Session identifier (auto-generated if not provided).
                    Use different IDs to isolate research vs daily topics.
        platform: Preferred push platform ("telegram", "discord", "feishu", "wecom").
                  If None, auto-detects from configured env vars.
        channel_action: "new" = create dedicated channel, "existing" = use configured
                       channel, "auto" = use existing if available.
        load_context: "yes" = auto-load previous research context,
                     "no" = start fresh, "ask" = return context summary for user to decide.
    """
    import uuid

    root = _get_root()
    cfg = load_config()

    # Generate session ID
    if not session_id:
        session_id = f"session-{uuid.uuid4().hex[:8]}"

    # Detect available platforms
    platforms = {}
    if cfg.telegram_bot_token and cfg.telegram_chat_id:
        platforms["telegram"] = {"status": "ready", "chat_id": cfg.telegram_chat_id}
    if cfg.discord_webhook_url:
        platforms["discord"] = {"status": "ready"}
    if cfg.feishu_webhook_url:
        platforms["feishu"] = {"status": "ready"}
    if cfg.wecom_webhook_url:
        platforms["wecom"] = {"status": "ready"}

    # Select platform
    active_platform = None
    if platform and platform in platforms:
        active_platform = platform
    elif len(platforms) == 1:
        active_platform = next(iter(platforms))
    # If multiple platforms available, don't auto-select — let AI client ask user

    # Check for previous research context
    interests_path = root / "data" / "interests.jsonl"
    context_info = {"has_previous": False, "entries": 0, "topics": []}

    if interests_path.exists():
        entries = _load_jsonl(interests_path)
        if entries:
            context_info["has_previous"] = True
            context_info["entries"] = len(entries)
            # Collect unique topics from keywords
            all_kw = set()
            for e in entries[-10:]:  # Last 10 entries
                all_kw.update(e.get("keywords", [])[:5])
            context_info["recent_keywords"] = sorted(all_kw)[:20]
            context_info["last_date"] = entries[-1].get("date", "")

    # Build context loading decision
    loaded_context = None
    if load_context == "yes" and context_info["has_previous"]:
        loaded_context = _load_session_context(root)
    elif load_context == "ask" and context_info["has_previous"]:
        # Return info so AI client can ask user
        pass  # context_info already has the summary

    # Save session record
    sessions_path = root / "data" / "sessions.jsonl"
    sessions_path.parent.mkdir(parents=True, exist_ok=True)
    session_record = {
        "session_id": session_id,
        "platform": active_platform,
        "channel_action": channel_action,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(sessions_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(session_record, ensure_ascii=False) + "\n")

    result = {
        "session_id": session_id,
        "available_platforms": platforms,
        "active_platform": active_platform,
        "context": context_info,
        "channel_action": channel_action,
    }

    if not platforms:
        result["setup_hint"] = (
            "No push platform configured. Paper search and curation work fine without push.\n"
            "To enable push notifications, set env vars for any platform:\n"
            "  Telegram: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID\n"
            "  Discord:  DISCORD_WEBHOOK_URL\n"
            "  Feishu:   FEISHU_WEBHOOK_URL\n"
            "  WeCom:    WECOM_WEBHOOK_URL"
        )
    elif len(platforms) > 1 and not active_platform:
        result["ask_platform"] = (
            f"Multiple push platforms detected: {', '.join(platforms.keys())}. "
            "Ask the user which one to use, then call init_session again "
            "with platform=<chosen>."
        )

    if loaded_context:
        result["loaded_context"] = loaded_context

    if load_context == "ask" and context_info["has_previous"]:
        result["ask_user"] = (
            f"Found {context_info['entries']} previous research entries "
            f"(last: {context_info.get('last_date', '?')}). "
            f"Recent keywords: {', '.join(context_info.get('recent_keywords', [])[:10])}. "
            "Load previous context? (The AI client should ask the user)"
        )

    return result


@mcp.tool()
def load_session_context(session_id: str | None = None) -> dict:
    """Load previous research context into current session.

    Call this after init_session if user chose to load context.
    Returns accumulated keywords and summaries from interests.jsonl.

    Args:
        session_id: If provided, only load context from this session.
                    If None, load all previous context.
    """
    root = _get_root()
    return _load_session_context(root, session_id)


def _load_session_context(root: Path, session_id: str | None = None) -> dict:
    """Internal: load research context from interests.jsonl."""
    interests_path = root / "data" / "interests.jsonl"
    if not interests_path.exists():
        return {"keywords": [], "summaries": [], "entry_count": 0}

    entries = _load_jsonl(interests_path)

    if session_id:
        entries = [e for e in entries if e.get("session_id") == session_id]

    all_keywords: set[str] = set()
    summaries = []
    for e in entries:
        all_keywords.update(e.get("keywords", []))
        if e.get("summary"):
            summaries.append({
                "date": e.get("date", ""),
                "summary": e["summary"][:200],
            })

    return {
        "keywords": sorted(all_keywords)[:50],
        "summaries": summaries[-10:],  # Last 10
        "entry_count": len(entries),
    }


# ── Setup & Configuration ─────────────────────────────────────────────────

def _is_first_run(root: Path) -> bool:
    """Check if this is a fresh install (no real topics configured)."""
    prefs_path = root / "data" / "topic_prefs.json"
    if not prefs_path.exists():
        return True
    prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
    topics = prefs.get("topics", {})
    # Only has the seed "example-topic" or empty
    return not topics or list(topics.keys()) == ["example-topic"]


@mcp.tool()
def setup() -> dict:
    """Check setup status and guide first-time configuration.

    Call this FIRST when starting a new session. Returns setup state and
    instructions for the AI client on what to ask the user.

    If setup is complete, returns current config summary.
    If first run, returns step-by-step instructions for the AI to follow.
    """
    root = _get_root()
    cfg = load_config()
    prefs_path = root / "data" / "topic_prefs.json"
    prefs = json.loads(prefs_path.read_text(encoding="utf-8")) if prefs_path.exists() else {"topics": {}}
    pcfg_path = root / "config" / "pipeline_config.json"
    pcfg = json.loads(pcfg_path.read_text(encoding="utf-8")) if pcfg_path.exists() else {}

    first_run = _is_first_run(root)

    # Detect platforms
    platforms = []
    if cfg.telegram_bot_token and cfg.telegram_chat_id:
        platforms.append("telegram")
    if cfg.discord_webhook_url:
        platforms.append("discord")
    if cfg.feishu_webhook_url:
        platforms.append("feishu")
    if cfg.wecom_webhook_url:
        platforms.append("wecom")

    result = {
        "first_run": first_run,
        "data_dir": str(root),
        "topics": {k: {"label": v.get("label", k), "keywords": v.get("keywords", [])}
                   for k, v in prefs.get("topics", {}).items()
                   if k != "example-topic"},
        "paper_count": pcfg.get("paper_count", {"mode": "at_most", "value": 6}),
        "push_platforms": platforms,
        "zotero_configured": bool(cfg.zotero_library_id and cfg.zotero_api_key),
    }

    if first_run:
        result["agent_instructions"] = (
            "This is a first-time setup. Guide the user step by step.\n"
            "Ask ONE question at a time. Wait for the user's answer before moving on.\n"
            "\n"
            "## Step 1: Research Topics (REQUIRED)\n"
            "Ask: 'What are your research interests?'\n"
            "The user can describe in natural language. Extract 1-5 topics, each with a label\n"
            "and 3-5 keywords. Call `add_topic()` for each one.\n"
            "Confirm the extracted topics with the user before proceeding.\n"
            "\n"
            "## Step 2: Push Platform (RECOMMENDED)\n"
            "Ask: 'Want to receive daily paper pushes? Supported platforms:'\n"
            "- Telegram (need bot token + chat ID)\n"
            "- Discord (need webhook URL)\n"
            "- Feishu / 飞书 (need webhook URL)\n"
            "- WeCom / 企业微信 (need webhook URL)\n"
            "\n"
            "If the user wants push, guide them to set the corresponding env vars.\n"
            "Push message format: title, journal, two-line summary, DOI link.\n"
            "If not interested, skip — paper search still works without push.\n"
            "\n"
            "## Step 3: Paper Library Website (OPTIONAL)\n"
            "Ask: 'Want a personal paper library website? It auto-updates with each push.'\n"
            "If yes, guide the user through:\n"
            "1. Fork the template repo: https://github.com/Eclipse-Cj/paper-library-template\n"
            "2. Connect to Vercel (free): import the forked repo, deploy\n"
            "3. Create a deploy hook in Vercel (Settings > Git > Deploy Hooks)\n"
            "4. Give the deploy hook URL to the agent — save via:\n"
            "   `configure(site_deploy_hook='https://api.vercel.com/...')`\n"
            "\n"
            "Once configured, every `finalize_review()` will auto-push a digest JSON\n"
            "to the site repo and trigger a Vercel rebuild.\n"
            "\n"
            "## Step 4: Summarizer / Scraper (RECOMMENDED)\n"
            "Tell the user:\n"
            "'Paper summarization (extracting key info from abstracts) can consume a lot of tokens.\n"
            "You can delegate this to a cheaper agent or API to save costs significantly.'\n"
            "\n"
            "Options:\n"
            "- **self** (default): this agent does it (most expensive, uses your main model tokens)\n"
            "- **A cheaper agent** (e.g. 'scraper'): if the user has a scraper/utility agent,\n"
            "  specify its name. The summarization prompt will be forwarded to that agent.\n"
            "- **An API endpoint**: if the user has a cheap LLM API (e.g. DeepSeek, local Ollama),\n"
            "  provide the URL. Paper data will be sent there for extraction.\n"
            "\n"
            "Call `configure(summarizer='scraper')` or `configure(summarizer='https://...')`.\n"
            "If the user doesn't have one, keep default 'self' and move on.\n"
            "\n"
            "## Step 5: Preferences (OPTIONAL — show defaults, ask if they want to change)\n"
            "Present all available settings as a summary table, then ask:\n"
            "'These are the default settings. Want to customize any of them?'\n"
            "\n"
            "Available settings (all via `configure()`):\n"
            "- **Papers per push**: at most 6 (mode: at_most/at_least/exactly, value: integer)\n"
            "- **Review mode**: single (one AI reviews) or dual (two AIs blind review independently, then merge)\n"
            "- **Ranking weights** (must sum to ~1.0):\n"
            "  - relevance=0.55 (keyword match to topics)\n"
            "  - recency=0.20 (prefer recent papers)\n"
            "  - impact=0.15 (citation count)\n"
            "  - novelty=0.10 (not previously seen)\n"
            "- **Custom screening focus**: free text criteria for the AI reviewer\n"
            "  (e.g. 'prefer clinical trials over reviews', 'focus on deep learning methods')\n"
            "\n"
            "If the user says 'defaults are fine' or similar, skip to Step 6.\n"
            "If they want changes, call `configure()` with the relevant parameters.\n"
            "\n"
            "## Step 6: First Search\n"
            "Tell the user: 'Setup complete! Running your first paper search...'\n"
            "Call `pool_refresh()` to search all configured topics.\n"
        )
    else:
        result["agent_instructions"] = (
            "Setup is complete. The user has configured topics.\n"
            "You can proceed with `pool_status()` to check pool state,\n"
            "or `pool_refresh()` if the pool is exhausted.\n"
            "\n"
            "If the user wants to change settings, use `configure()` or `add_topic()`.\n"
            "Available settings: paper_count, picks_per_reviewer, review_mode, ranking weights\n"
            "(w_relevance, w_recency, w_impact, w_novelty), custom_focus, scan_batches.\n"
            "\n"
            "Push & site: user can set up push platform or paper library website anytime.\n"
            "Guide them through the steps if they ask."
        )

    return result


@mcp.tool()
def add_topic(key: str, label: str, keywords: list[str], weight: float = 1.0) -> dict:
    """Add a research topic for paper search.

    Args:
        key: Short identifier (e.g. "llm-reasoning", "rag-retrieval"), lowercase with hyphens
        label: Human-readable name (e.g. "LLM Reasoning")
        keywords: Search keywords for this topic (3-5 recommended)
        weight: Priority weight 0.0-1.0 (default 1.0 = highest priority)
    """
    root = _get_root()
    prefs_path = root / "data" / "topic_prefs.json"
    prefs = json.loads(prefs_path.read_text(encoding="utf-8")) if prefs_path.exists() else {"topics": {}}

    # Remove seed example-topic on first real topic
    if "example-topic" in prefs.get("topics", {}):
        del prefs["topics"]["example-topic"]

    prefs.setdefault("topics", {})[key] = {
        "weight": max(0.0, min(1.0, weight)),
        "blocked": False,
        "label": label,
        "keywords": keywords,
    }

    prefs_path.write_text(json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"ok": True, "topic": key, "label": label, "keywords": keywords,
            "total_topics": len(prefs["topics"])}


@mcp.tool()
def configure(
    paper_count_mode: str | None = None,
    paper_count_value: int | None = None,
    custom_focus: str | None = None,
    review_mode: str | None = None,
    w_relevance: float | None = None,
    w_recency: float | None = None,
    w_impact: float | None = None,
    w_novelty: float | None = None,
    picks_per_reviewer: int | None = None,
    scan_batches: int | None = None,
    site_deploy_hook: str | None = None,
    site_repo_path: str | None = None,
    summarizer: str | None = None,
) -> dict:
    """Update pipeline configuration.

    All parameters are optional — only provided values are changed.

    Args:
        paper_count_mode: "at_most", "at_least", or "exactly"
        paper_count_value: Number of papers per push (e.g. 6)
        custom_focus: Custom screening criteria (e.g. "prefer clinical trials over reviews")
        review_mode: "single" (one AI reviews) or "dual" (two AIs review independently)
        w_relevance: Ranking weight for topic relevance (default 0.55)
        w_recency: Ranking weight for publication recency (default 0.20)
        w_impact: Ranking weight for citation impact (default 0.15)
        w_novelty: Ranking weight for novelty/unseen (default 0.10)
        picks_per_reviewer: Papers each reviewer selects per scan (default 5)
        scan_batches: Number of scan batches per pool cycle (default 3, pool is reviewed over batches+1 days)
        site_deploy_hook: Vercel deploy hook URL for auto-deploying paper library website
        site_repo_path: Local path to the paper library site repo (for pushing digest JSON)
        summarizer: Who handles paper summarization to save tokens. Options:
                    - "self" (default): main agent summarizes (most expensive)
                    - agent name (e.g. "scraper"): delegate to a cheaper agent
                    - API URL: call an external summarization endpoint
    """
    root = _get_root()
    pcfg_path = root / "config" / "pipeline_config.json"
    pcfg_path.parent.mkdir(parents=True, exist_ok=True)
    pcfg = json.loads(pcfg_path.read_text(encoding="utf-8")) if pcfg_path.exists() else {}

    if paper_count_mode or paper_count_value:
        pc = pcfg.get("paper_count", {"mode": "at_most", "value": 6})
        if paper_count_mode:
            pc["mode"] = paper_count_mode
        if paper_count_value:
            pc["value"] = paper_count_value
        pcfg["paper_count"] = pc

    if custom_focus is not None:
        pcfg["custom_focus"] = custom_focus

    if review_mode is not None:
        pcfg["review_mode"] = review_mode

    # Ranking weights
    weights = pcfg.get("ranking_weights", {})
    if w_relevance is not None:
        weights["relevance"] = w_relevance
    if w_recency is not None:
        weights["recency"] = w_recency
    if w_impact is not None:
        weights["impact"] = w_impact
    if w_novelty is not None:
        weights["novelty"] = w_novelty
    if weights:
        pcfg["ranking_weights"] = weights

    if picks_per_reviewer is not None:
        pcfg["picks_per_reviewer"] = picks_per_reviewer

    if scan_batches is not None:
        pcfg["scan_batches"] = scan_batches

    if site_deploy_hook is not None:
        pcfg["site_deploy_hook"] = site_deploy_hook

    if site_repo_path is not None:
        pcfg["site_repo_path"] = site_repo_path

    if summarizer is not None:
        pcfg["summarizer"] = summarizer

    pcfg_path.write_text(json.dumps(pcfg, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"ok": True, "config": pcfg}


# ── Site Deploy ────────────────────────────────────────────────────────────

def _auto_deploy_site(data_dir: Path) -> str | None:
    """Push latest digest to paper library site and trigger Vercel rebuild."""
    import subprocess

    pcfg_path = data_dir / "config" / "pipeline_config.json"
    if not pcfg_path.exists():
        return None
    pcfg = json.loads(pcfg_path.read_text(encoding="utf-8"))

    deploy_hook = pcfg.get("site_deploy_hook", "")
    repo_path = pcfg.get("site_repo_path", "")
    if not deploy_hook or not repo_path:
        return None

    repo = Path(repo_path)
    if not repo.exists():
        return None

    # Find today's papers from papers.jsonl
    papers_path = data_dir / "data" / "papers.jsonl"
    if not papers_path.exists():
        return None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_papers = []
    for line in papers_path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        p = json.loads(line)
        if p.get("push_date") == today:
            today_papers.append(p)

    if not today_papers:
        return None

    # Write digest JSON to site repo
    digests_dir = repo / "src" / "content" / "digests"
    digests_dir.mkdir(parents=True, exist_ok=True)
    digest_path = digests_dir / f"{today}.json"
    digest_path.write_text(json.dumps(today_papers, ensure_ascii=False, indent=2), encoding="utf-8")

    # Sync topic_prefs to site
    prefs_src = data_dir / "data" / "topic_prefs.json"
    prefs_dst = repo / "data" / "topic_prefs.json"
    if prefs_src.exists():
        prefs_dst.parent.mkdir(parents=True, exist_ok=True)
        prefs_dst.write_text(prefs_src.read_text(encoding="utf-8"), encoding="utf-8")

    # Git push — only add specific files we wrote, never -A
    files_to_add = [str(digest_path)]
    if prefs_dst.exists():
        files_to_add.append(str(prefs_dst))
    try:
        subprocess.run(["git", "add"] + files_to_add, cwd=str(repo), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"digest {today}: {len(today_papers)} papers"],
            cwd=str(repo), check=True, capture_output=True,
        )
        subprocess.run(["git", "push"], cwd=str(repo), check=True, capture_output=True)
    except subprocess.CalledProcessError:
        return "Site: git push failed"

    # Trigger Vercel deploy
    import httpx
    try:
        httpx.post(deploy_hook, timeout=10)
    except Exception:
        return "Site: digest pushed but deploy hook failed"

    return f"Site: deployed {len(today_papers)} papers, Vercel rebuilding"


# ── V2 Pipeline Tools ─────────────────────────────────────────────────────

def _pipeline_config(data_dir: Path) -> dict:
    """Build pipeline config dict from topic_prefs.json + pipeline_config.json."""
    prefs_path = data_dir / "data" / "topic_prefs.json"
    prefs = json.loads(prefs_path.read_text(encoding="utf-8")) if prefs_path.exists() else {"topics": {}}

    # Optional pipeline config for custom_focus, review_mode, paper_count
    pcfg_path = data_dir / "config" / "pipeline_config.json"
    pcfg = json.loads(pcfg_path.read_text(encoding="utf-8")) if pcfg_path.exists() else {}

    return {
        "topics": prefs.get("topics", {}),
        "paper_count": pcfg.get("paper_count", {"mode": "at_most", "value": 6}),
        "picks_per_reviewer": pcfg.get("picks_per_reviewer", 5),
        "custom_focus": pcfg.get("custom_focus", ""),
        "review_mode": pcfg.get("review_mode", "single"),
        "ranking_weights": pcfg.get("ranking_weights", {}),
        "scan_batches": pcfg.get("scan_batches", 3),
    }


def _data_dir() -> Path:
    """Get data directory (= project_root from MCP config)."""
    return _get_root()


@mcp.tool()
async def pool_refresh(topic: str | None = None) -> dict:
    """Refresh the paper search pool by querying 9 academic APIs.

    Call this when pool is exhausted or when adding a new research topic.
    Searches: OpenAlex, Semantic Scholar, PubMed, arXiv, Papers with Code,
    CrossRef, Europe PMC, bioRxiv, DBLP.

    Args:
        topic: Optional single topic key to search (for new topics).
               If None, refreshes all topics.
    """
    _ensure_sys_path()
    from paper_digest.pipeline import pool_refresh as _pool_refresh

    data_dir = _data_dir()
    config = _pipeline_config(data_dir)
    pool = await _pool_refresh(config, data_dir / "data", single_topic=topic)

    from paper_digest.pool import pool_stats
    return pool_stats(pool)


@mcp.tool()
def prepare_review(dual: bool = False) -> str:
    """Prepare the review prompt for today's scan batch.

    Returns a structured prompt listing candidate papers for the AI to review.
    The AI should respond with push/overflow/discard decisions in JSON format.

    If pool is exhausted, returns "POOL_EXHAUSTED" — call pool_refresh first.

    Args:
        dual: Enable dual review mode (two reviewers each pick 3 papers)
    """
    _ensure_sys_path()
    from paper_digest.pipeline import prepare_review as _prepare_review

    data_dir = _data_dir()
    config = _pipeline_config(data_dir)
    return _prepare_review(config, data_dir / "data", dual=dual)


@mcp.tool()
def finalize_review(selections: str, is_final: bool = False) -> str:
    """Process AI review decisions, update pool, and generate push output.

    Takes the AI's review response (JSON with push/overflow/discard decisions),
    updates paper statuses in the pool, appends pushed papers to papers.jsonl,
    and returns formatted push message.

    Args:
        selections: JSON string with review decisions, e.g.
                    '[{"index": 1, "action": "push", "tldr": "..."}, ...]'
        is_final: True for final review (no discard allowed, only push/overflow)
    """
    _ensure_sys_path()
    from paper_digest.pipeline import finalize as _finalize

    data_dir = _data_dir()
    config = _pipeline_config(data_dir)
    result = _finalize(selections, config, data_dir / "data", is_final_review=is_final)

    # Auto-deploy to paper library website if configured
    site_result = _auto_deploy_site(data_dir)
    if site_result:
        result += f"\n{site_result}"

    return result


@mcp.tool()
def collect(paper_indices: str, obsidian_mode: str = "none") -> str:
    """Collect pushed papers to Zotero and optionally create Obsidian notes.

    Use after finalize_review. Paper indices refer to the latest push
    (1-based, e.g. "1,3" to collect papers 1 and 3).

    Args:
        paper_indices: Comma-separated 1-based indices (e.g. "1,3")
        obsidian_mode: "none" (Zotero only), "summary" (with AI summary note),
                       or "template" (empty template for user notes)
    """
    _ensure_sys_path()
    from paper_digest.pipeline import do_collect as _do_collect

    data_dir = _data_dir()
    config = _pipeline_config(data_dir)
    return _do_collect(paper_indices, config, data_dir / "data", obsidian_mode=obsidian_mode)


@mcp.tool()
def pool_status() -> dict:
    """Show current pool status: paper counts by status, scan day, topics searched.

    Returns:
        Dict with total, by_status, scan_day, total_scan_days, exhausted, etc.
    """
    _ensure_sys_path()
    from paper_digest.pool import load_pool, pool_stats

    data_dir = _data_dir()
    pool = load_pool(data_dir / "data")
    return pool_stats(pool)


@mcp.tool()
def prepare_summarize(custom_focus: str = "") -> dict:
    """Generate a summarization prompt for unsummarized papers in today's batch.

    Returns a dict with:
    - prompt: the summarization prompt (structured fields to extract)
    - summarizer: who should process this prompt ("self", agent name, or API URL)
    - paper_count: how many papers need summarizing

    If summarizer is NOT "self", the calling agent should delegate this prompt
    to the specified agent or API instead of processing it directly.
    This can save significant token costs.

    Args:
        custom_focus: Optional custom screening criteria to include
    """
    _ensure_sys_path()
    from paper_digest.pipeline import prepare_summarize_prompt

    data_dir = _data_dir()
    prompt = prepare_summarize_prompt(data_dir / "data", custom_focus=custom_focus)

    # Load summarizer config
    pcfg_path = data_dir / "config" / "pipeline_config.json"
    pcfg = json.loads(pcfg_path.read_text(encoding="utf-8")) if pcfg_path.exists() else {}
    summarizer = pcfg.get("summarizer", "self")

    # Count papers in prompt
    paper_count = prompt.count("### Paper ")

    return {
        "prompt": prompt,
        "summarizer": summarizer,
        "paper_count": paper_count,
        "token_hint": (
            f"This prompt contains {paper_count} papers to summarize. "
            "If summarizer is not 'self', delegate this to the specified agent/API "
            "to avoid spending main agent tokens on bulk extraction."
        ) if summarizer != "self" else None,
    }


# ── MCP Resources ──────────────────────────────────────────────────────────

@mcp.resource("paper-distill://topics")
def get_topics() -> str:
    """Current research topic preferences (topic_prefs.json)."""
    root = _get_root()
    prefs_path = root / "data" / "topic_prefs.json"
    if not prefs_path.exists():
        return "{}"
    return prefs_path.read_text(encoding="utf-8")


@mcp.resource("paper-distill://history")
def get_history() -> str:
    """Recent push history (last 30 entries from pushes.jsonl)."""
    root = _get_root()
    entries = _load_jsonl(root / "data" / "pushes.jsonl")
    recent = entries[-30:] if len(entries) > 30 else entries
    return json.dumps(recent, ensure_ascii=False, indent=2)


@mcp.resource("paper-distill://config")
def get_config() -> str:
    """System configuration (API keys redacted)."""
    cfg = load_config()
    safe = {
        "data_dir": cfg.data_dir,
        "site_url": cfg.site_url,
        "openalex_email": cfg.openalex_email,
        "telegram_configured": bool(cfg.telegram_bot_token and cfg.telegram_chat_id),
        "discord_configured": bool(cfg.discord_webhook_url),
        "feishu_configured": bool(cfg.feishu_webhook_url),
        "wecom_configured": bool(cfg.wecom_webhook_url),
        "zotero_configured": bool(cfg.zotero_library_id and cfg.zotero_api_key),
        "deepseek_configured": bool(cfg.deepseek_api_key),
    }
    return json.dumps(safe, ensure_ascii=False, indent=2)


# ── Entry point ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Paper Distill MCP Server")
    parser.add_argument(
        "--transport", choices=["stdio", "http"], default="stdio",
        help="MCP transport (default: stdio)",
    )
    parser.add_argument(
        "--port", type=int, default=8765,
        help="HTTP port (only used with --transport http)",
    )
    parser.add_argument(
        "--data-dir", type=str, default=None,
        help="Override PAPER_DISTILL_DATA_DIR",
    )
    args = parser.parse_args()

    if args.data_dir:
        os.environ["PAPER_DISTILL_DATA_DIR"] = args.data_dir

    if args.transport == "http":
        mcp.run(transport="streamable-http", host="127.0.0.1", port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
