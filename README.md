# Academic AI Prompt × LitWatch

这是一个把“学术研究 Prompt 方法库”变成真实可运行工具的项目。

原仓库提供论文选题、文献查找、文献综述和论文写作的 89+ 个中文 Prompt；新增的 **LitWatch 文献雷达**负责从真实学术 API 检索论文、验证元数据、去重、排序、分析、汇总和推送。

> 原则：**API 找论文，AI 读论文；不让 AI 凭记忆编造论文清单。**

## v2.0 默认运行方式（实现 / RC 准备阶段）

当前 v2.0 尚处于实现与 Release Candidate 准备阶段，**不是 Stable
版本，也没有 v2.0 Stable 标签**。默认运行路径已经切换为纯 Python
LitWatch：FastAPI、SQLite、Scheduler、JobWorker 和 Python LLM Gateway
共同提供检索、雷达、订阅、周报、任务与论文分析。

Windows 默认入口只管理 Python LitWatch：

```text
启动科研文献系统.cmd
停止科研文献系统.cmd
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\status-stack.ps1
```

这些默认入口不会探测、启动或要求 Docker Desktop、Dify、Dify Compose
或 Dify SSRF proxy；启动失败时也**不会自动回退到 Dify**。

项目已按用户决定删除 Dify 内容：旧版启动/停止入口、Dify 生命周期脚本
以及 `dify/workflows/` 下的 DSL 文件已从工作区移除，系统为纯 Python
运行时。历史 v1.0/v1.1 DSL 仍保留在 `dify-v1.0`、`dify-v1.1` 等 Git
tag 中，仅用于历史追溯；日常使用不需要也不提供 Dify 回滚入口。

## LitWatch 能做什么

- OpenAlex + arXiv 多源检索，可选 Semantic Scholar
- DOI、arXiv ID、规范化标题三级去重
- 相关性、时效、引用、开放获取和元数据完整度综合评分
- 快速检索表单与长期监测主题
- 快速筛选、综述矩阵、经典与前沿、最接近工作等分析模式
- 明确区分摘要分析和开放 PDF 全文节选分析
- SQLite 历史记录、Web 仪表盘、HTML 邮件和 Zotero 导出
- Codespaces 实时检索、GitHub Pages 每周快照与 Windows 定时任务
- 每周可视化研究简报：主题分布、提炼覆盖率、开放获取率、研究类型与优先阅读线索
- 每篇论文展示核心内容和文章主题阐述，周报也可导出为 JSON 继续分析

## 随时打开：Codespaces + GitHub Pages

两种入口服务于不同场景：

- [打开 LitWatch Codespace](https://codespaces.new/HQY-qianqiuwu/academic-ai-prompt-litwatch?quickstart=1)：可输入研究问题并立即检索、排序和提炼。容器创建后会自动安装项目，每次唤醒都会启动 8000 端口并打开网页。
- [查看 LitWatch 每周快照](https://HQY-qianqiuwu.github.io/academic-ai-prompt-litwatch/)：无需启动服务即可浏览最近结果和历史快照，并可直接使用 OpenAlex 即时轻量检索、导出本次 BibTeX；多源去重与深度提炼仍使用 Codespaces 或本地动态站点。

第一次创建 Codespace 时，建议从仓库的 **Code → Codespaces → New with options** 进入。页面会推荐填写以下可选密钥；全部留空也能使用 OpenAlex、arXiv 和基础抽取式提炼：

- `LITWATCH_LLM_API_KEY`：启用 LLM 深度分析。
- `LITWATCH_OPENALEX_EMAIL`：进入 OpenAlex polite pool，提高请求稳定性。
- `LITWATCH_SEMANTIC_SCHOLAR_API_KEY`：启用 Semantic Scholar 数据源。

`.github/workflows/pages.yml` 在每周一北京时间 08:00 扫描并更新 `gh-pages` 分支。首次部署后，在仓库 **Settings → Pages → Build and deployment** 中选择 **Deploy from a branch**，分支选择 `gh-pages` / `(root)`。后续快照会自动累积到“历史快照”。

## 快速启动（Windows）

默认的本地启动不需要 Docker 或 Dify。建议先安装
[uv](https://docs.astral.sh/uv/)，然后执行：

```powershell
Copy-Item .env.example .env
Copy-Item config/topics.example.yaml config/topics.yaml -ErrorAction SilentlyContinue
uv sync
uv run litwatch scan --days 14
uv run litwatch serve
```

浏览器打开 <http://127.0.0.1:8000>。不配置 LLM 密钥也可以完成检索、排序、存储和浏览。

当前工作区若已有 `.venv`，也可以直接运行：

```powershell
.\.venv\Scripts\litwatch.exe serve
```

## 本机长期使用（推荐）

本项目提供 Windows 登录自启和每周扫描任务。安装一次后，只要电脑已经登录，就可以随时打开固定地址 <http://127.0.0.1:8000>：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-local.ps1
```

安装内容：

- `LitWatch Web`：登录 Windows 后在后台启动本地网页；异常退出时自动重试。
- `LitWatch Weekly Scan`：每周一 08:00 检索最近 14 天论文并更新数据库。

每周任务日志保存在 `data/litwatch-weekly.log`，扫描中断或数据源异常时可直接查看原因。

也可以双击项目根目录的 `打开 LitWatch.cmd` 随时启动并打开网页，双击 `停止 LitWatch.cmd` 停止服务。卸载自动任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall-local.ps1
```

## 配置 AI 分析

编辑 `.env`：

```dotenv
LITWATCH_LLM_API_KEY=sk-...
LITWATCH_LLM_BASE_URL=https://api.openai.com/v1
LITWATCH_LLM_MODEL=gpt-5-mini
```

系统只对每个主题的高分论文调用模型。开放 PDF 成功提取时标记为 `fulltext_excerpt`，否则标记为 `abstract`，不会把摘要分析包装成全文精读。

没有配置模型密钥时，系统仍会基于真实摘要生成基础抽取式提炼，包括动机、方法句、结果句、局限提示和阅读优先级；配置模型后才会生成更深入的中文综述矩阵和研究空白分析。

## 长期监测

研究主题位于 [`config/topics.yaml`](config/topics.yaml)：

```yaml
topics:
  - id: underwater_acoustics
    name: 水声通信
    query: underwater acoustic communication channel estimation Doppler OFDM sonar
    include: [underwater acoustic, sonar, hydrophone, channel estimation]
    domain_anchors:
      any: [underwater acoustic, hydrophone, sonar]
    method_terms:
      any: [channel estimation, OFDM, Doppler compensation, beamforming]
    require_domain_anchor: true
    exclude: [medical ultrasound, mmWave, RIS-assisted, satellite communication]
    categories: [eess.SP, eess.AS, cs.SD]
    analysis_mode: review_matrix
    min_score: 0.30
```

`require_domain_anchor: true` 会先检查论文是否命中水声领域锚点，再计算 channel estimation、beamforming 等方法词相关性，避免仅因通用通信方法词而混入卫星、蜂窝或毫米波论文。旧主题不配置这些字段时继续使用原有排序行为。

执行扫描：

```powershell
uv run litwatch scan --days 14
uv run litwatch scan --days 14 --email
uv run litwatch weekly-report --output reports/latest-weekly-report.json
```

网页中的“自动周报”只汇总最近一次扫描入选的论文，并明确区分 AI 深度分析、基础摘要抽取和暂无提炼。每周历史快照会保留当期的主题可视化与文章阐述，详细口径见 [`docs/WEEKLY_REPORT.md`](docs/WEEKLY_REPORT.md)。

`.github/workflows/weekly.yml` 默认每周一北京时间 08:00 运行。Windows 本机可执行 `scripts/install-scheduled-task.ps1` 创建计划任务。

## Zotero 导出

配置 `.env` 中的 Zotero 用户 ID 和具有写权限的 API Key 后：

```powershell
uv run litwatch zotero-export --min-score 0.55 --limit 20
```

## 原 Prompt 库

原始内容完整保留，并继续作为方法和教学资源：

- [`论文查找系列/`](论文查找系列/)：搜索策略、筛选清单、分级推荐与论文对标
- [`文献综述系列/`](文献综述系列/)：综述框架、论文提炼与质量检查
- [`论文选题系列/`](论文选题系列/)：选题生成、五维评估与论证模板
- [`论文撰写系列/`](论文撰写系列/)：论文结构、各章节写作与文本优化
- [`索引`](索引)：原 Prompt 库完整导航

LitWatch 只采用其中适合自动化的工作流结构。涉及“直接列举论文”的 Prompt 在应用内被改为：先查询真实数据源，再让 AI 对已验证论文分析，避免虚构标题、作者、期刊或引用量。

## 数据源与边界

- OpenAlex 负责正式出版物和广覆盖；arXiv 负责低延迟预印本。
- Semantic Scholar 匿名共享池容易限流，因此默认仅在配置 API Key 后启用。
- IEEE Xplore、ACM、CNKI 等商业数据库没有统一的默认匿名接口。聚合数据源能覆盖其中许多元数据，但不等同于直接检索商业数据库。
- 全文分析只处理合法可访问的开放 PDF，不绕过付费墙。
- Web 的即时扫描适合个人使用；公开部署时应增加登录和后台任务队列。

## 开发验证

```powershell
uv sync --extra dev
uv run pytest
uv run ruff check .
```

## License

MIT。原 Prompt 库版权归其贡献者所有；新增应用代码同样按仓库 MIT License 发布。
