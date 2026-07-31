from __future__ import annotations

import json

import httpx

from litwatch.config import Settings, Topic
from litwatch.models import Paper


class PaperAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.Client(timeout=90, follow_redirects=True)

    @property
    def enabled(self) -> bool:
        return bool(self.settings.llm_api_key)

    def analyze(self, paper: Paper, topic: Topic, fulltext: str = "") -> dict[str, object]:
        if not self.enabled:
            return {"status": "skipped", "reason": "未配置 LLM API"}
        evidence = fulltext or paper.abstract
        if not evidence:
            return {"status": "skipped", "reason": "无摘要或可用全文"}

        modes = {mode.id: mode for mode in self.settings.load_analysis_modes()}
        mode = modes.get(topic.analysis_mode) or modes["quick_scan"]
        prompt = f"""你是严谨的科研文献筛选助手。只能依据提供的论文文本，不得补充未出现的事实、论文或引用。
研究主题：{topic.name}
关注点：{", ".join(topic.include)}
分析工作流：{mode.name}
工作流要求：{mode.instruction}
论文标题：{paper.title}
来源文本（{"开放全文节选" if fulltext else "摘要"}）：
{evidence[:36000]}

请输出 JSON 对象，字段固定为：
- one_liner: 一句话中文结论
- motivation: 研究动机
- methods: 核心方法，字符串数组
- results: 主要结果，字符串数组；无定量结果时明确写“摘要未报告”
- limitations: 局限，字符串数组；文本未说明时写“原文未明确说明”
- relevance: 与研究主题的具体关系
- paper_type: theory/method/experiment/application/review 中最接近的一类
- research_gap: 本文暴露或试图填补的研究空白；证据不足时明确说明
- reading_priority: 1 到 5 的整数
- workflow_output: 根据“分析工作流”要求生成的 JSON 对象
- evidence_level: "abstract" 或 "fulltext_excerpt"
- confidence: 0 到 1
"""
        response = self.client.post(
            self.settings.llm_base_url.rstrip("/") + "/chat/completions",
            headers={
                "Authorization": f"Bearer {self.settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.settings.llm_model,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        result = json.loads(content)
        result["status"] = "ok"
        result["evidence_level"] = "fulltext_excerpt" if fulltext else "abstract"
        return result
