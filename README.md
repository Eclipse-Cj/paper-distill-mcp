# 📚 Paper Distill MCP Server

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![PyPI version](https://img.shields.io/pypi/v/paper-distill-mcp.svg)](https://pypi.org/project/paper-distill-mcp/)
[![CI](https://github.com/Eclipse-Cj/paper-distill-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/Eclipse-Cj/paper-distill-mcp/actions/workflows/ci.yml)

学术论文搜索、智能筛选、多平台推送 —— 基于 [MCP 协议](https://modelcontextprotocol.io/)。

兼容所有 MCP 客户端：Claude Code、Cursor、Codex CLI、Gemini CLI、OpenClaw、VS Code、Zed 等。

> ⚠️ **项目仍处于早期开发阶段**，很多功能尚未充分验证，可能存在 bug 或不稳定之处。
> 如遇问题，请多多海涵，欢迎通过下方联系方式反馈！

---

## ✨ 核心特性

- 🔍 **9 源并行搜索** — OpenAlex、Semantic Scholar、PubMed、arXiv、Papers with Code、CrossRef、Europe PMC、bioRxiv、DBLP
- 🤖 **AI 自适应推送** — Agent 在对话中感知你的研究方向变化，自动调整搜索关键词和推送内容
- 📊 **4 维加权排序** — 相关性 × 新近度 × 影响力 × 新颖度，权重完全可自定义
- 👥 **双 AI 盲审** — 两个 AI 独立初选，主审综合终审决定推送、溢出或丢弃（可选）
- 🧹 **Scraper 代理** — 将论文摘要提取任务委托给低成本 agent 或 API，大幅减少 token 消耗
- 🌐 **论文库网站** — Astro + Vercel 自动部署，每次推送后 30 秒内网站更新
- 📬 **多平台推送** — Telegram / Discord / 飞书 / 企业微信
- 📦 **Zotero 集成** — 一键收藏论文到 Zotero 文献管理器
- 📝 **Obsidian 集成** — 自动生成论文笔记卡片，带 Zotero 反向链接，支持摘要模式和模板模式

---

## 🚀 一键安装

```bash
uvx paper-distill-mcp
```

搞定。AI 客户端会自动发现所有工具，基础论文搜索无需 API 密钥。

> 没有 uv？→ `curl -LsSf https://astral.sh/uv/install.sh | sh` 或 `brew install uv`

### 其他安装方式

<details>
<summary>pip / Homebrew / Docker / 源码安装</summary>

**pip:**

```bash
pip install paper-distill-mcp
```

国内用户加清华源加速：`pip install paper-distill-mcp -i https://pypi.tuna.tsinghua.edu.cn/simple`

**Homebrew:**

```bash
brew tap Eclipse-Cj/tap
brew install paper-distill-mcp
```

**Docker:**

```bash
docker run -i --rm ghcr.io/eclipse-cj/paper-distill-mcp
```

国内用户：`docker run -i --rm ghcr.nju.edu.cn/eclipse-cj/paper-distill-mcp`

**从源码安装（开发者）:**

```bash
git clone https://github.com/Eclipse-Cj/paper-distill-mcp.git
cd paper-distill-mcp
python3 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -e .
```

</details>

---

## 🔗 连接 AI 客户端

### Claude Code

```bash
claude mcp add paper-distill -- uvx paper-distill-mcp
```

或添加到 `.mcp.json`：

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

添加到 `~/.codex/config.toml`：

```toml
[mcp_servers.paper-distill]
command = "uvx"
args = ["paper-distill-mcp"]
```

### Gemini CLI (Google)

添加到 `~/.gemini/settings.json`：

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
mcporter list  # 验证
```

> 卸载：`mcporter config remove paper-distill`

<details>
<summary>从源码安装（PyPI 发布前）</summary>

```bash
# 1. 克隆
git clone https://github.com/Eclipse-Cj/paper-distill-mcp.git ~/.openclaw/tools/paper-distill-mcp

# 2. 安装（uv 自动处理 Python 版本）
cd ~/.openclaw/tools/paper-distill-mcp
uv venv .venv && uv pip install .

# 3. 注册到 mcporter
mcporter config add paper-distill \
  --command ~/.openclaw/tools/paper-distill-mcp/.venv/bin/python3 \
  --scope home \
  -- -m mcp_server.server

# 4. 验证
mcporter list
```

> 卸载：`rm -rf ~/.openclaw/tools/paper-distill-mcp && mcporter config remove paper-distill`

</details>

### 其他客户端 (Cursor, VS Code, Windsurf, Zed)

同样的 JSON 格式，不同配置路径：

| 客户端 | 配置路径 |
|--------|----------|
| Cursor | `~/.cursor/mcp.json` |
| VS Code | `.vscode/mcp.json` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` |
| Zed | `settings.json` |

### HTTP 传输（远程 / 托管）

```bash
paper-distill-mcp --transport http --port 8765
```

---

## 🎯 首次使用

安装后调用 `setup()` — 系统检测到全新安装，会引导你的 AI 完成初始化：

1. **研究方向** — 用自然语言描述你的兴趣，AI 提取关键词
2. **推送平台** — 设置 Telegram / Discord / 飞书 / 企业微信（可选）
3. **论文库网站** — 建立个人论文库网页，每次推送后自动更新（可选）
4. **Scraper 代理** — 设置低成本 agent 做信息提取，大幅节省 token（推荐）
5. **个性化偏好** — 论文数量、排序权重、评审模式等
6. **首次搜索** — `pool_refresh()` 填充论文池

所有设置都可以随时通过和 AI 对话修改，例如：
- "改成每次推 8 篇"
- "加一个方向：RAG 检索增强"
- "开启双 AI 盲审"
- "新近度权重调高一些"

---

## ⚙️ 完整配置参数

所有参数都可通过 `configure()` 或 `add_topic()` 工具修改。
直接告诉 AI 你想要什么 — 无需手动编辑配置文件。

### 研究方向 (`add_topic` / `manage_topics`)

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `key` | 方向标识符（如 `"llm-reasoning"`） | — |
| `label` | 显示名称（如 `"LLM Reasoning"`） | — |
| `keywords` | 搜索关键词，建议 3-5 个 | — |
| `weight` | 方向优先级 0.0-1.0（越高 = 越多相关论文） | `1.0` |
| `blocked` | 暂时停用某方向（不删除） | `false` |

### 论文数量与评审 (`configure`)

| 参数 | 选项 | 默认值 | 说明 |
|------|------|--------|------|
| `paper_count_value` | 任意整数 | `6` | 每次推送的论文数 |
| `paper_count_mode` | `"at_most"` / `"at_least"` / `"exactly"` | `"at_most"` | 数量模式 |
| `review_mode` | `"single"` / `"dual"` | `"single"` | 单 AI 评审 / 双 AI 盲审 |
| `custom_focus` | 自由文本 | `""` | 自定义筛选标准 |

> 💡 **双 AI 盲审**：两个 AI 独立评审同一批论文，两者都选中的论文置信度更高。
> 适合对推送质量要求高的场景。通过 `configure(review_mode="dual")` 开启。

### 排序权重 (`configure`)

控制论文评分，四项权重之和应约等于 1.0。

| 参数 | 衡量内容 | 默认值 |
|------|---------|--------|
| `w_relevance` | 关键词与方向的匹配度 | `0.55` |
| `w_recency` | 发表时间的新近程度 | `0.20` |
| `w_impact` | 引用量（对数归一化） | `0.15` |
| `w_novelty` | 是否为首次出现 | `0.10` |

> 示例："更看重最新论文" → `configure(w_recency=0.35, w_relevance=0.40)`

### Scraper / 摘要提取代理 (`configure`)

论文摘要提取（从 abstract 中提取结构化信息）是最消耗 token 的步骤。
默认由主 agent 完成 — 但可以委托给更便宜的 agent 或 API 来大幅节约成本。

| 参数 | 选项 | 说明 |
|------|------|------|
| `summarizer` | `"self"` | 主 agent 处理（最贵，用主模型 token） |
|  | agent 名称（如 `"scraper"`） | 委托给低成本 agent |
|  | API URL | 调用外部 LLM API（如 DeepSeek、本地 Ollama） |

> 🔧 **强烈建议设置 scraper**。对 30+ 篇论文做摘要提取时，用前沿模型成本很高，
> 而 $0.14/M-token 的模型完全胜任。如果你有 scraper agent 或便宜 API，
> 务必通过 `configure(summarizer="scraper")` 配置。

### 论文池与扫描批次 (`configure`)

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `scan_batches` | 将论文池分为 N 批，N+1 天内评审完毕 | `2`（3 天） |

**扫描批次工作原理**：`pool_refresh()` 搜索 9 个 API 后，所有结果进入论文池。
论文池被分成若干批次供 AI 逐日评审 — 避免一次性甩出 60+ 篇论文。

- `scan_batches=2`（默认）：第 1 天评审前半、第 2 天评审后半、第 3 天汇总
- `scan_batches=3`：第 1-3 天各评审 1/3、第 4 天汇总

全部批次评审完毕后，论文池耗尽，下次运行自动触发新一轮 API 搜索。

### 推送平台（环境变量）

| 平台 | 环境变量 | `platform` 参数 |
|------|---------|----------------|
| Telegram | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | `"telegram"` |
| Discord | `DISCORD_WEBHOOK_URL` | `"discord"` |
| 飞书 | `FEISHU_WEBHOOK_URL` | `"feishu"` |
| 企业微信 | `WECOM_WEBHOOK_URL` | `"wecom"` |

推送消息格式（固定）：
```
1. 论文标题 (年份)
   期刊名称
   - 一句话摘要
   - 推荐理由
   https://doi.org/...
```

### 论文库网站 (`configure`)

个人论文库网站，每次推送后自动更新。基于 Astro + Vercel（免费）。

| 参数 | 说明 |
|------|------|
| `site_deploy_hook` | Vercel deploy hook URL（触发网站重建） |
| `site_repo_path` | 本地 paper-library 仓库路径 |

配置步骤（AI agent 会引导你完成）：
1. Fork [paper-library-template](https://github.com/Eclipse-Cj/paper-library-template)（即将开源）
2. 连接 Vercel → 部署
3. 在 Vercel 创建 deploy hook（Settings > Git > Deploy Hooks）
4. 告诉 agent hook URL → 保存到 `configure(site_deploy_hook=...)`

配置完成后，每次 `finalize_review()` 会自动推送 digest JSON 到网站仓库并触发 Vercel 重建。
网站在约 30 秒内更新。

> ⚠️ 注意：Vercel.app 域名在中国大陆可能无法直接访问。建议绑定自定义域名，或使用 Cloudflare Pages 作为替代。

### 集成 & 环境变量

| 变量 | 说明 | 是否必需 |
|------|------|---------|
| `OPENALEX_EMAIL` | 提高 OpenAlex API 速率 | 可选 |
| `DEEPSEEK_API_KEY` | 增强搜索（DeepSeek） | 可选 |
| `ZOTERO_LIBRARY_ID` + `ZOTERO_API_KEY` | 保存论文到 Zotero | 可选 |
| `SITE_URL` | 论文库网站地址 | 可选 |
| `PAPER_DISTILL_DATA_DIR` | 数据目录 | 默认 `~/.paper-distill/` |

---

## 🛠️ 工具列表（19 个）

### 初始化 & 配置

| 工具 | 说明 |
|------|------|
| `setup()` | **首次调用** — 检测全新安装，返回引导式初始化指令 |
| `add_topic(key, label, keywords)` | 添加研究方向及搜索关键词 |
| `configure(...)` | 更新任意设置：论文数量、排序权重、评审模式等 |

### 搜索 & 筛选

| 工具 | 说明 |
|------|------|
| `search_papers(query)` | 9 源并行搜索 |
| `rank_papers(papers)` | 4 维加权评分 |
| `filter_duplicates(papers)` | 与已推送论文去重 |

### 每日流水线（论文池模式）

| 工具 | 说明 |
|------|------|
| `pool_refresh(topic?)` | 搜索 9 个 API，构建论文池 |
| `prepare_summarize(custom_focus?)` | 生成 AI 摘要提取提示 |
| `prepare_review(dual?)` | 生成评审提示 — AI 做 push/overflow/discard 决策 |
| `finalize_review(selections)` | 处理 AI 决策，更新论文池，输出推送消息 |
| `pool_status()` | 论文池状态：数量、扫描日、是否耗尽 |
| `collect(paper_indices)` | 收藏论文到 Zotero + Obsidian 笔记 |

### 会话 & 输出

| 工具 | 说明 |
|------|------|
| `init_session` | 检测推送平台，加载研究上下文 |
| `load_session_context` | 加载历史研究上下文 |
| `generate_digest(papers, date)` | 生成输出文件（JSONL、网站、Obsidian） |
| `send_push(date, papers, platform)` | 推送到 Telegram / Discord / 飞书 / 企业微信 |
| `collect_to_zotero(paper_ids)` | 通过 DOI 保存到 Zotero |
| `manage_topics(action, topic)` | 列出 / 停用 / 启用 / 设置权重 |
| `ingest_research_context(text)` | 跨会话研究上下文继承 |

---

## 🏗️ 架构

```
AI 客户端（Claude Code / Codex CLI / Gemini CLI / Cursor / ...）
    ↓ MCP（stdio 或 HTTP）
paper-distill-mcp
    ├── search/         — 9 源学术搜索
    ├── curate/         — 评分 + 去重
    ├── generate/       — 输出（JSONL、Obsidian、网站）
    ├── bot/            — 推送格式化（4 平台）
    └── integrations/   — Zotero API
```

服务器内部不调用 LLM。搜索、排序、去重都是纯数据操作。
智能来自你的 AI 客户端。

---

## 🧑‍💻 开发

```bash
git clone https://github.com/Eclipse-Cj/paper-distill-mcp.git
cd paper-distill-mcp
python3 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -e .
python tests/test_mcp_smoke.py   # 9 个测试，无需网络
```

---

## 📄 许可证

本项目采用 **AGPL-3.0** 许可证，详见 [LICENSE](LICENSE)。

**禁止未经授权的商业使用。** 如需商业授权，请联系作者。

---

## 📬 联系方式

- 邮箱：vertex.cj@gmail.com
- 小红书：回声Echo（小红书号 1101579039）

如遇 bug 或有功能建议，欢迎提 [Issue](https://github.com/Eclipse-Cj/paper-distill-mcp/issues) 或直接联系。
项目仍处于早期开发和测试阶段，感谢你的理解和支持 🙏
