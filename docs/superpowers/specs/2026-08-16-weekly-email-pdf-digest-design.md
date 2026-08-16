# LitWatch 每周邮件 PDF 周报设计（Weekly Email PDF Digest）

## Goal

每周一 09:00（Asia/Shanghai），每个开启“每周邮件”的研究订阅自动把该周
高质量新文献通过邮件发送到用户在 Web UI 中配置的 QQ 邮箱。邮件正文为
HTML 摘要，并附带一份排版好的 PDF 版周报。QQ 邮箱地址可随时在网站界面
修改；SMTP 授权码只写不读。

## Scope

- `EmailSettings` 存储与“邮件设置”Web 页面（邮箱、启用开关、授权码、测试发送）。
- `DeliveryService` 增加 `email` 交付通道，复用现有 `deliveries` 表。
- HTML 正文 + PDF 附件渲染（PyMuPDF 内置 CJK 字体，不新增依赖）。
- 订阅级“每周邮件”开关；新建订阅默认每周一 09:00（Asia/Shanghai）。
- 幂等（同一 run 只发一次）与失败隔离（不影响 Dashboard 周报与 run 状态）。

## Non-goals

- 不发送论文原文 PDF（版权/付费墙限制，系统也不保存全文）。
- 不实现 CNKI / IEEE / Web of Science 数据源（另行规划）。
- 不做公网部署、账号体系、多收件人、HTML 模板自定义。
- 不擅自修改已有订阅的既有调度时间。

## Current state

- 订阅、每周调度、Run Engine、历史去重、Dashboard 周报已实现并 Stable 验证。
- `deliveries` 表已包含 `DeliveryChannel.EMAIL` 枚举与 `dashboard_deliveries`
  迁移（`src/litwatch/deliveries.py`、`src/litwatch/db.py`）。
- `notifier.py` 已有 `render_digest()`（HTML）与 `send_email()`（SMTP_SSL）。
- 运行环境已安装 PyMuPDF 1.28（`fitz`），可生成中文 PDF，无需新依赖。

## Architecture

### 1. EmailSettingsStore

- 非敏感字段（`recipient_email`、`enabled`、`smtp_host=smtp.qq.com`、
  `smtp_port=465`、`smtp_username`）通过新迁移新增单行 `email_settings` 表
  存放，可随时通过 UI 修改；订阅表新增 `email_enabled` 列（布尔，默认开）。
- SMTP 授权码**只写**：写入 `data/smtp-auth.secret` 本地文件（`data/` 已在
  `.gitignore`），应用启动时读入 `Settings`。任何 GET 响应、页面渲染、日志
  都不得包含授权码；UI 提交新值即覆盖旧值。

### 2. EmailDigestRenderer

- HTML 正文复用现有 digest 卡片样式：标题、作者、年份、期刊、摘要、来源、
  DOI、链接、综合评分/相关度/元数据质量。
- PDF 附件用 PyMuPDF 生成（内置 CJK 字体，如 `china-s`），内容与 HTML 一致。
- PDF 生成失败时降级为仅发送 HTML 正文，并在 delivery 中记录安全提示。

### 3. DeliveryService.deliver_email

- 在现有 `DeliveryService` 上新增 `deliver_email(subscription, run,
  recommendations)`。
- 按 `run_id` 幂等：同一 run 已有 `channel=email` 的 delivery 则直接返回，
  不重复发送。
- 发送失败：delivery 状态为 `failed` + `safe_error`（allowlist 消息），
  不影响 run 状态与 Dashboard 交付；下次合法 run 可重试。

### 4. Web UI

- 导航新增“邮件设置”：QQ 邮箱地址、启用开关、SMTP 授权码（`password`
  类型输入框，只写不回显）、保存按钮、测试发送按钮、最近发送状态展示。
- 订阅编辑页新增“每周邮件”开关（订阅模型增加 `email_enabled` 字段，
  默认开启）。
- 新建订阅表单默认 `weekday=Monday`、`time=09:00`、
  `timezone=Asia/Shanghai`；已有订阅时间保持不变，用户可自行修改。

### 5. Scheduler hook

- 订阅 run 以 `success` / `partial_success` 结束后：先执行现有
  `deliver_dashboard`，再在 `email_enabled` 且邮件已配置时执行
  `deliver_email`。

## Data flow

```text
Scheduler（每周一 09:00）
  -> Run Engine（检索/去重/历史去重/排序）
  -> recommendations
  -> deliver_dashboard（现有，不变）
  -> deliver_email：渲染 HTML + PDF
  -> SMTP(QQ) 发送到 recipient_email
  -> deliveries(channel=email, delivered|failed, safe_error)
```

## Error handling

- 未配置邮箱或授权码：跳过邮件，delivery=`failed`，
  `safe_error="Email not configured"`。
- SMTP 401/535：`safe_error="SMTP authentication failed"`，不输出任何凭据。
- 超时/网络错误：`failed`，下次合法 run 自动重试。
- PDF 渲染失败：仅发送 HTML，delivery=`delivered`，附加安全提示。
- 测试发送使用同一发送路径，不产生 `deliveries` 记录；失败仅显示安全错误。

## Security

- 授权码只写：API 不返回、页面不渲染、日志 redact、不进 Git（`data/` 已
  ignore）。
- 失败信息走 allowlist，禁止拼接原始异常或凭据。
- 邮件只发送到用户本人填写的收件人邮箱。

## Testing

- `EmailSettingsStore`：写入后可覆盖；读取接口与页面响应不含授权码。
- PDF 渲染：内容包含标题/作者/DOI/评分，中文可正常渲染。
- `deliver_email`：同 run 幂等；失败时 run 仍为 success；未配置时跳过。
- Web：邮件设置页保存/回显无 secret；订阅“每周邮件”开关生效。
- Scheduler：新建订阅默认周一 09:00；run 完成后按开关触发邮件。
- 回归：`python -m pytest -q`、`ruff check src tests`、`git diff --check`。

## Manual E2E

1. 用户在“邮件设置”填写 QQ 邮箱 + 授权码 → 点击“发送测试邮件”收到邮件。
2. 新建订阅（默认周一 09:00，开启每周邮件）→ Run Now → 收到 HTML + PDF
   周报邮件。
3. 重启 LitWatch：设置仍在、授权码不回显、订阅开关保持。
4. 同一 run 重复触发不产生第二封邮件。

## Versioning

- 在 `feat/v2.0-python-native-runtime` 分支基础上开发，不创建 Stable tag。
- 本功能按项目流程独立实现、独立测试、独立提交；版本归属（v2.x）待 v2.0
  人工验收后决定。
