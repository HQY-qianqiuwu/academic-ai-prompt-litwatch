# LitWatch 每周可视化研究简报

## 目标

每次扫描完成后，LitWatch 会把最近一次运行中入选的真实论文整理为一份可视化周报。周报同时出现在本地动态网页、Codespaces 和 GitHub Pages 的当周历史快照中。

## 周报内容

- 本期入选论文数、结构化提炼覆盖率、开放获取率和平均匹配度。
- 按监测主题统计的论文分布，以条形图显示占比。
- 基于已有分析字段统计的理论、方法、实验、应用、综述等研究类型。
- 每个主题的高频关注短语、自动主题阐述和前三篇优先阅读论文。
- 每篇论文的核心内容、主题阐述、方法、结果、局限、研究空白和证据级别。

## 数据与证据边界

周报不凭空生成论文或结论。论文元数据来自已启用的学术数据源；核心内容优先使用保存的 LLM 分析，其次使用摘要抽取。主题阐述优先使用分析结果中的 `relevance`，不存在时只根据论文标题和所属监测主题生成保守说明。

页面会继续展示 `evidence_level`：

- `fulltext_excerpt`：分析使用了合法开放 PDF 的全文节选。
- `abstract`：分析只使用摘要。
- `none`：没有足够文本，不做内容推断。

## 自动更新

- Windows 计划任务 `LitWatch Weekly Scan` 默认每周一 08:00 扫描最近 14 天。
- GitHub Pages 工作流默认每周一北京时间 08:00 扫描、生成周报并保存历史快照。
- 手动执行 `litwatch scan --days 14` 后，刷新本地网页即可看到新周报。

## JSON 导出

```powershell
uv run litwatch weekly-report --output reports/latest-weekly-report.json
```

可使用 `--topic underwater_acoustics` 只导出一个主题。JSON 包含 KPI、主题聚合、研究类型、来源分布和优先论文，可用于后续绘图、Obsidian 或其他研究工作流。

## 与分阶段重构方案的关系

本功能保持现有 Web、CLI、SQLite、邮件、Pages 和 Windows 任务兼容。领域锚点门控、阅读状态、反馈与 Obsidian 导出仍按 `CODEX_LITWATCH_IMPLEMENTATION.md` 的后续阶段推进；本周报聚合层不会假装这些尚未实现的能力已经完成。
