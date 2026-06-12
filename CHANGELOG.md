# 更新日志

本文件记录「定时天气推送」插件的所有重要变更。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [v1.0.1] — 2026-06-12

### 修复

- **面板关闭「仅特殊天气推送」不生效**：`_ensure_target_cfg` 在创建会话时硬拷贝全局 `alert_only`，拷贝后两者独立，面板修改无法同步到已有会话。
- **指令无法关闭特殊天气推送**：`_ensure_target_cfg` 对 `target_id` 包含少于 2 个 `:` 的会话提前返回空 `dict`，后续修改被静默丢弃。
- **DND 免打扰面板热更新不生效**：`_timer_runner` 从缓存的 `self.config` 读取，面板修改需重启才生效。

### 改进

- 新增 `_get_cfg(key, default)` 方法：优先从 `_dashboard_config` 读取面板实时值，回退到 `self.config`，确保面板修改即时对所有会话生效。
- 配置回退链：`会话显式设置（指令 / Agent Tool） → 面板实时配置 → 代码默认值`。
- `_ensure_target_cfg` 不再硬拷贝 `alert_only` / `alert_first_of_day` 到新建会话，会话仅在通过指令或 Agent Tool 显式覆盖时才存储这两个字段。
- `/weather_alert` 命令行为优化：
  - **无参数 = toggle**：当前开着就关，关着就开
  - 新增 `on` 显式开启、`off` 显式关闭（与 Toggle 并列）
  - 参数错误时显示用法帮助而非静默开启

### 变更文件

| 文件 | 变更 |
|------|------|
| `main.py` | 新增 `_get_cfg()`；修改 `_ensure_target_cfg`、`_check_and_push`、`_timer_runner`、`cmd_weather_alert`、`cmd_weather_status` |
| `README.md` | 更新命令表、会话级配置说明、故障排查表 |

---

## [v1.0.0] — 2026-05-28

### 新增

- 首个正式版本发布。

#### 核心功能

- 基于 cron 表达式的定时天气推送，间隔可配置（最小 5 分钟）。
- 和风天气 API v7 集成：实时天气（温度 / 体感温度 / 湿度 / 风速 / 能见度 / 气压 / 降水量）+ 未来 3 天预报。
- **Agent Tool Calling**：向 LLM 注册 6 个工具函数，用户用自然语言即可控制所有功能。
- **特殊天气智能去重**：按天气类型（雨 / 雪 / 暴风 / 雷 / 冰雹 / 雾霾 / 沙尘 / 台风 / 高温 >35°C / 低温 <0°C）分类追踪，同类天气不重复推送，天气转好时主动通知。
- **免打扰时段**：可配置静默窗口（如 22:00–07:00），跨天支持，触发后自动顺延 10 分钟重试。
- **LivingMemory 集成**：自动获取会话长期记忆，LLM 结合用户偏好和上下文播报天气。
- **IP 自动定位**：首次使用时自动检测城市（ip-api → ipapi.co 双源回退）。
- **DeepSeek V4 前缀缓存优化**：静态前缀（人格 + ToolSet 定义 + 固定 motivation）保证 API 调用 100% 缓存命中。

#### 面板配置（10 项）

`qweather_api_host` · `qweather_key` · `request_timeout` · `dnd_enabled` · `dnd_start` · `dnd_end` · `alert_only` · `alert_first_of_day` · `memory_limit` · `max_tool_retries`

#### 命令

`/weather` · `/weather_city` · `/weather_forecast` · `/weather_auto` · `/weather_alert` · `/weather_stop` · `/weather_test` · `/weather_status`

#### Agent 工具

`get_weather` · `set_weather_city` · `set_weather_interval` · `enable_weather_push` · `disable_weather_push` · `set_weather_alert_only`

---

## 版本号说明

| 递增规则 | 适用场景 |
|----------|---------|
| MAJOR（主版本号） | 不兼容的 API 变更、架构重构 |
| MINOR（次版本号） | 向下兼容的功能新增 |
| PATCH（修订号） | 向下兼容的 bug 修复 |

---

[v1.0.1]: https://github.com/D1ff1culTT/astrbot_plugin_proactive_weather/compare/v1.0.0...v1.0.1
[v1.0.0]: https://github.com/D1ff1culTT/astrbot_plugin_proactive_weather/releases/tag/v1.0.0
