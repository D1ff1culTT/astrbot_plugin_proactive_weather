# astrbot_plugin_weather

定时天气推送插件，基于和风天气 API，支持 Agent 工具调用、会话上下文感知、LivingMemory 记忆集成和 DeepSeek V4 缓存优化。


## AI 生成声明

> **本插件 100% 由 AI（大型语言模型）生成代码**，包括插件主体、工具定义、配置逻辑和文档。未经过专业安全审计或人工代码审查。

## 免责声明

1. **不提供任何保证**：本插件按"原样"提供，不附带任何明示或暗示的担保，包括但不限于适销性、特定用途适用性和非侵权性保证。
2. **使用风险自负**：使用者应自行承担使用本插件所带来的所有风险和责任。作者/AI 不对因使用或无法使用本插件而导致的任何直接、间接、附带、特殊或后果性损害承担责任。
3. **数据准确性**：天气数据来源于和风天气 API，数据的准确性、及时性和完整性由第三方服务商负责，本插件不对天气数据的准确性做任何保证。
4. **API 费用**：使用和风天气 API 可能产生费用，DeepSeek API 调用可能产生费用，使用者应自行了解和承担相关费用。
5. **安全风险**：插件涉及网络请求和外部 API 调用，可能存在未知的安全漏洞。API Key 等敏感信息以明文存储在本地 JSON 文件中，请确保服务器安全。

## 功能

- **定时推送**：按可配置间隔自动推送天气到私聊/群聊
- **Agent 工具调用**：LLM 主动调用 `get_weather` 获取实时天气 + 3 天预报，自然语言播报
- **IP 自动定位**：首次使用时自动检测用户城市
- **免打扰时段**：可配置静默时间窗口，避开夜间打扰
- **特殊天气模式**：仅在有雨、雪、暴风、高温等特殊天气时推送，同类型不重复提醒
- **LivingMemory 集成**：自动获取会话长期记忆，结合用户偏好和话题播报天气
- **DeepSeek V4 缓存优化**：静态前缀策略保证每次推送首轮 API 调用 100% 缓存命中
- **面板配置**：10 项可调参数，AstrBot 控制面板直接管理

## 安装

```bash
# 在 AstrBot 插件目录下
cd data/plugins
git clone https://github.com/D1ff1culTT/astrbot_plugin_weather.git
```

或通过 AstrBot 面板的插件市场安装。

## 配置

所有配置项均可通过 AstrBot 控制面板调整：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `qweather_api_host` | string | - | 和风天气 API 域名（必填） |
| `qweather_key` | string | - | 和风天气 API Key（必填） |
| `request_timeout` | int | 10 | API 请求超时（秒） |
| `dnd_enabled` | bool | false | 启用免打扰时段 |
| `dnd_start` | string | 22:00 | 免打扰开始时间 |
| `dnd_end` | string | 07:00 | 免打扰结束时间 |
| `alert_only` | bool | false | 仅特殊天气时推送 |
| `alert_first_of_day` | bool | true | 每天首次无视天气条件始终推送 |
| `memory_limit` | int | 10 | LivingMemory 记忆获取条数 |
| `max_tool_retries` | int | 3 | LLM 工具调用最大重试次数 |

> **注意**：`alert_only`、`alert_first_of_day`、推送间隔和城市可由 Agent 通过自然语言按会话覆盖。

## 使用方法

### 命令

| 命令 | 说明 |
|------|------|
| `/weather` | 查询当前会话默认城市天气 |
| `/weather_city <城市>` | 设置默认城市 |
| `/weather_forecast` | 查看 3 天预报 |
| `/weather_auto <分钟>` | 开启定时推送（最小 5 分钟） |
| `/weather_stop` | 停止定时推送 |
| `/weather_test` | 立即触发一次推送（测试用） |
| `/weather_status` | 查看插件状态和活跃推送列表 |

### Agent 自然语言

用户可直接用自然语言与 Bot 交互：

- "今天广州天气怎么样" → 查询天气
- "每 30 分钟推送一次天气" → 设置推送间隔
- "以后默认查上海的天气" → 设置默认城市
- "开启/关闭定时天气推送" → 开关推送
- "仅推送特殊天气" → 开启特殊天气模式

## 架构

```
weather_plugin/
├── main.py              # 插件主体（Star 类 + 6 个 Agent 工具）
├── _conf_schema.json     # 面板配置 Schema
├── metadata.yaml         # 插件元数据
└── requirements.txt      # 依赖
```

推送流程：`_schedule_next` → `_timer_runner` (asyncio 单次定时器) → `_check_and_push` → `_prepare_llm_request` (人格 + LivingMemory 记忆) → `_generate_push_response` (Agent 工具调用) → 发送 → 存档 → 重新调度

## 依赖

- Python >= 3.10
- astrbot >= 4.8.0
- aiohttp >= 3.9.0
- 和风天气 API (免费版每日 1000 次调用)

## 可选集成

- **[astrbot_plugin_livingmemory](https://github.com/lxfight-s-Astrbot-Plugins/astrbot_plugin_livingmemory)**：安装后天气播报将自动结合用户长期记忆中的偏好和话题，无需额外配置。


## License

MIT
