# Dify 内网最简分发网关与兼容性探针

Windows + Python 3.10 或更新版本，使用标准库，无需安装依赖。当前提供单上游、单分发 Key 的最简网关和兼容性测试脚本。

## 管理界面预览

`frontend` 使用 Vue 3 + Vite，提供总览、调用日志和设置三个页面。保留海岸背景，可选择跟随当地时间、白天、傍晚、夜晚，切换场景动画；外观偏好保存在当前浏览器。系统开启“减少动态效果”时，场景动画遵循系统设置。

```powershell
cd frontend
npm ci
npm run dev
```

`npm run dev` 会先检查并启动 Python 管理后端（8788），再启动 Vite 前端；后端已经运行时会复用。保持终端运行，打开显示的前端本地地址。按 Ctrl+C 会停止本次命令启动的前后端进程，独立启动的后端继续运行。需要单独启动前端时可用 `npm run dev:frontend`。生产构建使用 `npm run build`。

前端通过同源 `/api` 访问管理服务；开发模式由 Vite 转发到 `127.0.0.1:8788`。管理服务可独立于 Dify 启动。超级用户可查看总览、网关日志和用户列表，普通用户可查看自己的账号与外观设置。统计和日志只读取现有网关 SQLite 中的脱敏元数据；数据库尚未生成时显示空状态。网关进程的实时状态与配置修改尚待接入，界面暂不包含应用管理。

## 登录与超级用户

在项目根目录初始化两个超级用户：

```powershell
python .\manager_server.py --init-superusers
python .\manager_server.py --set-password crescent039
python .\manager_server.py --set-password 123sswss
```

两个账号为 `crescent039` 和 `123sswss`，初始化可重复执行且保留已有密码。初始账号处于“待设置密码”状态；每个账号设置密码后才能登录。密码在终端交互输入，至少 6 个字符，保存为加盐 PBKDF2-SHA256 哈希。设置或重置密码会撤销该账号的已有会话。

启动管理服务：

```powershell
python .\manager_server.py
```

生产构建后可直接打开 `http://127.0.0.1:8788`，由该服务同时提供页面和 API。也可运行前面的 Vite 开发命令。管理服务默认仅监听本机；部署到内网时应配置 HTTPS 反向代理，并使用 `--secure-cookie`。API 分发网关仍单独运行在 8787，用户登录与 API 分发 Key 各自独立。

本机创建普通用户：

```powershell
python .\manager_server.py --create-user 用户名
```

用户名为 3–48 位字母、数字、下划线、点或短横线。当前最多两个超级用户，普通用户由本机命令创建，暂不提供公开注册和网页账号修改。超级用户可在“用户”页查看账号状态。账号与会话保存到已忽略的 `manager.sqlite3`；可通过 `--database` 指定路径，日志库通过 `--gateway-database` 指定。

会话有效期 8 小时，使用 HttpOnly、SameSite=Strict Cookie，数据库只保存会话令牌哈希。登录具备 5 分钟窗口内的账号与来源地址限次，写接口检查来源和 CSRF。所有 `/api/admin/*` 接口在后端校验超级用户角色，普通用户直接调用返回 403，未登录返回 401。请保护本机账号数据库文件的访问权限。

## 启动网关

将以下四个文件放在内网机器的同一个目录：`dify_gateway.py`、`dify_gateway.ini`、`dify_probe.py`、已经填好的 `dify_probe.ini`。

网关读取现有 `dify_probe.ini` 中 `[dify]` 的 `url` 和 `key`，保留原始配置；网关的监听、限制设置放在 `dify_gateway.ini`。运行：

```powershell
python .\dify_gateway.py
```

第一次启动自动生成分发 Key，保存到 `dify_gateway.ini` 的 `[distribution] key`，并显示在终端。之后启动沿用这个 Key。默认监听 `0.0.0.0:8787`，保持终端运行，按 Ctrl+C 停止。

- 同机使用分发 API 基础地址 `http://127.0.0.1:8787/v1`。
- 其他内网机器使用 `http://网关机器的内网IP:8787/v1`，Windows 防火墙需要允许该端口的内网入站访问。
- 客户端将地址和 Key 替换为分发地址、分发 Key，其余接口路径、参数和读取响应方式保持原样。例如工作流地址是 `http://网关机器的内网IP:8787/v1/workflows/run`。
- 所有 `/v1/...` 路径统一映射到原始 API 基础地址，保留路径后缀和查询参数。网关只向配置的上游发请求，替换 Authorization，透传请求体、响应体、上游状态码及端到端响应头。响应按块及时刷新，支持 SSE；传输分块和连接头由网关管理。

### 运行对照测试

启动网关后，把终端显示的地址与分发 Key 填到 `dify_probe.ini`：

```ini
[gateway]
url = http://127.0.0.1:8787/v1
key = 网关显示的分发Key
```

另开一个 PowerShell 窗口：

```powershell
python .\dify_probe.py --gateway
```

报告将同时包含直连和经过网关的结果，覆盖两种返回模式与运行详情查询。共享时只带回 `dify-report-*.json`。

### 限制与记录

`dify_gateway.ini` 的 `[distribution]` 支持：

| 字段 | 作用 |
| --- | --- |
| `key` | 分发 Key；留空后重启会生成新 Key |
| `enabled` | `true` 启用；`false` 停用并返回 403 |
| `max_requests` | 0 表示无限制；正整数表示该 Key 累计允许接收的请求数，耗尽返回 429 |
| `expires_at` | 留空表示永久；可填带时区的时间，例如 `2026-12-31T23:59:59+08:00`，到期返回 403 |

修改配置后重启生效。额度在通过 Key 检查后原子预扣，运行、查询、上传等每个 HTTP 请求都计一次，后续失败也占一次；被身份、停用、到期、额度检查拦截的请求不扣额度。计数存入 SQLite，重启保留；更换分发 Key 使用独立计数。

每次请求记录时间、接口类别、方法、HTTP 状态、耗时、响应字节数、传输结果。记录保存到 `gateway.sqlite3`，用以下命令查看最近 100 条：

```powershell
python .\dify_gateway.py --logs
```

`forwarded` 表示完整转发结束；工作流业务状态由 Dify 响应携带，测试脚本进一步检查 SSE 内的失败事件。记录省略原始地址、Key、完整路径、查询参数和业务正文。转发响应保留 Dify 原始内容，诊断时分享脱敏报告即可。

当前分发规模：一个上游、一个分发 Key，登录与日志管理由独立的 `manager_server.py` 提供。请求体最大 64 MiB，可通过 `max_body_mb` 调整；上传完整接收后转发，超过 1 MiB 使用临时文件，响应持续流式转发。`upstream_timeout` 默认 180 秒，是上游连接/单次读写等待时限。HTTPS 使用 Python 默认证书验证，自动重定向与系统代理关闭。断开连接会关闭对应上游 HTTP 连接，已启动工作流的停止行为以 Dify 为准。

本地验证使用模拟 Dify，覆盖工作流、SSE、多种 HTTP 方法、原始上传、错误响应、Key 校验、到期、停用、日志和并发额度。真实内网 Dify 的兼容性以 `--gateway` 报告为准。

## 内网运行

将 `dify_probe.py` 和 `dify_probe.ini` 一起复制到能访问 Dify 的机器。用文本编辑器打开 `dify_probe.ini`，填写 `[dify]` 下的 `url`、`key` 和 `inputs`，保存为 UTF-8。打开 PowerShell 运行：

```powershell
python .\dify_probe.py
```

配置字段：

1. `url`：Dify 的 **API 基础地址**，使用应用「访问 API」页面给出的地址，通常以 `/v1` 结尾。也接受完整 `/workflows/run` 地址，保留反向代理的路径前缀。填写地址本身。
2. `key`：原始应用 API Key，填写 Key 本身，省略引号与 Bearer 前缀。
3. `inputs`：工作流输入 JSON，字段名与用户输入节点变量一致。例如 `{"query":"请只输出 TEST_OK_123"}`。固定提示词工作流可以填 `{}`；多个必填变量需一起提供。输入节点变量须由工作流实际传给 LLM。

脚本默认从自身目录读取 `dify_probe.ini`，直接执行测试。自定义配置路径可用 `python .\dify_probe.py --config .\other.ini`。配置中的 `%`、`#`、`;` 原样保留，注释请单独占一行。

每个目标执行两次工作流：一次 blocking，一次 streaming；每次有运行 ID 时追加一次 GET 运行详情。可能产生模型费用。脚本自动发送固定测试用户标识 `gateway-compatibility-probe`。

网关建好后，在同一次测试中加入网关：

```powershell
python .\dify_probe.py --gateway
```

先填写 INI 中 `[gateway]` 的 `url` 和 `key`；网关复用 `[dify]` 的 `inputs`，合计执行四次工作流。报告保存到脚本同目录 `dify-report-*.json`，将该文件带回分析即可。退出码：0 全部通过，1 存在失败项，2 配置或脚本异常，130 手动取消。

## 脱敏约定

- 地址、Key、输入 JSON 从本地 INI 读取。**INI 明文保存敏感配置，请留在内网机器上，仅分享 JSON 报告。** `.gitignore` 已排除 `dify_probe.ini`、测试报告及 Python 缓存。
- 报告采用固定字段，只包含状态码、已知状态/事件枚举、计数、耗时、去掉字段名与值的输出类型结构，以及比较结果。
- 原始与网关地址、主机/IP、Key、用户输入、模型输出、运行 ID、响应头原文、错误消息和异常原文均省略。未知事件统一写为 `other`。
- 终端只显示固定提示、目标标签和结果，省略原始响应及 traceback。配置错误仅显示固定错误类别。
- 脚本读取现有配置文件，省略原始响应文件与敏感值摘要。INI 格式或字段错误仅显示固定错误类别。
- 给agent用来预览的文件夹位于/frontend/preview，已经忽略，GPT你要是想自己截图测试就在这个文件夹里玩好不好

## 判定范围

检查 HTTP 成功、工作流成功、outputs 对象存在；SSE 检查开始和结束事件、失败事件、JSON 解析和帧完整性；运行详情检查 ID 对应和执行成功。报告记录首批字节与首次 `data:` 到达时间，供分析缓冲问题；短工作流的时间数据只能作为线索。

网关比较的是两次独立执行。输出值可能因模型随机性变化，`output_value_equal` 作为参考；输出结构比较隐藏字段名，详细字段兼容性需后续专门验证。当前范围覆盖最简 Workflow，不包含聊天、知识库、文件、停止、额度和管理日志。

每次请求总时限默认 180 秒（`--timeout 300` 可调整），连接及单次读取最长等待 30 秒，响应上限 8 MiB。流式数据到达时计时，收到完整流后分析事件。HTTP 自动重定向与系统代理均关闭，HTTPS 使用系统默认的 Python 证书验证；认证请求仅发向填写的目标。

官方接口参考：[OpenAPI](https://docs.dify.ai/en/api-reference/openapi_service.json)、[流式响应](https://docs.dify.ai/en/api-reference/guides/streaming)。真实 Dify 兼容性以目标内网部署的运行报告为准。
