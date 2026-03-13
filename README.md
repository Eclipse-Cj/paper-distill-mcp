# 📚 Paper Distill MCP Server

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![PyPI version](https://img.shields.io/pypi/v/paper-distill-mcp.svg)](https://pypi.org/project/paper-distill-mcp/)
[![CI](https://github.com/Eclipse-Cj/paper-distill-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/Eclipse-Cj/paper-distill-mcp/actions/workflows/ci.yml)

学术论文搜索、智能筛选、多平台推送 —— 基于 [MCP 协议](https://modelcontextprotocol.io/)。

兼容所有 MCP 客户端：Claude Desktop、Claude Code、Cursor、Trae、Codex CLI、Gemini CLI、OpenClaw、VS Code、Zed 等。

> ⚠️ **项目仍处于早期开发阶段**，很多功能尚未充分验证，可能存在 bug 或不稳定之处。
> 如遇问题，请多多海涵，欢迎通过下方联系方式反馈！

---

## ✨ 核心特性

- 🔍 **11 源并行搜索** — OpenAlex、Semantic Scholar、PubMed、arXiv、Papers with Code、CrossRef、Europe PMC、bioRxiv、DBLP、CORE、Unpaywall
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

国内用户建议使用 pip 安装（清华源），Docker 镜像暂不支持国内加速。

**从源码安装（开发者）:**

```bash
git clone https://github.com/Eclipse-Cj/paper-distill-mcp.git
cd paper-distill-mcp
python3 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -e .
```

</details>

---

## 🔗 连接 AI 客户端

### Claude Desktop

添加到 `claude_desktop_config.json`（Settings → Developer → Edit Config）：

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

### Trae

设置 → MCP → 添加 MCP Server，JSON 配置同上。

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
| Claude Desktop | `claude_desktop_config.json` |
| Trae | 设置 → MCP → 添加 |
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

安装连接客户端后，告诉 Agent「初始化 paper-distill」，Agent 会自动调用 `setup()` 并引导你完成配置：

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
| `picks_per_reviewer` | 任意整数 | `5` | 每个 reviewer 初选的论文数 |
| `review_mode` | `"single"` / `"dual"` | `"single"` | 单 AI 评审 / 双 AI 盲审 |
| `custom_focus` | 自由文本 | `""` | 自定义筛选标准 |

> 💡 **双 AI 盲审**：两个 AI 各自独立初选 5 篇，主审综合终审决定推送（≤6 篇）或溢出，不推送的论文留到下一天而非丢弃。
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

**扫描批次工作原理**：`pool_refresh()` 搜索 11 个 API 后，所有结果进入论文池。
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

> ⚠️ **重要：环境变量必须配置在 MCP 客户端配置文件的 `env` 字段中**，而不是系统环境变量。
> 否则 `send_push()` 无法获取 webhook 地址，AI 可能会生成脚本（如 PowerShell）直接调用 webhook，
> 导致中文乱码等编码问题。

**配置文件在哪？** 找到你的 MCP 客户端对应的配置文件，在 paper-distill 的配置中加入 `env` 字段：

| 客户端 | 配置文件路径 |
|--------|-------------|
| Claude Desktop | `claude_desktop_config.json`（Settings → Developer → Edit Config） |
| Claude Code | `~/.claude/claude_code_config.json` 或项目 `.mcp.json` |
| Cursor | `~/.cursor/mcp.json` |
| Trae | 设置 → MCP → 添加（界面中填写） |
| VS Code (Copilot) | `.vscode/mcp.json` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` |
| Cherry Studio | 设置 → MCP 服务器 → 编辑（界面中填写环境变量） |
| Zed | `settings.json` |

配置示例（以企业微信 + Claude Desktop 为例）：

打开 `claude_desktop_config.json`，找到 `paper-distill` 的配置，加入 `env` 字段：

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

其他平台同理，把 `WECOM_WEBHOOK_URL` 换成对应的环境变量名和值即可。

添加后需**重启 MCP 客户端**使配置生效。

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
1. 使用 [paper-library-template](https://github.com/Eclipse-Cj/paper-library-template) 模板创建仓库（点击 "Use this template"）
2. 连接 Vercel → 部署
3. 在 Vercel 创建 deploy hook（Settings > Git > Deploy Hooks）
4. 告诉 agent hook URL → 保存到 `configure(site_deploy_hook=...)`

配置完成后，每次 `finalize_review()` 会自动推送 digest JSON 到网站仓库并触发 Vercel 重建。
网站在约 30 秒内更新。

> ⚠️ 注意：Vercel.app 域名在中国大陆可能无法直接访问。建议绑定自定义域名，或使用 Cloudflare Pages 作为替代。

### Zotero 集成

一键收藏论文到 Zotero 文献管理器。需要 Zotero 账号和 API 密钥。

**获取步骤：**

1. **API Key**：打开 [zotero.org/settings/keys/new](https://www.zotero.org/settings/keys/new) → 勾选 "Allow library access" + "Allow write access" → Save Key
2. **Library ID**：打开 [zotero.org/settings/keys](https://www.zotero.org/settings/keys) → 页面顶部显示 "Your userID for use in API calls is **123456**"

**配置到 MCP 客户端：**

```json
{
  "mcpServers": {
    "paper-distill": {
      "command": "uvx",
      "args": ["paper-distill-mcp"],
      "env": {
        "ZOTERO_LIBRARY_ID": "你的 userID",
        "ZOTERO_API_KEY": "你的 API Key"
      }
    }
  }
}
```

> ⚠️ **重要：必须在 MCP 客户端配置的 `env` 字段中设置这两个变量。**
> 如果未配置，AI 可能会尝试直接调用 Zotero API 而非使用内置的 `collect()` 工具，
> 导致论文条目只有 DOI、缺少标题和作者等元数据。

配置完成后，在推送结果中回复 `collect 1 3` 即可将第 1、3 篇论文保存到 Zotero，
并自动按研究方向归入对应的 Zotero 文件夹。

### 集成 & 环境变量

| 变量 | 说明 | 是否必需 |
|------|------|---------|
| `OPENALEX_EMAIL` | 提高 OpenAlex API 速率，同时用于 Unpaywall 查询 | 可选 |
| `CORE_API_KEY` | CORE API 密钥（[免费注册](https://core.ac.uk/services/api)） | 可选 |
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
| `search_papers(query)` | 11 源并行搜索 |
| `rank_papers(papers)` | 4 维加权评分 |
| `filter_duplicates(papers)` | 与已推送论文去重 |

### 每日流水线（论文池模式）

| 工具 | 说明 |
|------|------|
| `pool_refresh(topic?)` | 搜索 11 个 API，构建论文池 |
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
    ├── search/         — 11 源学术搜索（含 OA 全文增强）
    ├── curate/         — 评分 + 去重
    ├── generate/       — 输出（JSONL、Obsidian、网站）
    ├── bot/            — 推送格式化（4 平台）
    └── integrations/   — Zotero API
```

服务器内部不调用 LLM。搜索、排序、去重都是纯数据操作。
智能来自你的 AI 客户端。

---

## 📖 付费论文 & 全文获取

系统默认搜索覆盖所有论文（含付费期刊），并通过以下方式最大化免费全文获取：

1. **CORE** — 全球最大 OA 聚合平台（2 亿+篇），收录各大学机构库的作者自存档版本
2. **Unpaywall** — 搜索结果合并后，自动通过 DOI 查找合法免费 PDF（预印本、绿色 OA、作者版本）

对于确实没有免费版本的论文，系统返回 DOI 链接。**如果你有学校 VPN，连上后直接点击 DOI 链接即可下载** — 出版商通过 IP 识别学校身份，自动放行，无需额外登录。

> `open_access_url` 优先级：arXiv > CORE > Unpaywall > OpenAlex > Semantic Scholar > Papers with Code

---

## ❓ 常见问题

### Review 阶段卡住 / 半小时无响应

**症状**：`prepare_review()` 生成的审稿 prompt 发送给 AI 后，长时间无响应或超时。

**原因**：论文池中候选论文过多（如 80-100 篇），生成的 prompt 超出了客户端的上下文窗口或输出 token 上限。VS Code Copilot、部分 IDE 插件的上下文能力有限，无法处理这么长的结构化输入。

**解决方案**（任选其一）：

1. **增加 scan_batches**（推荐）— 把论文池拆成更多批次，每批审稿数量减少：
   ```
   configure(scan_batches=5)
   ```
   200 篇论文分 5 批 → 每天约 40 篇，大多数客户端都能正常处理。

2. **减少研究方向或关键词** — 方向越多，搜索结果越多。精简关键词可以从源头控制池子大小。

3. **换用上下文更大的客户端** — Claude Code（200k）、Claude Desktop（200k）、Cursor 等对长 prompt 支持更好。

### 安装报错 `Requires-Python >=3.10`

需要 Python 3.10 或更高版本。macOS 自带的 Python 通常是 3.9，请通过 `brew install python@3.13` 或 `uv` 安装新版本。

### Docker 镜像国内无法拉取

`ghcr.io` 在中国大陆被墙。建议使用 pip + 清华源安装：
```bash
pip install paper-distill-mcp -i https://pypi.tuna.tsinghua.edu.cn/simple
```

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
