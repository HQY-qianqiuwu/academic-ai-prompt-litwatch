# LitWatch 文献雷达

LitWatch 是一个面向个人研究者的多源论文监测应用：定期检索 OpenAlex、arXiv，并可选接入 Semantic Scholar，按相关性、时效性、影响力和开放获取状态排序，对高分论文做可选的摘要/开放全文分析，并通过网页、邮件和 Zotero 进入后续阅读流程。

## 为什么这样实现

你提供的调研方向基本正确，但截至 2026-07-31 又出现了两个值得关注的项目：

- [paper-distill-mcp](https://github.com/Eclipse-Cj/paper-distill-mcp) 的功能覆盖最完整，已经包含 11 个数据源、四维排序、Zotero 和多平台推送；它的 README 同时明确标注仍处于早期开发阶段，适合作为可选增强层，不适合作为唯一基础设施。
- [research-claw](https://github.com/nanoAgentTeam/research-claw) 已经包含研究雷达、定时摘要、全文阅读和多渠道推送，但范围远超“文献监测”，而且 Windows 需要 WSL2，部署和维护成本更高。

因此本项目采用较稳妥的分层方案：

1. **发现层**：OpenAlex 负责正式出版物和广覆盖，arXiv 负责低延迟预印本，Semantic Scholar 负责补充检索和引用数据。
2. **判断层**：先做零成本、可解释的确定性排序，再只把少量高分论文交给 LLM，避免让模型承担召回和初筛。
3. **证据层**：明确区分 `abstract` 与 `fulltext_excerpt`。只有开放 PDF 成功下载并抽取文字时，才标记为全文节选分析。
4. **状态层**：SQLite 保存历史结果和运行记录，避免周报重复失忆。
5. **交付层**：同一份结果可在网页查看、发邮件、写入 Zotero；任何一个出口失效都不会破坏检索数据。

这套实现没有复制上述 AGPL/GPL 项目代码，便于后续独立演进。

## 五分钟启动（Windows）

建议安装 [uv](https://docs.astral.sh/uv/)，然后在 PowerShell 中执行：

```powershell
Copy-Item .env.example .env
Copy-Item config/topics.example.yaml config/topics.yaml
uv sync
uv run litwatch scan --days 14
uv run litwatch serve
```

浏览器打开 <http://127.0.0.1:8000>。首次无需 API Key：OpenAlex、arXiv、评分、数据库和网页都可工作。编辑 `config/topics.yaml` 即可调整研究方向和排除词。Semantic Scholar 的匿名共享池在定时任务中容易触发 429，因此默认只在配置 `LITWATCH_SEMANTIC_SCHOLAR_API_KEY` 后启用；临时测试可设置 `LITWATCH_SEMANTIC_SCHOLAR_ANONYMOUS=true`。

## 开启 AI 分析

在 `.env` 中配置任意 OpenAI 兼容接口：

```dotenv
LITWATCH_LLM_API_KEY=sk-...
LITWATCH_LLM_BASE_URL=https://api.openai.com/v1
LITWATCH_LLM_MODEL=gpt-5-mini
```

`LITWATCH_ANALYZE_TOP_N` 控制每个主题最多分析多少篇；`LITWATCH_FULLTEXT_TOP_N` 控制其中最多多少篇尝试下载开放 PDF。没有密钥时系统只跳过 AI 步骤，不影响其他功能。

## 邮件、Zotero 与定时运行

填好 `.env` 中的 SMTP 配置后：

```powershell
uv run litwatch scan --days 14 --email
```

填好 Zotero 用户 ID 和具有写权限的 API Key 后：

```powershell
uv run litwatch zotero-export --min-score 0.55 --limit 20
```

定时运行有两种方式：

- 仓库内的 `.github/workflows/weekly.yml` 默认每周一北京时间 08:00 执行；在 GitHub Actions 的 Variables/Secrets 中配置对应变量。
- 本机执行 `./scripts/install-scheduled-task.ps1`，创建 Windows 每周计划任务。

## 评分说明

总分由以下部分组成，所有分项会存入数据库，后续可以检查为什么某篇论文入选：

| 分项 | 权重 | 含义 |
|---|---:|---|
| 相关性 | 58% | 主题短语在标题和摘要中的命中情况，标题命中权重更高 |
| 时效性 | 18% | 45 天指数衰减 |
| 影响力 | 10% | 引用量对数归一化；新论文不会因零引用被直接淘汰 |
| 开放获取 | 8% | 是否有可验证的开放 PDF |
| 元数据完整度 | 6% | 摘要、DOI、作者是否齐全 |

排除词优先级最高。每个主题的 `min_score` 控制入选阈值。

## 当前边界

- IEEE Xplore、ACM 和 CNKI 没有适合默认匿名调用的统一开放接口。OpenAlex/Semantic Scholar 能覆盖其中大量元数据，但不能保证等同于直接检索这些商业数据库。
- 全文分析只处理合法可访问的开放 PDF，不绕过付费墙。
- GitHub Actions 的 SQLite 数据在每次 runner 结束后不会自动持久化；如果要在网页长期保留历史，请部署到持久卷，或把 `data/` 改接托管数据库。
- Web 页面的“立即扫描”是同步任务，适合个人规模；后续数据量大时应换成后台队列。

## 开发验证

```powershell
uv sync --extra dev
uv run pytest
uv run ruff check .
```
