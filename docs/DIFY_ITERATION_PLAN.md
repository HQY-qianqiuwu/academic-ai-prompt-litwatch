# Dify Iteration Plan

## v1.0

OpenAlex 单源文献检索

状态：Stable

## v1.1

LitWatch 统一检索 API

状态：Stable

- FastAPI endpoint：完成
- 离线 API contract tests：完成
- LitWatch-backed Dify DSL：完成
- Windows Host 调用：通过
- Dify Docker → LitWatch 调用：通过
- Dify DSL 导入：通过
- Dify 已认证实际运行：通过
- 动态 topic 检索：通过
- Stable tag：dify-v1.1

## v1.2

Provider Configuration Layer

状态：实现完成，本地 E2E 待验证

- 保持 v1.1 `topic + limit` 请求兼容
- 搜索请求可选 `providers`
- Provider Profile + Credential Reference
- OpenAlex 作为唯一可运行 Provider
- Semantic Scholar、arXiv、Crossref、IEEE Xplore、Scopus 和 Web of Science 仅注册能力
- API Key 不进入 Git、YAML、SQLite、Dify DSL 或 API 响应
- 未创建 v1.2 DSL，未创建 Stable tag

## v1.2.x

逐个实现并验证 Semantic Scholar、arXiv、Crossref 等 Provider Adapter

## v1.3

RSS 增量文献监测

## v1.4

跨数据源 DOI / title 去重与评分

## v1.5

Zotero 自动分类与同步

## v1.6

Dify LLM 文献相关性筛选

## v1.7

摘要级文献结构化精读

## v1.8

PDF / 全文分析

## v1.9

跨论文对比、Research Gap、综述

## v2.0

完整自动化科研文献工作流
