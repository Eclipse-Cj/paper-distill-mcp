# 📚 Paper Distill MCP Server

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![PyPI version](https://img.shields.io/pypi/v/paper-distill-mcp.svg)](https://pypi.org/project/paper-distill-mcp/)
[![CI](https://github.com/Eclipse-Cj/paper-distill-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/Eclipse-Cj/paper-distill-mcp/actions/workflows/ci.yml)

<!-- mcp-name: io.github.Eclipse-Cj/paper-distill-mcp -->

Academic paper search, intelligent curation, and multi-platform delivery — built on the [Model Context Protocol](https://modelcontextprotocol.io/).

Compatible with all MCP clients: Claude Desktop, Claude Code, Cursor, Trae, Codex CLI, Gemini CLI, OpenClaw, VS Code, Zed, and more.

> ⚠️ **Early development stage.** Many features are still being validated and may contain bugs or instabilities. Feedback and bug reports are warmly welcome!

---

## ✨ Features

- 🔍 **11-source parallel search** — OpenAlex, Semantic Scholar, PubMed, arXiv, Papers with Code, CrossRef, Europe PMC, bioRxiv, DBLP, CORE, Unpaywall
- 🤖 **Adaptive AI delivery** — the agent tracks your evolving research interests and automatically refines search keywords and recommendations over time
- 📊 **4-dimensional weighted ranking** — relevance × recency × impact × novelty, fully customizable weights
- 👥 **Dual-AI blind review** — two AI reviewers independently shortlist papers; a chief reviewer synthesizes a final push/overflow/discard decision (optional)
- 🧹 **Scraper delegation** — offload abstract extraction to a low-cost agent or API to cut token spend significantly
- 🌐 **Personal paper library site** — Astro + Vercel auto-deploy; site updates within 30 seconds of each push
- 📬 **Multi-platform delivery** — Telegram / Discord / Feishu / WeCom
- 📦 **Zotero integration** — save papers to Zotero with one command
- 📝 **Obsidian integration** — auto-generate paper note cards with Zotero backlinks; supports summary and template modes

---

## 🚀 Quick Install

```bash
uvx paper-distill-mcp
```

That's it. Your AI client will discover all tools automatically. No API keys required for basic paper search.

> No `uv`? → `curl -LsSf https://astral.sh/uv/install.sh | sh` or `brew install uv`

<details>
<summary>Other installation methods (pip / Homebrew / Docker / source)</summary>

**pip:**

```bash
pip install paper-distill-mcp
```

**Homebrew:**

```bash
brew tap Eclipse-Cj/tap
brew install paper-distill-mcp
```

**Docker:**

```bash
docker run -i --rm ghcr.io/eclipse-cj/paper-distill-mcp
```

**From source (developers):**

```bash
git clone https://github.com/Eclipse-Cj/paper-distill-mcp.git
cd paper-distill-mcp
python3 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -e .
```

</details>

---

## 🔗 Connecting to AI Clients

### Claude Desktop

Add to `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "paper-distill": {
      "command": "uvx",
      "args": ["paper-distill-mcp"]
    }
  }
}
```

### Claude Code

```bash
claude mcp add paper-distill -- uvx paper-distill-mcp
```

Or add to `.mcp.json`:

```json
{
  "mcpServers": {
    "paper-distill": {
      "command": "uvx",
      "args": ["paper-distill-mcp"]
    }
  }
}
```

### Codex CLI (OpenAI)

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.paper-distill]
command = "uvx"
args = ["paper-distill-mcp"]
```

### Gemini CLI (Google)

Add to `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "paper-distill": {
      "command": "uvx",
      "args": ["paper-distill-mcp"]
    }
  }
}
```

### OpenClaw

```bash
mcporter config add paper-distill --command uvx --scope home -- paper-distill-mcp
mcporter list  # verify
```

> To remove: `mcporter config remove paper-distill`

<details>
<summary>OpenClaw — install from source</summary>

```bash
git clone https://github.com/Eclipse-Cj/paper-distill-mcp.git ~/.openclaw/tools/paper-distill-mcp
cd ~/.openclaw/tools/paper-distill-mcp
uv venv .venv && uv pip install .
mcporter config add paper-distill \
  --command ~/.openclaw/tools/paper-distill-mcp/.venv/bin/python3 \
  --scope home \
  -- -m mcp_server.server
mcporter list
```

> To remove: `rm -rf ~/.openclaw/tools/paper-distill-mcp && mcporter config remove paper-distill`

</details>

### Other clients (Cursor, VS Code, Windsurf, Zed, Trae)

Same JSON config, different config file paths:

| Client | Config path |
|--------|-------------|
| Claude Desktop | `claude_desktop_config.json` |
| Trae | Settings → MCP → Add |
| Cursor | `~/.cursor/mcp.json` |
| VS Code | `.vscode/mcp.json` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` |
| Zed | `settings.json` |

### HTTP transport (remote / hosted)

```bash
paper-distill-mcp --transport http --port 8765
```

---

## 🎯 Getting Started

After connecting your client, tell the agent **"initialize paper-distill"**. It will call `setup()` and walk you through:

1. **Research topics** — describe your interests in plain language; the AI extracts keywords
2. **Delivery platform** — set up Telegram / Discord / Feishu / WeCom (optional)
3. **Paper library site** — build a personal paper library that updates automatically (optional)
4. **Scraper delegate** — point to a low-cost agent or API for abstract extraction (recommended)
5. **Preferences** — paper count, ranking weights, review mode, etc.
6. **First search** — `pool_refresh()` populates the paper pool

All settings can be updated at any time through conversation:
- "Push 8 papers next time"
- "Add a new topic: RAG retrieval"
- "Enable dual-AI blind review"
- "Increase recency weight"

---

## ⚙️ Configuration Reference

All parameters are set via `configure()` or `add_topic()` — no manual file editing needed.

### Research Topics (`add_topic` / `manage_topics`)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `key` | Topic identifier (e.g. `"llm-reasoning"`) | — |
| `label` | Display name (e.g. `"LLM Reasoning"`) | — |
| `keywords` | Search keywords, 3–5 recommended | — |
| `weight` | Topic priority 0.0–1.0 (higher = more papers) | `1.0` |
| `blocked` | Temporarily disable without deleting | `false` |

### Paper Count & Review (`configure`)

| Parameter | Options | Default | Description |
|-----------|---------|---------|-------------|
| `paper_count_value` | any integer | `6` | Papers per push |
| `paper_count_mode` | `"at_most"` / `"at_least"` / `"exactly"` | `"at_most"` | Count mode |
| `picks_per_reviewer` | any integer | `5` | Shortlist size per reviewer |
| `review_mode` | `"single"` / `"dual"` | `"single"` | Single AI or dual blind review |
| `custom_focus` | free text | `""` | Custom selection criteria |

> 💡 **Dual blind review**: two independent AI reviewers each shortlist papers; a chief reviewer makes the final push/overflow/discard call. Papers that don't make the cut are held for the next cycle rather than discarded. Enable with `configure(review_mode="dual")`.

### Ranking Weights (`configure`)

Controls paper scoring. The four weights should sum to approximately 1.0.

| Parameter | Measures | Default |
|-----------|----------|---------|
| `w_relevance` | Keyword and topic match | `0.55` |
| `w_recency` | How recently the paper was published | `0.20` |
| `w_impact` | Citation count (log-normalized) | `0.15` |
| `w_novelty` | Whether this is the first appearance | `0.10` |

> Example: "Prioritize recent papers" → `configure(w_recency=0.35, w_relevance=0.40)`

### Scraper / Abstract Extraction Delegate (`configure`)

Abstract extraction is the most token-intensive step. It runs on the main agent by default, but can be delegated to a cheaper model to cut costs significantly.

| Parameter | Value | Description |
|-----------|-------|-------------|
| `summarizer` | `"self"` | Main agent handles extraction (most expensive) |
| | agent name (e.g. `"scraper"`) | Delegate to a low-cost sub-agent |
| | API URL | Call an external LLM API (DeepSeek, Ollama, etc.) |

> 🔧 **Strongly recommended**: for 30+ papers, frontier model costs add up fast. A $0.14/M-token model handles extraction just as well. Set this with `configure(summarizer="scraper")`.

### Paper Pool & Scan Batches (`configure`)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `scan_batches` | Split the paper pool into N batches, reviewed over N+1 days | `2` (3 days) |

`pool_refresh()` searches all 11 APIs and fills the pool. The pool is then split into batches for daily AI review — avoiding a single 60+ paper dump.

- `scan_batches=2` (default): review first half on day 1, second half on day 2, finalize on day 3
- `scan_batches=3`: review one-third per day, finalize on day 4

When all batches are reviewed, the pool is exhausted and the next run triggers a fresh API search automatically.

### Delivery Platforms (Environment Variables)

| Platform | Environment variables | `platform` value |
|----------|-----------------------|------------------|
| Telegram | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | `"telegram"` |
| Discord | `DISCORD_WEBHOOK_URL` | `"discord"` |
| Feishu | `FEISHU_WEBHOOK_URL` | `"feishu"` |
| WeCom | `WECOM_WEBHOOK_URL` | `"wecom"` |

> ⚠️ **Important**: set environment variables in the MCP client config `env` field, not as system environment variables. Otherwise `send_push()` cannot access the webhook URL and the AI may generate scripts that call webhooks directly, causing encoding issues.

Config example (WeCom + Claude Desktop):

```json
{
  "mcpServers": {
    "paper-distill": {
      "command": "uvx",
      "args": ["paper-distill-mcp"],
      "env": {
        "WECOM_WEBHOOK_URL": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY"
      }
    }
  }
}
```

Restart the MCP client after editing the config.

Push message format (fixed):

```
1. Paper Title (Year)
   Journal Name
   - One-sentence summary
   - Why it was selected
   https://doi.org/...
```

### Paper Library Site (`configure`)

Personal paper library website, auto-updated on every push. Built on Astro + Vercel (free tier).

| Parameter | Description |
|-----------|-------------|
| `site_deploy_hook` | Vercel deploy hook URL (triggers site rebuild) |
| `site_repo_path` | Local path to the paper-library repository |

Setup steps (the AI agent will guide you):
1. Create a repo from the [paper-library-template](https://github.com/Eclipse-Cj/paper-library-template)
2. Connect to Vercel and deploy
3. Create a deploy hook in Vercel (Settings > Git > Deploy Hooks)
4. Tell the agent the hook URL → saved via `configure(site_deploy_hook=...)`

After setup, every `finalize_review()` call pushes the digest JSON to the site repo and triggers a Vercel rebuild. The site updates in ~30 seconds.

### Zotero Integration

Save papers to Zotero with one command. Requires a Zotero account and API key.

**Getting credentials:**
1. **API Key**: go to [zotero.org/settings/keys/new](https://www.zotero.org/settings/keys/new) → check "Allow library access" + "Allow write access" → Save Key
2. **Library ID**: go to [zotero.org/settings/keys](https://www.zotero.org/settings/keys) → your userID is shown at the top

**Add to MCP client config:**

```json
{
  "mcpServers": {
    "paper-distill": {
      "command": "uvx",
      "args": ["paper-distill-mcp"],
      "env": {
        "ZOTERO_LIBRARY_ID": "your userID",
        "ZOTERO_API_KEY": "your API key"
      }
    }
  }
}
```

After setup, reply `collect 1 3` after a push to save papers 1 and 3 to Zotero, automatically sorted into per-topic folders.

### All Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENALEX_EMAIL` | Increases OpenAlex API rate limit; also used for Unpaywall | optional |
| `CORE_API_KEY` | CORE API key ([free registration](https://core.ac.uk/services/api)) | optional |
| `DEEPSEEK_API_KEY` | Enhanced search via DeepSeek | optional |
| `ZOTERO_LIBRARY_ID` + `ZOTERO_API_KEY` | Save papers to Zotero | optional |
| `SITE_URL` | Paper library website URL | optional |
| `PAPER_DISTILL_DATA_DIR` | Data directory | default: `~/.paper-distill/` |

---

## 🛠️ Tools (19 total)

### Setup & Configuration

| Tool | Description |
|------|-------------|
| `setup()` | **First call** — detects fresh install and returns guided initialization instructions |
| `add_topic(key, label, keywords)` | Add a research topic with search keywords |
| `configure(...)` | Update any setting: paper count, ranking weights, review mode, etc. |

### Search & Curation

| Tool | Description |
|------|-------------|
| `search_papers(query)` | Parallel search across 11 sources |
| `rank_papers(papers)` | 4-dimensional weighted scoring |
| `filter_duplicates(papers)` | Deduplicate against previously pushed papers |

### Daily Pipeline (paper pool mode)

| Tool | Description |
|------|-------------|
| `pool_refresh(topic?)` | Search all 11 APIs and build the paper pool |
| `prepare_summarize(custom_focus?)` | Generate AI abstract extraction prompt |
| `prepare_review(dual?)` | Generate review prompt — AI makes push/overflow/discard decisions |
| `finalize_review(selections)` | Process AI decisions, update pool, output push message |
| `pool_status()` | Pool status: count, scan day, exhausted or not |
| `collect(paper_indices)` | Save papers to Zotero + generate Obsidian notes |

### Session & Output

| Tool | Description |
|------|-------------|
| `init_session` | Detect delivery platform and load research context |
| `load_session_context` | Load historical research context |
| `generate_digest(papers, date)` | Generate output files (JSONL, site, Obsidian) |
| `send_push(date, papers, platform)` | Deliver to Telegram / Discord / Feishu / WeCom |
| `collect_to_zotero(paper_ids)` | Save to Zotero via DOI |
| `manage_topics(action, topic)` | List / disable / enable / reweight topics |
| `ingest_research_context(text)` | Inherit research context across sessions |

---

## 🏗️ Architecture

```
AI client (Claude Code / Codex CLI / Gemini CLI / Cursor / ...)
    ↓ MCP (stdio or HTTP)
paper-distill-mcp
    ├── search/         — 11-source academic search (with OA full-text enrichment)
    ├── curate/         — scoring + deduplication
    ├── generate/       — output (JSONL, Obsidian, site)
    ├── bot/            — push formatting (4 platforms)
    └── integrations/   — Zotero API
```

The server does not call any LLM internally. Search, ranking, and deduplication are pure data operations. Intelligence comes from your AI client.

---

## 📖 Paywalled Papers & Open Access

The system searches all papers by default (including subscription journals) and maximizes free full-text access through:

1. **CORE** — world's largest OA aggregator (200M+ papers), covering author self-archived versions from institutional repositories
2. **Unpaywall** — after merging results, automatically looks up legal free PDFs via DOI (preprints, green OA, author versions)

For papers with no free version, the system returns a DOI link. If you have institutional VPN access, clicking the DOI link while connected is usually enough — publishers identify your institution by IP.

> `open_access_url` priority: arXiv > CORE > Unpaywall > OpenAlex > Semantic Scholar > Papers with Code

---

## ❓ FAQ

### Review stage hangs / no response for 30+ minutes

**Symptom**: the review prompt generated by `prepare_review()` causes the AI client to hang or time out.

**Cause**: too many candidate papers in the pool (e.g. 80–100), making the prompt exceed the client's context window or output token limit. VS Code Copilot and some IDE plugins have limited context capacity.

**Solutions** (pick one):
1. **Increase `scan_batches`** (recommended) — split the pool into more batches:
   ```
   configure(scan_batches=5)
   ```
2. **Reduce topics or keywords** — fewer topics → fewer search results → smaller pool.
3. **Switch to a higher-context client** — Claude Code (200k), Claude Desktop (200k), or Cursor handle long prompts better.

### Install error: `Requires-Python >=3.10`

Python 3.10+ is required. macOS ships with Python 3.9 by default — install a newer version with `brew install python@3.13` or use `uv`.

### Docker image fails to pull (mainland China)

`ghcr.io` is blocked in mainland China. Use pip with a Chinese mirror:

```bash
pip install paper-distill-mcp -i https://pypi.tuna.tsinghua.edu.cn/simple
```

---

## 🧑‍💻 Development

```bash
git clone https://github.com/Eclipse-Cj/paper-distill-mcp.git
cd paper-distill-mcp
python3 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -e .
python tests/test_mcp_smoke.py   # 9 tests, no network required
```

---

## 📄 License

This project is licensed under **AGPL-3.0**. See [LICENSE](LICENSE) for details.

**Unauthorized commercial use is prohibited.** For commercial licensing inquiries, contact the author.

---

## 📬 Contact

- Email: vertex.cj@gmail.com
- GitHub Issues: [Eclipse-Cj/paper-distill-mcp/issues](https://github.com/Eclipse-Cj/paper-distill-mcp/issues)

Bug reports and feature requests are welcome. The project is in active early development — thank you for your patience and support 🙏
