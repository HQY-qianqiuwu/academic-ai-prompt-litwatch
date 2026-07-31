# Academic AI Prompt × LitWatch

这是一个把“学术研究 Prompt 方法库”变成真实可运行工具的项目。

原仓库提供论文选题、文献查找、文献综述和论文写作的 89+ 个中文 Prompt；新增的 **LitWatch 文献雷达**负责从真实学术 API 检索论文、验证元数据、去重、排序、分析、汇总和推送。

> 原则：**API 找论文，AI 读论文；不让 AI 凭记忆编造论文清单。**

## LitWatch 能做什么

- OpenAlex + arXiv 多源检索，可选 Semantic Scholar
- DOI、arXiv ID、规范化标题三级去重
- 相关性、时效、引用、开放获取和元数据完整度综合评分
- 快速检索表单与长期监测主题
- 快速筛选、综述矩阵、经典与前沿、最接近工作等分析模式
- 明确区分摘要分析和开放 PDF 全文节选分析
- SQLite 历史记录、Web 仪表盘、HTML 邮件和 Zotero 导出
- GitHub Actions 与 Windows 每周定时任务

## 快速启动（Windows）

建议先安装 [uv](https://docs.astral.sh/uv/)，然后执行：

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

## 配置 AI 分析

编辑 `.env`：

```dotenv
LITWATCH_LLM_API_KEY=sk-...
LITWATCH_LLM_BASE_URL=https://api.openai.com/v1
LITWATCH_LLM_MODEL=gpt-5-mini
```

系统只对每个主题的高分论文调用模型。开放 PDF 成功提取时标记为 `fulltext_excerpt`，否则标记为 `abstract`，不会把摘要分析包装成全文精读。

## 长期监测

研究主题位于 [`config/topics.yaml`](config/topics.yaml)：

```yaml
topics:
  - id: underwater_acoustics
    name: 水声通信
    query: underwater acoustic communication channel estimation Doppler OFDM sonar
    include: [underwater acoustic, sonar, hydrophone, channel estimation]
    exclude: [medical ultrasound]
    categories: [eess.SP, eess.AS, cs.SD]
    analysis_mode: review_matrix
    min_score: 0.30
```

执行扫描：

```powershell
uv run litwatch scan --days 14
uv run litwatch scan --days 14 --email
```

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

