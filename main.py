import asyncio
import json
import os
import time
import traceback
from datetime import datetime

from astrbot.api import AstrBotConfig, logger
from astrbot.core.star.star import star_map
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain
from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.astr_agent_context import AstrAgentContext
from pydantic import Field
from pydantic.dataclasses import dataclass
from astrbot.core.agent.message import UserMessageSegment, TextPart, AssistantMessageSegment

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weather_config.json")
PLUGIN_INSTANCE: "WeatherPlugin | None" = None

# ═══════════════════════ 工具函数 ═══════════════════════

def _get_plugin(ctx: ContextWrapper[AstrAgentContext]):
    return getattr(ctx, "plugin_instance", None) or PLUGIN_INSTANCE

def _get_session_id(ctx: ContextWrapper[AstrAgentContext]) -> str | None:
    agent_ctx = getattr(ctx, "context", None)
    if agent_ctx is None:
        return None
    event = getattr(agent_ctx, "event", None)
    return str(event.unified_msg_origin) if event and hasattr(event, "unified_msg_origin") else None

def _fmt_weather(city: str, current: dict, forecast: list | None = None) -> str:
    parts = [
        f"城市：{city}",
        f"当前天气：{current['desc']}",
        f"当前温度：{current['temp']}°C（体感 {current['feels_like']}°C）",
        f"湿度：{current['humidity']}%",
        f"风速：{current['wind_speed']} km/h {current['wind_dir']}（{current['wind_scale']}级）",
        f"能见度：{current['visibility']} km",
        f"气压：{current['pressure']} hPa",
        f"降水量：{current['precip']} mm",
    ]
    if forecast:
        parts.append("未来三天预报：" + "；".join(
            f"{d['date']}：{d['desc_day']}，{d['low']}°C ~ {d['high']}°C" for d in forecast
        ))
    return "\n".join(parts)


# ═══════════════════════ Agent 工具 ═══════════════════════

@dataclass
class WeatherTool(FunctionTool[AstrAgentContext]):
    name: str = "get_weather"
    description: str = (
        "查询指定城市的实时天气（温度、湿度、风速、能见度、气压、降水量）和未来三天天气预报。"
        "播报要求：用当前对话人格自然口语化播报，不要使用列表或表格格式；"
        "结合天气主动给出生活建议（是否需要带伞、穿衣建议、出行提醒等）；"
        "如有未来天气预报一并提及；保持简洁，不要长篇大论。"
    )
    parameters: dict = Field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "城市名称。不传则使用当前会话默认城市；无默认城市时通过 IP 自动检测。"},
        },
        "required": [],
    })

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs):
        plugin = _get_plugin(context)
        if not plugin:
            return "天气插件未初始化，请稍后重试。"

        location = kwargs.get("location", "").strip()
        tid = _get_session_id(context)
        session_city = None
        if tid:
            cfg = plugin._ensure_target_cfg(tid)
            session_city = cfg.get("city") if cfg else None
            plugin._save_config()

        if location:
            city = location
        elif session_city and session_city != "北京":
            city = session_city
        else:
            city = await plugin._detect_city()
            if tid and cfg:
                cfg["city"] = city
                plugin._save_config()

        current = await plugin._fetch_current(city)
        if not current:
            return f"抱歉，暂时无法获取「{city}」的天气数据，请稍后重试。"
        return _fmt_weather(city, current, await plugin._fetch_forecast(city))


@dataclass
class SetCityTool(FunctionTool[AstrAgentContext]):
    name: str = "set_weather_city"
    description: str = (
        "设置当前会话的默认天气查询城市，仅影响本会话。"
        "用户说「把城市改成XX」「以后默认查XX的天气」「设置城市为XX」时必须调用。"
    )
    parameters: dict = Field(default_factory=lambda: {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "城市名称，支持国内主要城市及部分国际城市。"}},
        "required": ["city"],
    })

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs):
        plugin = _get_plugin(context)
        if not plugin:
            return "天气插件未初始化。"
        city = kwargs.get("city", "").strip()
        if not city:
            return "请指定一个有效的城市名称。"
        tid = _get_session_id(context) or "default"
        cfg = plugin._ensure_target_cfg(tid)
        old = cfg.get("city", "北京")
        cfg["city"] = city
        plugin._save_config()
        return f"已将本会话默认城市从「{old}」改为「{city}」。"


@dataclass
class SetIntervalTool(FunctionTool[AstrAgentContext]):
    name: str = "set_weather_interval"
    description: str = (
        "设置当前会话定时天气推送的间隔时间（分钟），最小 5 分钟。"
        "调用后自动激活本会话的定时推送。用户说「每X分钟推送天气」「每X小时推送一次」时必须调用。"
    )
    parameters: dict = Field(default_factory=lambda: {
        "type": "object",
        "properties": {"minutes": {"type": "integer", "description": "推送间隔，单位分钟，最小 5。"}},
        "required": ["minutes"],
    })

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs):
        plugin = _get_plugin(context)
        if not plugin:
            return "天气插件未初始化。"
        minutes = kwargs.get("minutes", 60)
        if minutes < 5:
            return "推送间隔不能小于 5 分钟，请设置更大的数值。"
        tid = _get_session_id(context) or "default"
        cfg = plugin._ensure_target_cfg(tid)
        old = cfg.get("interval", 60)
        cfg["interval"] = minutes
        cfg["last_report"] = 0
        plugin._save_config()
        plugin._schedule_next(tid)
        return f"已将「{cfg.get('city', '北京')}」的天气推送间隔从 {old} 分钟改为 {minutes} 分钟。"


@dataclass
class EnablePushTool(FunctionTool[AstrAgentContext]):
    name: str = "enable_weather_push"
    description: str = (
        "为当前会话激活定时天气推送。使用已设置的默认城市和推送间隔。"
        "用户说「开启推送」「开始推送天气」「帮我开启天气提醒」时必须调用。"
    )
    parameters: dict = Field(default_factory=lambda: {"type": "object", "properties": {}})

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs):
        plugin = _get_plugin(context)
        if not plugin:
            return "天气插件未初始化。"
        tid = _get_session_id(context) or "default"
        cfg = plugin._ensure_target_cfg(tid)
        cfg["last_report"] = 0
        plugin._save_config()
        plugin._schedule_next(tid)
        return f"已开启「{cfg.get('city', '北京')}」的定时天气推送，每 {cfg.get('interval', 60)} 分钟推送一次。"


@dataclass
class DisablePushTool(FunctionTool[AstrAgentContext]):
    name: str = "disable_weather_push"
    description: str = (
        "停止当前会话的定时天气推送。用户说「关闭推送」「停止推送」「取消天气提醒」时必须调用。"
    )
    parameters: dict = Field(default_factory=lambda: {"type": "object", "properties": {}})

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs):
        plugin = _get_plugin(context)
        if not plugin:
            return "天气插件未初始化。"
        tid = _get_session_id(context) or "default"
        if tid in plugin.config["targets"]:
            city = plugin.config["targets"][tid].get("city", "?")
            plugin._cancel_timer(tid)
            del plugin.config["targets"][tid]
            plugin._save_config()
            return f"已停止「{city}」的定时天气推送。"
        return "当前会话没有开启定时推送，无需停止。"


@dataclass
class AlertOnlyTool(FunctionTool[AstrAgentContext]):
    name: str = "set_weather_alert_only"
    description: str = (
        "设置仅在有特殊天气（雨、雪、暴风、雷、冰雹、雾霾、沙尘、台风、高温>35°C、低温<0°C）时才推送提醒。"
        "每天第一次推送不受此限制，始终会推送。"
        "用户说「仅推送特殊天气」「开启天气预警」「每天只看一次天气」时必须调用。"
    )
    parameters: dict = Field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "enabled": {"type": "boolean", "description": "true=仅特殊天气推送，false=正常定时推送"},
            "first_of_day": {"type": "boolean", "description": "仅enabled=true时生效。true=每天首次推送无视天气条件始终推送，false=严格仅特殊天气"},
        },
        "required": ["enabled"],
    })

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs):
        plugin = _get_plugin(context)
        if not plugin:
            return "天气插件未初始化。"
        enabled = kwargs.get("enabled", True)
        first_of_day = kwargs.get("first_of_day", True)
        tid = _get_session_id(context) or "default"
        cfg = plugin._ensure_target_cfg(tid)
        cfg["alert_only"] = enabled
        cfg["alert_first_of_day"] = first_of_day
        plugin._save_config()
        if enabled:
            extra = "，每天首次始终推送" if first_of_day else "，严格仅推送特殊天气"
            return f"已开启「仅特殊天气推送{extra}」，城市：{cfg.get('city', '北京')}，间隔：{cfg.get('interval', 60)} 分钟。"
        return f"已切换为「正常定时推送」模式。"



# ═══════════════════════ 插件主体 ═══════════════════════

@register("weather_plugin", "YourName", "定时天气查询与推送插件", "1.0.0")
class WeatherPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = {
            "qweather_api_host": "",
            "qweather_key": "",
            "request_timeout": 10,
            "dnd_enabled": False,
            "dnd_start": "22:00",
            "dnd_end": "07:00",
            "alert_only": False,
            "alert_first_of_day": True,
            "memory_limit": 10,
            "max_tool_retries": 3,
            "targets": {},
        }
        self._dashboard_config = config
        self._location_cache: dict[str, str] = {}
        self._tasks: dict[str, asyncio.Task] = {}  # 定时推送任务句柄
        self._dnd_logged = False
        # 缓存的 ToolSet 实例，确保每次 LLM 调用的工具定义序列化结果逐字节一致
        self._weather_tool_set: ToolSet | None = None
        # 人格文本缓存，key=target_id，避免每次推送重复执行多级回退查找
        self._persona_cache: dict[str, str] = {}

        global PLUGIN_INSTANCE
        PLUGIN_INSTANCE = self
        self.context.add_llm_tools(WeatherTool(), SetCityTool(), SetIntervalTool(), EnablePushTool(), DisablePushTool(), AlertOnlyTool())

    # ── 生命周期 ──

    async def initialize(self):
        await self._load_config()
        await self._detect_city()
        self._weather_tool_set = ToolSet([WeatherTool()])
        for tid in self.config.get("targets", {}):
            self._schedule_next(tid)
        api_ok = bool(self.config.get("qweather_api_host") and self.config.get("qweather_key"))
        logger.info(f"[WeatherPlugin] 初始化完成, API={'OK' if api_ok else '未配置'}, 推送目标={len(self.config['targets'])}")

    async def terminate(self):
        for tid in list(self._tasks):
            self._cancel_timer(tid)

    # ── 定时调度 ──

    def _schedule_next(self, target_id: str):
        """为指定会话安排下一次推送（单次定时器，发送后重新调度）。"""
        self._cancel_timer(target_id)
        cfg = self.config["targets"].get(target_id)
        if not cfg:
            return
        interval_m = cfg.get("interval", 60)
        last = cfg.get("last_report", 0)
        elapsed = time.time() - last
        delay_s = max(1, interval_m * 60 - elapsed)
        self._tasks[target_id] = asyncio.create_task(self._timer_runner(target_id, delay_s))

    def _cancel_timer(self, target_id: str):
        task = self._tasks.pop(target_id, None)
        if task:
            task.cancel()

    async def _timer_runner(self, target_id: str, delay_s: float):
        """等待 delay_s 秒后检查是否应触发推送，DND 期间顺延。"""
        try:
            await asyncio.sleep(delay_s)
        except asyncio.CancelledError:
            return

        if self.config.get("dnd_enabled") and self._is_in_dnd(self.config["dnd_start"], self.config["dnd_end"]):
            if not self._dnd_logged:
                logger.info(f"[WeatherPlugin] 免打扰时段 ({self.config['dnd_start']}-{self.config['dnd_end']})，推送顺延 10 分钟")
                self._dnd_logged = True
            self._tasks[target_id] = asyncio.create_task(self._timer_runner(target_id, 600))
            return
        self._dnd_logged = False

        cfg = self.config["targets"].get(target_id)
        if not cfg:
            return
        logger.info(f"[WeatherPlugin] 定时推送触发: target={target_id}, city={cfg.get('city')}")
        await self._check_and_push(target_id)

    # ── 单次推送流程（参考 proactive_chat 的 check_and_chat）──

    async def _check_and_push(self, target_id: str):
        """一次完整的定时推送流程：IP检测 → 特殊天气过滤 → LLM → 发送 → 存档 → 重调度。"""
        cfg = self.config["targets"].get(target_id)
        if not cfg:
            return
        city = cfg.get("city", "北京")

        # IP 检测
        detected = await self._detect_city()
        if detected != city:
            cfg["city"] = detected
            city = detected
            self._save_config()

        # 仅特殊天气模式：基于天气类型变化去重，避免重复推送相同天气
        if cfg.get("alert_only", False):
            current = await self._fetch_current(city)
            if current:
                now_cat = self._classify_weather(current)
                last_cat = cfg.get("last_weather_category", "normal")

                # 每天首次推送：无视类别比较，始终推送
                first_of_day = cfg.get("alert_first_of_day", True)
                last_ts = cfg.get("last_report", 0)
                is_first_today = not last_ts or (
                    datetime.fromtimestamp(last_ts).date() != datetime.now().date()
                )
                if first_of_day and is_first_today:
                    pass  # 每天首次始终放行
                elif now_cat == last_cat:
                    reason = "仍为特殊天气" if now_cat != "normal" else "仍为正常天气"
                    logger.info(f"[WeatherPlugin] {city} 天气类型未变（{reason}: {now_cat}），跳过推送")
                    cfg["last_report"] = time.time()
                    self._save_config()
                    self._schedule_next(target_id)
                    return

                cfg["last_weather_category"] = now_cat

        try:
            request = await self._prepare_llm_request(target_id)
            user_prompt = None
            if request is None:
                response_text = f"自动推送：获取 {city} 天气失败，请稍后重试"
            else:
                response_text, user_prompt = await self._generate_push_response(request, city)
                if not response_text:
                    response_text = f"自动推送：获取 {city} 天气失败，请稍后重试"
                    user_prompt = None
        except Exception as e:
            logger.error(f"[WeatherPlugin] 推送异常: {e}\n{traceback.format_exc()}")
            response_text = f"自动推送：获取 {city} 天气失败，请稍后重试"
            user_prompt = None

        await self._send_to_target(target_id, response_text)

        # 存档到对话历史
        if request and user_prompt:
            try:
                await self._save_to_history(
                    request["conv_id"],
                    user_prompt,
                    response_text,
                )
            except Exception:
                pass

        # 更新推送时间并重新调度
        cfg["last_report"] = time.time()
        self._save_config()
        self._schedule_next(target_id)

    async def _prepare_llm_request(self, target_id: str) -> dict | None:
        """准备 LLM 所需的上下文、人格和对话 ID（参考 proactive_chat 的 _prepare_llm_request）。"""
        conv_mgr = getattr(self.context, "conversation_manager", None)
        if conv_mgr is None:
            return None
        try:
            conv_id = await conv_mgr.get_curr_conversation_id(target_id)
            if not conv_id:
                platform_id = target_id.split(":", 1)[0] if ":" in target_id else target_id
                conv_id = await conv_mgr.new_conversation(target_id, platform_id=platform_id)
        except Exception:
            return None

        # 尝试从 livingmemory 插件获取会话记忆作为上下文
        memory_context = ""
        try:
            for meta in star_map.values():
                if meta.star_cls and "livingmemory" in (meta.module_path or "").lower():
                    engine = getattr(getattr(meta.star_cls, "initializer", None), "memory_engine", None)
                    if engine:
                        memories = await engine.get_session_memories(
                                    target_id, limit=self.config.get("memory_limit", 10)
                                )
                        if memories:
                            lines = ["\n以下是用户近期相关的对话记忆，请结合这些信息进行天气播报："]
                            for m in memories:
                                text = m.get("text", "") or m.get("content", "")
                                if text:
                                    lines.append(f"- {text}")
                            memory_context = "\n".join(lines)
                            logger.info(f"[WeatherPlugin] 从 livingmemory 获取到 {len(memories)} 条记忆")
                        else:
                            logger.info(f"[WeatherPlugin] livingmemory 无此会话记忆: {target_id}")
                    else:
                        logger.info("[WeatherPlugin] livingmemory memory_engine 为 None，可能尚未初始化完毕")
                    break
            else:
                names = [m.name or m.module_path or "?" for m in star_map.values()]
                logger.info(f"[WeatherPlugin] star_map 中未找到 livingmemory，已有插件: {names}")
        except Exception as e:
            logger.info(f"[WeatherPlugin] livingmemory 接入异常: {e}")

        # 获取人格
        conv = await conv_mgr.get_conversation(target_id, conv_id)
        persona = await self._load_persona(target_id, conv)

        # 获取 provider
        provider = None
        if hasattr(self.context, "get_using_provider"):
            provider = self.context.get_using_provider(umo=target_id)

        return {"conv_id": conv_id, "persona": persona, "provider": provider, "memory_context": memory_context}

    async def _generate_push_response(self, request: dict, city: str) -> tuple[str | None, str | None]:
        """返回 (response_text, user_prompt)。user_prompt 用于存档到对话历史。"""
        provider = request["provider"]
        persona = request["persona"]

        # 方案 1：Agent 工具调用
        if provider:
            try:
                motivation = "请使用 get_weather 查询天气并播报。"
                memory_context = request.get("memory_context", "")
                content = motivation + "\n" + memory_context if memory_context else motivation
                messages = [{"role": "user", "content": content}]
                tool_set = self._weather_tool_set or ToolSet([WeatherTool()])

                for _ in range(self.config.get("max_tool_retries", 3)):
                    resp = await provider.text_chat(contexts=messages, system_prompt=persona, func_tool=tool_set)
                    if resp is None:
                        break
                    if resp.tools_call_name:
                        assistant_msg: dict = {"role": "assistant", "content": resp.completion_text or ""}
                        tc_block = []
                        ids = resp.tools_call_ids or [f"call_{i}" for i in range(len(resp.tools_call_name))]
                        for i, (name, args) in enumerate(zip(resp.tools_call_name, resp.tools_call_args)):
                            tc_block.append({"id": ids[i], "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}})
                        assistant_msg["tool_calls"] = tc_block
                        messages.append(assistant_msg)
                        for i, (name, args) in enumerate(zip(resp.tools_call_name, resp.tools_call_args)):
                            result = await self._run_push_tool(name, args)
                            messages.append({"role": "tool", "tool_call_id": ids[i], "content": result})
                    elif resp.completion_text:
                        return resp.completion_text, content
                    else:
                        break
            except Exception as e:
                logger.warning(f"[WeatherPlugin] 工具调用模式失败: {e}")

        # 方案 2：text_chat 回退（插件获取天气 → 直接播报）
        if provider:
            try:
                current = await self._fetch_current(city)
                if current:
                    data_text = _fmt_weather(city, current, await self._fetch_forecast(city))
                    fallback_prompt = f"天气数据：\n{data_text}"
                    messages = [{"role": "user", "content": fallback_prompt}]
                    resp = await provider.text_chat(contexts=messages, system_prompt=persona)
                    if resp and resp.completion_text:
                        return resp.completion_text, fallback_prompt
            except Exception as e:
                logger.warning(f"[WeatherPlugin] text_chat 回退失败: {e}")

        # 方案 3：固定格式
        current = await self._fetch_current(city)
        if current:
            return _fmt_weather(city, current), None
        return None, None

    async def _run_push_tool(self, name: str, args: dict) -> str:
        if name != "get_weather":
            return f"未知工具: {name}"
        city = args.get("location", "").strip() or await self._detect_city()
        current = await self._fetch_current(city)
        if not current:
            return f"抱歉，暂时无法获取「{city}」的天气数据。"
        return _fmt_weather(city, current, await self._fetch_forecast(city))

    # ── 对话历史 ──

    async def _save_to_history(self, conv_id: str, prompt: str, response: str):
        conv_mgr = getattr(self.context, "conversation_manager", None)
        if conv_mgr is None:
            return
        try:
            await conv_mgr.add_message_pair(
                conv_id,
                UserMessageSegment(content=[TextPart(text=prompt)]),
                AssistantMessageSegment(content=[TextPart(text=response)]),
            )
        except Exception:
            pass

    async def _load_persona(self, target_id: str, conv=None) -> str:
        # 人格文本作为 system_prompt 前缀使用，缓存确保每次推送逐字节一致
        if target_id in self._persona_cache:
            return self._persona_cache[target_id]

        pm = getattr(self.context, "persona_manager", None)
        if pm is None:
            return ""

        result = ""

        def _extract(obj) -> str | None:
            for attr in ("prompt", "system_prompt", "persona", "prompt_text", "content"):
                val = getattr(obj, attr, None)
                if val and str(val).strip():
                    return str(val).strip()
            return None

        # 会话人格
        if conv and getattr(conv, "persona_id", None):
            try:
                for getter in ("get_persona_v3_by_id", "get_persona"):
                    fn = getattr(pm, getter, None)
                    if callable(fn):
                        data = fn(conv.persona_id)
                        p = _extract(data) if data else None
                        if p:
                            result = p
            except Exception:
                pass

        # 默认人格（回退）
        if not result:
            try:
                resolve = getattr(pm, "resolve_selected_persona", None)
                if callable(resolve):
                    pid = resolve()
                    if pid:
                        for getter in ("get_persona_v3_by_id", "get_persona"):
                            fn = getattr(pm, getter, None)
                            if callable(fn):
                                p = _extract(fn(pid))
                                if p:
                                    result = p
            except Exception:
                pass

        if not result:
            for attr in ("selected_default_persona", "default_persona"):
                obj = getattr(pm, attr, None)
                if obj and not callable(obj):
                    p = _extract(obj)
                    if p:
                        result = p

        if not result:
            fn = getattr(pm, "get_default_persona_v3", None)
            if callable(fn):
                try:
                    p = _extract(fn())
                    if p:
                        result = p
                except Exception:
                    pass

        self._persona_cache[target_id] = result
        return result

    # ── 消息发送 ──

    async def _send_to_target(self, target_id: str, message: str):
        try:
            await self.context.send_message(target_id, MessageChain([Plain(message)]))
        except Exception as e:
            logger.error(f"[WeatherPlugin] 发送失败 -> {target_id}: {e}")

    # ── 天气 API ──

    # 特殊天气关键词，匹配到任一即视为需要推送
    SPECIAL_WEATHER_KEYWORDS = [
        "雨", "雪", "暴", "雷", "雹", "霾", "雾", "沙", "尘", "台风", "飓风",
    ]

    @classmethod
    def _classify_weather(cls, current: dict) -> str:
        """将天气归类为具体类型，用于去重逻辑。返回关键词、温度类型或 \"normal\"。"""
        desc = current.get("desc", "")
        for kw in cls.SPECIAL_WEATHER_KEYWORDS:
            if kw in desc:
                return kw
        try:
            temp = float(current.get("temp", 25))
            if temp > 35:
                return "高温"
            if temp < 0:
                return "低温"
        except (ValueError, TypeError):
            pass
        return "normal"

    @classmethod
    def _is_special_weather(cls, current: dict) -> bool:
        """判断当前天气是否属于需要提醒的特殊天气。"""
        return cls._classify_weather(current) != "normal"

    async def _detect_city(self) -> str:
        import aiohttp
        for url, field in [("http://ip-api.com/json/?fields=city", "city"), ("https://ipapi.co/json/", "city")]:
            try:
                timeout = aiohttp.ClientTimeout(total=3)
                async with aiohttp.ClientSession(timeout=timeout) as s:
                    async with s.get(url) as r:
                        if r.status == 200:
                            data = await r.json()
                            city = data.get(field, "")
                            if city:
                                return city
            except Exception:
                pass
        return "北京"

    @staticmethod
    def _is_in_dnd(start_str: str, end_str: str) -> bool:
        now = datetime.now().time()
        try:
            s = datetime.strptime(start_str, "%H:%M").time()
            e = datetime.strptime(end_str, "%H:%M").time()
        except Exception:
            return False
        return s <= now <= e if s <= e else now >= s or now <= e

    def _api_base(self) -> str:
        host = self.config.get("qweather_api_host", "").strip().rstrip("/")
        return f"https://{host}" if host else ""

    async def _api_get(self, url: str, params: dict) -> dict | None:
        import aiohttp
        timeout = self.config.get("request_timeout", 10)
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, params=params, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                    if r.status == 200:
                        data = json.loads(await r.text())
                        if data.get("code") == "200":
                            return data
        except Exception as e:
            logger.error(f"[WeatherPlugin] API 请求失败: {e}")
        return None

    async def _get_location_id(self, city: str) -> str | None:
        if city in self._location_cache:
            return self._location_cache[city]
        key = self.config.get("qweather_key", "")
        if not self._api_base() or not key:
            return None
        data = await self._api_get(f"{self._api_base()}/geo/v2/city/lookup", {"location": city, "key": key})
        if data:
            locations = data.get("location", [])
            if locations:
                self._location_cache[city] = locations[0]["id"]
                self._save_config()
                return self._location_cache[city]
        return None

    async def _fetch_current(self, city: str) -> dict | None:
        if not self._api_base() or not self.config.get("qweather_key"):
            return None
        loc_id = await self._get_location_id(city)
        if not loc_id:
            return None
        data = await self._api_get(f"{self._api_base()}/v7/weather/now", {"location": loc_id, "key": self.config["qweather_key"]})
        if not data:
            return None
        n = data.get("now", {})
        return {
            "temp": n.get("temp", "N/A"), "feels_like": n.get("feelsLike", "N/A"),
            "desc": n.get("text", "N/A"), "humidity": n.get("humidity", "N/A"),
            "wind_speed": n.get("windSpeed", "N/A"), "wind_dir": n.get("windDir", "N/A"),
            "wind_scale": n.get("windScale", "N/A"), "visibility": n.get("vis", "N/A"),
            "pressure": n.get("pressure", "N/A"), "precip": n.get("precip", "0.0"),
        }

    async def _fetch_forecast(self, city: str) -> list | None:
        if not self._api_base() or not self.config.get("qweather_key"):
            return None
        loc_id = await self._get_location_id(city)
        if not loc_id:
            return None
        data = await self._api_get(f"{self._api_base()}/v7/weather/3d", {"location": loc_id, "key": self.config["qweather_key"]})
        if not data:
            return None
        return [{"date": d.get("fxDate", "?"), "low": d.get("tempMin", "?"), "high": d.get("tempMax", "?"),
                 "desc_day": d.get("textDay", "?"), "desc_night": d.get("textNight", "?"),
                 "wind_dir_day": d.get("windDirDay", "?"), "wind_scale_day": d.get("windScaleDay", "?"),
                 "humidity": d.get("humidity", "?"), "precip": d.get("precip", "0.0")}
                for d in data.get("daily", [])[:3]]

    # ── 配置读写 ──

    async def _load_config(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self.config["targets"] = saved.get("targets", {})
                self._location_cache = saved.get("location_cache", {})
        except Exception:
            pass
        if self._dashboard_config:
            for key in ("qweather_api_host", "qweather_key", "request_timeout",
                        "dnd_enabled", "dnd_start", "dnd_end",
                        "alert_only", "alert_first_of_day",
                        "memory_limit", "max_tool_retries"):
                val = self._dashboard_config.get(key)
                if val is not None and val != "":
                    self.config[key] = val

    def _save_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({"targets": self.config.get("targets", {}), "location_cache": self._location_cache}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ── 工具方法 ──

    @staticmethod
    def _extract_target(event: AstrMessageEvent) -> str:
        return str(event.unified_msg_origin) if hasattr(event, "unified_msg_origin") else \
            event.get_session_id() if hasattr(event, "get_session_id") else "default"

    @staticmethod
    def _format_time(ts: float | None) -> str:
        return "暂无记录" if (ts is None or ts == 0) else datetime.fromtimestamp(ts).strftime("%H:%M:%S")

    def _ensure_target_cfg(self, target_id: str) -> dict:
        if target_id not in self.config["targets"]:
            if target_id.count(":") < 2:
                return {}
            self.config["targets"][target_id] = {
                "city": "北京",
                "interval": 60,
                "last_report": time.time(),
                "alert_only": self.config.get("alert_only", False),
                "alert_first_of_day": self.config.get("alert_first_of_day", True),
            }
        return self.config["targets"][target_id]

    # ── 格式化输出（/weather 命令用）──

    async def _build_weather(self, city: str) -> str | None:
        c = await self._fetch_current(city)
        return (_fmt_weather(city, c) + "\n数据源: 和风天气") if c else None

    async def _build_forecast(self, city: str) -> str | None:
        days = await self._fetch_forecast(city)
        if not days:
            return None
        lines = [f"{city} 未来三天预报："] + [f"  {d['date']}  {d['desc_day']}  {d['low']}C ~ {d['high']}C" for d in days]
        lines.append("数据源: 和风天气")
        return "\n".join(lines)

    # ── 命令 ──

    @filter.command("weather")
    async def cmd_weather(self, event: AstrMessageEvent):
        tid = self._extract_target(event)
        cfg = self._ensure_target_cfg(tid)
        city = cfg.get("city", "北京")
        self._save_config()
        msg = await self._build_weather(city)
        yield event.plain_result(msg or f"获取「{city}」天气失败。请检查 API 配置。")

    @filter.command("weather_city")
    async def cmd_weather_city(self, event: AstrMessageEvent):
        city = event.message_str.strip()
        for p in ("/weather_city", "weather_city"):
            city = city.replace(p, "", 1).strip()
        if not city:
            yield event.plain_result("用法：/weather_city <城市名>\n例如：/weather_city 上海")
            return
        tid = self._extract_target(event)
        self._ensure_target_cfg(tid)["city"] = city
        self._save_config()
        yield event.plain_result(f"已将本会话默认城市设置为：{city}")

    @filter.command("weather_forecast")
    async def cmd_weather_forecast(self, event: AstrMessageEvent):
        tid = self._extract_target(event)
        city = self.config["targets"].get(tid, {}).get("city", "北京")
        msg = await self._build_forecast(city)
        yield event.plain_result(msg or f"获取「{city}」预报失败。请检查 API 配置。")

    @filter.command("weather_auto")
    async def cmd_weather_auto(self, event: AstrMessageEvent):
        arg = event.message_str.strip()
        for p in ("/weather_auto", "weather_auto"):
            arg = arg.replace(p, "", 1).strip()
        try:
            minutes = int(arg) if arg else 60
        except ValueError:
            yield event.plain_result("用法：/weather_auto <分钟数>\n例如：/weather_auto 60")
            return
        if minutes < 5:
            yield event.plain_result("间隔不能小于 5 分钟。")
            return
        tid = self._extract_target(event)
        cfg = self._ensure_target_cfg(tid)
        cfg["interval"] = minutes
        cfg["last_report"] = 0
        self._save_config()
        self._schedule_next(tid)
        yield event.plain_result(f"已开启定时天气推送！\n城市：{cfg.get('city', '北京')}\n间隔：每 {minutes} 分钟\n发送 /weather_stop 可停止。")

    @filter.command("weather_alert")
    async def cmd_weather_alert(self, event: AstrMessageEvent):
        arg = event.message_str.strip()
        for p in ("/weather_alert", "weather_alert"):
            arg = arg.replace(p, "", 1).strip()
        # /weather_alert off → 关闭；/weather_alert strict → 严格仅特殊天气；其他 → 开启（含每天首次）
        if arg.lower() in ("off", "false", "0", "关", "停"):
            enabled, first_of_day = False, True
        elif arg.lower() in ("strict", "严格"):
            enabled, first_of_day = True, False
        else:
            enabled, first_of_day = True, True
        tid = self._extract_target(event)
        cfg = self._ensure_target_cfg(tid)
        cfg["alert_only"] = enabled
        cfg["alert_first_of_day"] = first_of_day
        self._save_config()
        if not enabled:
            yield event.plain_result("已切换为「正常定时推送」模式。")
        elif first_of_day:
            yield event.plain_result("已开启「仅特殊天气推送」，每天首次始终推送。\n特殊天气：雨、雪、暴风、雷、冰雹、雾霾、沙尘、台风、高温>35°C、低温<0°C。\n发送 /weather_alert strict 可关闭每日首次推送。")
        else:
            yield event.plain_result("已开启「严格仅特殊天气推送」（含每日首次也不推送）。\n发送 /weather_alert 可恢复每天首次推送。")

    @filter.command("weather_stop")
    async def cmd_weather_stop(self, event: AstrMessageEvent):
        tid = self._extract_target(event)
        if tid in self.config["targets"]:
            self._cancel_timer(tid)
            del self.config["targets"][tid]
            self._save_config()
            yield event.plain_result("已停止本会话的定时天气推送。")
        else:
            yield event.plain_result("本会话未开启定时推送，无需停止。")

    @filter.command("weather_test")
    async def cmd_weather_test(self, event: AstrMessageEvent):
        tid = self._extract_target(event)
        if tid not in self.config["targets"]:
            yield event.plain_result("本会话未开启定时推送，请先用 /weather_auto 开启。")
            return
        await self._check_and_push(tid)

    @filter.command("weather_status")
    async def cmd_weather_status(self, event: AstrMessageEvent):
        tid = self._extract_target(event)
        cfg = self.config["targets"].get(tid, {})
        city = cfg.get("city", "北京")
        interval = cfg.get("interval", 60)
        is_active = tid in self.config["targets"]
        now = time.time()

        lines = [
            "天气插件状态",
            f"数据源：和风天气",
            f"API 域名：{'已配置' if self._api_base() else '(未配置)'}",
            f"API Key：{'已配置' if self.config.get('qweather_key') else '(未配置)'}",
            f"城市：{city}",
            f"本会话推送：{'已激活' if is_active else '未激活'}",
        ]
        if is_active:
            lines.append(f"推送间隔：每 {interval} 分钟")
            alert_only = cfg.get("alert_only", False)
            first_of_day = cfg.get("alert_first_of_day", True)
            if alert_only:
                mode = "仅特殊天气（每天首次始终推送）" if first_of_day else "仅特殊天气（严格模式）"
            else:
                mode = "正常推送"
            lines.append(f"推送模式：{mode}")
            last = cfg.get("last_report", 0)
            lines.append(f"上次推送：{self._format_time(last)}")
            if last > 0:
                remaining = max(0, interval * 60 - (now - last)) / 60
                lines.append(f"下次推送：约 {remaining:.1f} 分钟后")
            else:
                lines.append(f"下次推送：首次将在 {interval} 分钟后触发")

        all_targets = self.config.get("targets", {})
        if all_targets:
            lines.append("\n所有活跃推送目标：")
            for t, c in all_targets.items():
                rem = max(0, c.get("interval", 60) * 60 - (now - c.get("last_report", 0))) / 60
                marker = " <- 当前" if t == tid else ""
                lines.append(f"  {c.get('city', '?')} | 间隔{c.get('interval', 60)}min | "
                           f"上次:{self._format_time(c.get('last_report', 0))} | 剩余:{rem:.1f}min{marker}")

        lines.extend(["", "Agent 自然语言：",
                       "  「今天广州天气怎么样」  — 查询天气",
                       "  「每30分钟推送一次天气」   — 设置间隔",
                       "  「开启/关闭定时天气推送」  — 开关推送",
                       "", "命令：/weather /weather_city /weather_forecast /weather_auto /weather_alert /weather_stop /weather_status /weather_test"])
        yield event.plain_result("\n".join(lines))
