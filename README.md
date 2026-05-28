# astrbot_plugin_weather

定时天气推送插件，基于和风天气 API v7，可定时推送天气、仅推送特殊天气，支持 Agent 工具调用、会话上下文感知、LivingMemory 记忆集成和 DeepSeek V4 前缀缓存优化。

> **平台兼容**：本插件仅在weixin_oc进行测试，其他平台兼容性未知。

---

## AI 生成声明

> **本插件 100% 由 AI（大型语言模型）生成代码**，包括插件主体、工具定义、配置逻辑和文档。未经过专业安全审计或人工代码审查。

## 免责声明

1. **不提供任何保证**：本插件按"原样"提供，不附带任何明示或暗示的担保，包括但不限于适销性、特定用途适用性和非侵权性保证。
2. **使用风险自负**：使用者应自行承担使用本插件所带来的所有风险和责任。作者/AI 不对因使用或无法使用本插件而导致的任何直接、间接、附带、特殊或后果性损害承担责任。
3. **数据准确性**：天气数据来源于和风天气 API，数据的准确性、及时性和完整性由第三方服务商负责，本插件不对天气数据的准确性做任何保证。
4. **API 费用**：使用和风天气 API 可能产生费用，DeepSeek API 调用可能产生费用，使用者应自行了解和承担相关费用。
5. **安全风险**：插件涉及网络请求和外部 API 调用，可能存在未知的安全漏洞。API Key 等敏感信息以明文存储在本地 JSON 文件中（`weather_config.json`），请确保服务器文件系统安全。

---

## 功能

### 核心能力

| 功能 | 说明 |
|------|------|
| 定时天气推送 | 按可配置间隔（最小 5 分钟）自动推送天气到指定会话 |
| Agent 工具调用 | LLM 通过 Function Calling 主动调用 `get_weather` 获取实时 + 3 天预报 |
| IP 自动定位 | 首次使用时通过 ip-api.com → ipapi.co 自动检测用户城市，支持手动覆盖 |
| 免打扰时段 | 可配置静默时间窗口（如 22:00–07:00），检测到 DND 后自动顺延 10 分钟重试 |
| 特殊天气智能去重 | 按天气类型（雨/雪/暴风/高温/低温等）分类追踪，同类不重复推送，天气变化或转好时主动通知 |
| LivingMemory 集成 | 自动从 `astrbot_plugin_livingmemory` 获取会话长期记忆，LLM 结合用户偏好和话题播报 |
| 提示词缓存优化 | 针对 DeepSeek V4 前缀缓存机制设计，静态前缀（人格 + 工具定义 + 固定 motivation）保证首轮 API 调用 100% 缓存命中，节省约 90% 费用 |
| 面板配置 | 10 项可调参数通过 AstrBot 控制面板直接管理，即时生效 |
| 自然语言控制 | 用户无需记命令，直接用自然语言设置城市、间隔、开关推送 |

### Agent 工具列表

插件向 LLM 注册了 6 个工具函数，LLM 可根据用户意图自动调用：

| 工具名 | 功能 | 触发场景示例 |
|--------|------|-------------|
| `get_weather` | 查询指定城市实时天气 + 3 天预报 | "今天天气怎么样"、"广州热不热" |
| `set_weather_city` | 设置当前会话默认城市 | "以后默认查上海"、"把城市改成深圳" |
| `set_weather_interval` | 设置推送间隔（分钟），激活定时推送 | "每 30 分钟推送一次"、"每小时提醒我天气" |
| `enable_weather_push` | 激活定时推送 | "开启天气推送"、"帮我开启天气提醒" |
| `disable_weather_push` | 停止定时推送 | "关闭推送"、"取消天气提醒" |
| `set_weather_alert_only` | 设置特殊天气过滤模式 | "仅推送特殊天气"、"每天只看一次天气" |

### 特殊天气类型

插件匹配以下关键词判断是否属于特殊天气，同时检测极端温度（>35°C 高温 / <0°C 低温）：

`雨` `雪` `暴` `雷` `雹` `霾` `雾` `沙` `尘` `台风` `飓风`

### 特殊天气去重逻辑

仅特殊天气模式下，插件按天气**类型**（而非简单的"是/否特殊"布尔值）追踪变化，实现智能去重：

```
上一轮天气类型    本轮天气类型    行为
─────────────────────────────────────────
normal          normal          跳过（无变化）
normal          雨               推送（新预警出现）
雨              雨               跳过（同类已报过）
雨              雪               推送（天气类型变化）
雨              normal           推送（天气转好，通知用户）
任意            每天首次          推送（alert_first_of_day 强制放行）
```

---

## 安装

### 前提条件

1. 已部署 [AstrBot](https://github.com/AstrBotDevs/AstrBot) >= v4.8.0
2. 已注册[和风天气](https://console.qweather.com/)账号并创建项目，获取 API Host 和 API Key
3. Python >= 3.10

### 安装步骤

```bash
# 进入 AstrBot 插件目录
cd data/plugins

# 克隆仓库
git clone https://github.com/D1ff1culTT/astrbot_plugin_weather.git

# 重启 AstrBot
```

或通过 AstrBot 面板的插件市场搜索安装（如已上架）。

### 首次配置

1. 在 AstrBot 控制面板中找到「定时天气推送」插件
2. 填写 **和风天气 API 域名**（在[控制台-设置](https://console.qweather.com/)中查看，格式如 `abc123.def.qweatherapi.com`）和 **API Key**
3. （可选）调整免打扰时段、特殊天气模式等参数
4. 重启插件或重启 AstrBot
5. 定时推送需手动在会话中输入/weather_auto <分钟数> 开启。

> **重要**：2025 年起和风天气不再使用共享 API 域名，必须填写专属 API Host，否则天气查询会失败。

---

## 配置

大部分配置项均可通过 AstrBot 控制面板调整，修改后即时生效无需重启：

### API 配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `qweather_api_host` | string | — | 和风天气 API 专属域名（**必填**） |
| `qweather_key` | string | — | 和风天气 API Key（**必填**，敏感信息，面板隐藏） |
| `request_timeout` | int | 10 | API HTTP 请求超时（秒），建议 5–15 |

### 推送策略

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `alert_only` | bool | false | 开启后仅在特殊天气时推送 |
| `alert_first_of_day` | bool | true | 每天首次推送无视天气条件始终触发（仅 `alert_only=true` 时生效） |
| `dnd_enabled` | bool | false | 启用免打扰时段 |
| `dnd_start` | string | `"22:00"` | 免打扰开始时间（HH:MM 24 小时制） |
| `dnd_end` | string | `"07:00"` | 免打扰结束时间（若小于开始时间表示跨天） |

### AI 行为

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `memory_limit` | int | 10 | 从 LivingMemory 获取的会话记忆条数 |
| `max_tool_retries` | int | 3 | LLM 工具调用最大重试次数 |

### 会话级配置

以下配置可按**单个会话**独立设置，通过 Agent 自然语言交互修改，存储在 `weather_config.json` 中，跨重启持久化：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `city` | `"北京"`（IP 自动检测） | 默认查询城市 |
| `interval` | 60 | 推送间隔（分钟） |
| `alert_only` | 继承全局 | 该会话是否仅特殊天气推送 |
| `alert_first_of_day` | 继承全局 | 该会话每天首次是否始终推送 |
| `last_weather_category` | `"normal"` | 上次推送的天气类型（用于去重） |

---

## 使用方法

### 命令列表

| 命令 | 参数 | 说明 |
|------|------|------|
| `/weather` | — | 查询当前会话默认城市的实时天气 |
| `/weather_city` | `<城市名>` | 设置当前会话默认城市（如 `/weather_city 上海`） |
| `/weather_forecast` | — | 查看 3 天天气预报 |
| `/weather_auto` | `<分钟数>` | 开启定时推送（如 `/weather_auto 60`，最小 5 分钟） |
| `/weather_alert` | — | 开启仅推送特殊天气 |
| `/weather_stop` | — | 停止当前会话的定时推送 |
| `/weather_test` | — | 立即触发一次推送（测试用，须先 `/weather_auto` 开启） |
| `/weather_status` | — | 查看插件状态：API 配置、活跃推送列表、下次推送倒计时 |



### Agent 自然语言交互

支持 NL2Tool，用户无需记忆命令格式。以下为典型对话示例：

| 用户输入 | Agent 行为 |
|----------|-----------|
| "今天广州天气怎么样" | 调用 `get_weather(location="广州")`，自然语言播报 |
| "每 30 分钟推送一次" | 调用 `set_weather_interval(minutes=30)`，激活定时推送 |
| "以后默认查上海" | 调用 `set_weather_city(city="上海")` |
| "帮我开启天气提醒" | 调用 `enable_weather_push()` |
| "别推了/取消推送" | 调用 `disable_weather_push()` |
| "只在下雨暴风的时候才提醒我" | 调用 `set_weather_alert_only(enabled=true)` |
| "我明天要出差去广州" | Agent 结合上下文调用 `get_weather(location="广州")` 并给出出行建议 |

---

## 架构

### 文件结构

```
astrbot_plugin_weather/
├── main.py                # 插件主体（Star 类 + 6 个 Agent 工具 + 天气 API 封装）
├── _conf_schema.json      # AstrBot 面板配置 Schema（10 项，含类型、默认值、提示文案）
├── metadata.yaml           # 插件元数据（名称、版本、作者、仓库地址）
├── requirements.txt        # Python 依赖（仅 aiohttp）
├── LICENSE                 # MIT License
├── README.md               # 本文件
└── .gitignore              # Git 忽略规则（排除 weather_config.json 和 .claude/）
```

### 数据流

```
用户开启推送
  │
  ▼
_schedule_next(target_id)
  │  计算距离下次推送的延迟
  │  创建 asyncio.Task
  ▼
_timer_runner(target_id, delay_s)
  │  await asyncio.sleep(delay_s)
  │  DND 时段检查 → 顺延 10 分钟
  ▼
_check_and_push(target_id)
  │  ├─ IP 自动检测城市
  │  ├─ [alert_only] 获取当前天气 → _classify_weather() → 类型去重
  │  ├─ _prepare_llm_request()      ← 人格 + provider
  │  │    └─ star_map 查找 LivingMemoryPlugin
  │  │       └─ get_session_memories(session_id, limit=N)
  │  ├─ _generate_push_response()
  │  │    ├─ 方案 1：provider.text_chat(func_tool=WeatherTool) → Agent 调用 get_weather
  │  │    │    └─ DeepSeek V4 前缀缓存：persona + tool_def + 固定 motivation = 100% 命中
  │  │    ├─ 方案 2：text_chat 回退（插件预取天气数据 → LLM 播报）
  │  │    └─ 方案 3：固定格式兜底（无 LLM，直接输出结构化天气文本）
  │  ├─ context.send_message()      ← 消息发送
  │  ├─ _save_to_history()          ← 写入 AstrBot 对话历史
  │  └─ _schedule_next()            ← 重新调度下一轮
  ▼
下一轮推送...
```

### 缓存优化策略

针对 DeepSeek V4 的前缀硬盘缓存机制（前缀 token 命中享受 ~90% 费用折扣），插件采用了以下优化：

1. **静态前缀**：`system_prompt`（人格文本）和 `func_tool`（工具定义 JSON Schema）在不同推送间完全一致 → 缓存命中
2. **固定 motivation**：首条用户消息为完全静态字符串 `"请使用 get_weather 查询天气并播报。"`，不含时间戳等动态内容 → 缓存命中
3. **记忆内容置后**：LivingMemory 记忆拼接在静态 motivation **之后**，避免动态内容破坏前缀
4. **ToolSet 实例缓存**：`WeatherTool` 的序列化结果在 `initialize()` 中创建一次后复用，保证工具定义逐字节一致
5. **人格文本缓存**：`_load_persona()` 结果按 `target_id` 缓存，避免多级回退查找导致的前缀漂移

**缓存模型：**
```
API 请求：
┌─────────────────────────────────────────┐
│ system_prompt  = 人格文本        ← HIT  │
│ tool_defs      = 工具 JSON       ← HIT  │
│ user_message   = "请使用 get_..." ← HIT  │
│ memory_context = "以下是记忆..."  ← miss │
└─────────────────────────────────────────┘
```

---

## 可选集成

### LivingMemory（长期记忆）

安装 [astrbot_plugin_livingmemory](https://github.com/lxfight-s-Astrbot-Plugins/astrbot_plugin_livingmemory) 后，天气播报将自动结合用户长期记忆，无需额外配置。

**工作原理：**
- LivingMemory 在后台监听 LLM 请求/响应，自动将用户偏好、习惯、话题提取为结构化记忆
- 天气插件每次推送前通过 `star_map` 全局注册表查找 LivingMemory 实例
- 调用 `memory_engine.get_session_memories()` 获取当前会话的记忆
- 记忆以列表形式拼接到 LLM 上下文，如：

```
以下是用户近期相关的对话记忆，请结合这些信息进行天气播报：
- 用户明天要出差去上海
- 用户偏好简短直接的回复风格
- 用户上次提到对雨天比较敏感
```

---

## 依赖

| 依赖 | 版本 | 来源 |
|------|------|------|
| Python | >= 3.10 | — |
| AstrBot | >= 4.8.0 | 框架 |
| aiohttp | >= 3.9.0 | pip（HTTP 请求） |
| pydantic | — | AstrBot 自带 |
| 和风天气 API | v7 | 免费版每日 1000 次调用 |

---

## 故障排查

| 现象 | 可能原因 | 解决 |
|------|----------|------|
| 天气查询失败 | API Host / Key 未配置或错误 | 检查面板配置，确认和风天气控制台中 API Host 正确 |
| 推送不触发 | 免打扰时段中 / 间隔未到 / alert_only 过滤 | 查看日志 `[WeatherPlugin]`，使用 `/weather_status` 检查状态 |
| 无对话上下文 | LivingMemory 未安装或记忆库为空 | 确认 LivingMemory 插件已安装并初始化完毕，多聊几句积累记忆 |
| 缓存未命中率高 | motivation 或工具定义被动态内容污染 | 检查日志，确认 `system_prompt` 和 `func_tool` 序列化结果稳定 |

---

## License

MIT
