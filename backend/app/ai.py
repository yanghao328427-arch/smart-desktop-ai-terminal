from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import re
from typing import Any
from xml.etree import ElementTree

from .actions import compact_utf8_text
from .config import Settings
from .schemas import ActionSpec, DeviceSnapshot, DialogueTurn


@dataclass
class ChatPlan:
    reply: str
    speech: str
    actions: list[ActionSpec]


@dataclass
class NewsItem:
    title: str
    link: str
    summary: str
    published: str
    source: str


SPEECH_MAX_BYTES = 90
NEWS_RSS_FEEDS = [
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("BBC Top Stories", "https://feeds.bbci.co.uk/news/rss.xml"),
]


def chat_plan_from_local_reply(reply: str, oled: str, tool_actions: list[ActionSpec]) -> ChatPlan:
    speech = speech_text(reply)
    actions = [
        ActionSpec(type="oled_display", payload={"text": oled}),
        *tool_actions,
        ActionSpec(type="tts_speak", payload={"text": speech}),
    ]
    return ChatPlan(reply=reply, speech=speech, actions=actions)


class MockAIClient:
    async def plan(self, text: str, device: DeviceSnapshot) -> ChatPlan:
        reply, oled, tool_actions = plan_local_reply(text, device)
        return chat_plan_from_local_reply(reply, oled, tool_actions)


class DashScopeOpenAIClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.fallback = MockAIClient()

    async def plan(self, text: str, device: DeviceSnapshot) -> ChatPlan:
        local_reply, local_oled, local_tool_actions = plan_local_reply(text, device)
        if local_tool_actions:
            return chat_plan_from_local_reply(local_reply, local_oled, local_tool_actions)

        try:
            import httpx

            news_context = await fetch_news_context() if is_news_query(text) else None
            url = self.settings.ai_base_url.rstrip("/") + "/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.settings.dashscope_api_key}",
                "Content-Type": "application/json",
            }
            messages = [
                {
                    "role": "system",
                    "content": build_system_prompt(device, has_news_context=bool(news_context)),
                },
                *conversation_messages(device),
            ]
            if news_context:
                messages.append({"role": "system", "content": news_context})
            messages.append({"role": "user", "content": text})

            payload = {
                "model": self.settings.ai_model,
                "messages": messages,
                "temperature": 0.75 if news_context else 0.7,
                "max_tokens": 1800,
            }
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
            reply, speech = parse_cloud_reply(data["choices"][0]["message"]["content"])
            actions = [
                ActionSpec(type="oled_display", payload={"text": local_oled}),
                *local_tool_actions,
                ActionSpec(type="tts_speak", payload={"text": speech}),
            ]
            return ChatPlan(reply=reply, speech=speech, actions=actions)
        except Exception:
            fallback = await self.fallback.plan(text, device)
            fallback.reply = f"{fallback.reply}（云端暂不可用，已使用本地规则。）"
            fallback.actions = [
                action if action.type != "tts_speak" else ActionSpec(type="tts_speak", payload={"text": fallback.speech})
                for action in fallback.actions
            ]
            return fallback


def get_ai_client(settings: Settings) -> MockAIClient | DashScopeOpenAIClient:
    provider = settings.ai_provider.lower()
    if provider == "dashscope_openai" and settings.dashscope_api_key:
        return DashScopeOpenAIClient(settings)
    return MockAIClient()


def compact_input(text: str) -> str:
    normalized = text.strip().lower()
    return "".join(ch for ch in normalized if ch not in " \t\r\n，。！？；：、,.!?;:'\"")


def recent_dialogue(device: DeviceSnapshot) -> list[DialogueTurn]:
    return [turn for turn in device.recent_dialogue if turn.role in {"user", "assistant"}][-8:]


def conversation_messages(device: DeviceSnapshot) -> list[dict[str, str]]:
    return [{"role": turn.role, "content": turn.text} for turn in recent_dialogue(device)]


def sensor_number(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def is_news_query(text: str) -> bool:
    compact = compact_input(text)
    news_terms = [
        "新闻",
        "世界新闻",
        "国际新闻",
        "今天新闻",
        "今日新闻",
        "最近新闻",
        "时事",
        "热点",
        "头条",
        "worldnews",
        "news",
    ]
    return any(term in compact for term in news_terms)


def xml_text(element: ElementTree.Element, tag: str) -> str:
    child = element.find(tag)
    if child is None or child.text is None:
        return ""
    return normalize_model_text(child.text)


def parse_rss_items(xml_text_value: str, source: str, limit: int = 5) -> list[NewsItem]:
    root = ElementTree.fromstring(xml_text_value)
    items: list[NewsItem] = []
    for item in root.findall(".//item"):
        title = xml_text(item, "title")
        if not title:
            continue
        items.append(
            NewsItem(
                title=title,
                link=xml_text(item, "link"),
                summary=xml_text(item, "description"),
                published=xml_text(item, "pubDate"),
                source=source,
            )
        )
        if len(items) >= limit:
            break
    return items


def format_news_context(items: list[NewsItem]) -> str:
    fetched_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    if not items:
        return (
            "新闻检索结果：当前没有成功获取到公开新闻条目。"
            "如果用户询问实时新闻，请明确说明后端新闻源暂时不可用，不要编造新闻。"
        )

    lines = [
        "新闻检索结果：以下条目来自公开 RSS 新闻源，可能存在数分钟到数小时延迟。",
        f"抓取时间：{fetched_at}。",
        "回答新闻问题时只能基于这些条目概括，不要编造未出现的事实；可以提醒用户这是简要新闻摘要。",
    ]
    for index, item in enumerate(items, start=1):
        detail = f"{index}. [{item.source}] {item.title}"
        if item.published:
            detail += f"；发布时间：{item.published}"
        if item.summary:
            detail += f"；摘要：{item.summary}"
        if item.link:
            detail += f"；链接：{item.link}"
        lines.append(detail)
    return "\n".join(lines)


async def fetch_news_context(limit: int = 6) -> str:
    import httpx

    headers = {"User-Agent": "SmartDesktopAITerminal/1.0"}
    items: list[NewsItem] = []
    async with httpx.AsyncClient(timeout=8, follow_redirects=True, headers=headers) as client:
        for source, url in NEWS_RSS_FEEDS:
            if len(items) >= limit:
                break
            try:
                response = await client.get(url)
                response.raise_for_status()
                items.extend(parse_rss_items(response.text, source, limit=limit - len(items)))
            except Exception:
                continue
    return format_news_context(items[:limit])


def normalize_model_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def json_candidates(raw_text: str) -> list[str]:
    text = raw_text.strip()
    if not text:
        return []

    candidates = [text]
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        candidates.append(fence.group(1).strip())

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1].strip())

    unique: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in unique:
            unique.append(candidate)
    return unique


def sentence_chunks(text: str) -> list[str]:
    parts = re.split(r"([。！？!?；;])", normalize_model_text(text))
    chunks: list[str] = []
    for index in range(0, len(parts), 2):
        sentence = parts[index].strip()
        if not sentence:
            continue
        punctuation = parts[index + 1] if index + 1 < len(parts) else ""
        chunks.append(f"{sentence}{punctuation}".strip())
    return chunks


def speech_text(reply: str, preferred: str | None = None, max_bytes: int = SPEECH_MAX_BYTES) -> str:
    preferred_text = normalize_model_text(preferred)
    if preferred_text:
        return compact_utf8_text(preferred_text, max_bytes) or "我在。"

    collected = ""
    for chunk in sentence_chunks(reply):
        proposal = f"{collected}{chunk}"
        if compact_utf8_text(proposal, max_bytes) != proposal:
            break
        collected = proposal

    if collected:
        return collected

    fallback = compact_utf8_text(normalize_model_text(reply), max_bytes)
    return fallback or "我在。"


def parse_cloud_reply(raw_text: str) -> tuple[str, str]:
    for candidate in json_candidates(raw_text):
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue

        reply = normalize_model_text(payload.get("reply"))
        if reply:
            return reply, speech_text(reply, normalize_model_text(payload.get("speech")))

    reply = normalize_model_text(raw_text)
    return reply or "我在。", speech_text(reply)


def sensor_phrase(device: DeviceSnapshot) -> str:
    sensors = device.sensors or {}
    parts: list[str] = []

    temperature = sensor_number(sensors.get("temperature_c"))
    humidity = sensor_number(sensors.get("humidity_pct"))
    pot_raw = sensors.get("pot_raw")
    pot_pct = sensors.get("pot_pct")
    ntc_raw = sensors.get("ntc_raw")
    ntc_pct = sensors.get("ntc_pct")
    tracking_signal = sensors.get("tracking_signal")
    distance_zone = sensors.get("distance_zone")
    env_state = sensors.get("env_state")
    interaction_hint = sensors.get("interaction_hint")
    rgb_status = sensors.get("rgb_status")
    rgb_reason = sensors.get("rgb_reason")
    encoder_position = sensors.get("encoder_position")
    encoder_delta = sensors.get("encoder_delta")
    distance_ok = sensors.get("distance_ok") is True
    distance = sensor_number(sensors.get("distance_cm"))

    if sensors.get("aht20_ok") is True and temperature is not None and humidity is not None:
        parts.append(f"温度 {temperature:.1f} 度，湿度 {humidity:.1f}%。")
    elif sensors.get("aht20_ok") is False:
        parts.append("温湿度暂时还没读到有效值。")

    if distance_ok and distance is not None:
        parts.append(f"距离约 {distance:.1f} 厘米。")
    elif sensors.get("distance_enabled") is False:
        parts.append("超声波测距当前未启用。")
    elif "distance_ok" in sensors:
        parts.append("距离数据暂时不可用。")

    if pot_raw is not None:
        suffix = f"，约 {pot_pct}%" if pot_pct is not None else ""
        parts.append(f"电位器原始值是 {pot_raw}{suffix}。")
    if ntc_raw is not None:
        suffix = f"，约 {ntc_pct}%" if ntc_pct is not None else ""
        parts.append(f"NTC 原始值是 {ntc_raw}{suffix}。")
    if tracking_signal is not None:
        parts.append(f"循迹信号是{'高电平' if tracking_signal else '低电平'}。")
    if env_state:
        parts.append(f"环境状态标记为 {env_state}。")
    if distance_zone:
        parts.append(f"距离区间标记为 {distance_zone}。")
    if interaction_hint:
        parts.append(f"当前交互提示是 {interaction_hint}。")
    if rgb_status:
        detail = f"，原因 {rgb_reason}" if rgb_reason else ""
        parts.append(f"RGB 状态灯是 {rgb_status}{detail}。")
    if encoder_position is not None:
        parts.append(f"旋转编码器位置是 {encoder_position}，本次增量是 {encoder_delta or 0}。")

    return "".join(parts)


def device_status_phrase(device: DeviceSnapshot) -> str:
    parts = [
        "当前设备" + ("在线" if device.online else "离线") + "。",
        "实时会话" + ("已连接" if device.session_connected else "未连接") + "。",
        "串口链路" + ("正常" if device.uart_ok else "待确认") + "。",
    ]
    if device.mode:
        parts.append(f"当前模式是 {device.mode.value}。")
    if device.current_user:
        parts.append(f"当前用户是 {device.current_user.name}。")
        if device.current_user.profile_summary:
            parts.append(f"用户上下文摘要：{device.current_user.profile_summary}。")
        if device.current_user.admin_notes:
            parts.append(f"管理员备注：{device.current_user.admin_notes}。")
    parts.append(sensor_phrase(device))
    return "".join(parts)


def build_system_prompt(device: DeviceSnapshot, *, has_news_context: bool = False) -> str:
    identity = (
        "你是部署在智能桌面对话终端里的 AI 助手。"
        "用户会把你当成住在设备里的角色，而不是网页客服。"
        "你本质上是接入云端大模型的通用智能助手，同时拥有本桌面终端的传感器上下文和硬件动作能力。"
        "回答要自然、口语化、有判断力，不要把自己局限成只会查设备状态或执行固定命令。"
        "如果用户在闲聊，就像桌面助手一样继续对话；如果用户在控制设备，就自然承接并给出结果。"
        "如果用户问复杂问题，例如新闻、科学、技术、学习规划、社会现象、方案设计、比较分析、原因推理或开放讨论，要由大模型充分回答，可以分点、举例、给出取舍和结论。"
        "简单寒暄和硬件控制保持简短；复杂问题按问题需要展开，不要为了播报而压缩网页/小程序里的完整答案。"
        "如涉及设备控制，只能说明你将执行或已准备执行，不要编造已经收到 ACK、已经播报完成或已经看到硬件结果。"
        "不要编造未提供的传感器数值、用户身份或设备状态。"
        "如果当前 RFID 用户带有上下文摘要或管理员备注，要据此理解用户偏好与任务背景，但不能牺牲事实准确性。"
        "你必须只输出一个 JSON 对象，不要输出 Markdown、代码块或额外说明。"
        'JSON 格式固定为 {"reply":"...","speech":"..."}。'
        "reply 给网页和小程序显示：短问题可以短答，复杂问题可以给较完整的中文答案，允许使用换行、编号和要点。"
        "speech 给 SYN6288 播报，必须更短，只保留一条口语短句，尽量不超过 30 个汉字。"
    )
    if has_news_context:
        identity += (
            "本轮已提供新闻检索结果。回答新闻问题时要基于检索结果做中文摘要，"
            "按重要性归纳 3 到 5 条，并说明这些是公开新闻源摘要。"
        )
    context = "当前设备上下文：" + device_status_phrase(device)
    if device.current_user:
        context += f"当前用户 ID 是 {device.current_user.user_id}。"
        if device.current_user.uid:
            context += f"当前 RFID UID 是 {device.current_user.uid}。"
    if device.last_assistant:
        context += f"上一轮你说过：{device.last_assistant}"
    return identity + context


def extract_focus_minutes(text: str) -> int:
    match = re.search(r"(\d{1,3})\s*分钟", text)
    if not match:
        return 25
    return max(1, min(180, int(match.group(1))))


def extract_fan_level(text: str) -> int:
    if any(key in text for key in ["三档", "3档", "三级", "3级", "最高"]):
        return 3
    if any(key in text for key in ["一档", "1档", "一级", "1级", "最低"]):
        return 1
    return 2


def append_action(actions: list[ActionSpec], action_type: str, payload: dict | None = None) -> None:
    payload = payload or {}
    for action in actions:
        if action.type == action_type and action.payload == payload:
            return
    actions.append(ActionSpec(type=action_type, payload=payload))


def last_user_turn(device: DeviceSnapshot) -> str | None:
    for turn in reversed(device.recent_dialogue):
        if turn.role == "user":
            return turn.text
    return None


def plan_local_reply(text: str, device: DeviceSnapshot) -> tuple[str, str, list[ActionSpec]]:
    normalized = text.strip().lower()
    compact = compact_input(text)
    mode_hint = f"当前模式是 {device.mode.value}。" if device.mode else ""
    user_hint = f"{device.current_user.name}，" if device.current_user else ""
    actions: list[ActionSpec] = []
    reply_parts: list[str] = []
    oled = "AI READY"
    heat_comfort_request = "热" in compact and any(key in compact for key in ["有点热", "太热", "很热"])
    fan_on = any(key in compact for key in ["打开风扇", "开风扇", "fanon", "风扇打开"])
    fan_off = any(key in compact for key in ["关闭风扇", "关风扇", "fanoff", "风扇关闭"])
    focus_on = any(key in compact for key in ["专注", "focus"])
    beep_on = any(key in compact for key in ["蜂鸣", "提示音", "报警"])
    music_stop = any(key in compact for key in ["停止音乐", "关闭音乐", "停音乐", "musicstop", "stop music"])
    music_on = (
        any(key in compact for key in ["播放音乐", "放音乐", "蜂鸣器音乐", "生日歌", "胜利音", "启动音", "music"])
        and not music_stop
    )
    unlock_on = any(key in compact for key in ["解锁", "unlock"])
    lock_on = ("锁定" in compact) or ("lock" in compact and "unlock" not in compact)
    volume_up = any(key in compact for key in ["音量大一点", "调大音量", "增大音量", "声音大一点", "volumeup"])
    volume_down = any(key in compact for key in ["音量小一点", "调小音量", "减小音量", "声音小一点", "volumedown"])
    volume_mute = any(key in compact for key in ["静音", "音量为零", "关闭声音", "mute"])
    volume_max = any(key in compact for key in ["最大音量", "音量最大", "声音最大"])
    volume_match = re.search(r"(?:音量|声音)(?:调到|设置为|设为|到|为)?(1[0-6]|[0-9])", compact)
    has_action_intent = any([
        heat_comfort_request, fan_on, fan_off, focus_on, beep_on, music_on, music_stop,
        unlock_on, lock_on, volume_up, volume_down, volume_mute, volume_max, volume_match,
    ])

    if any(key in compact for key in ["你是谁", "你是誰", "介绍下你自己", "自我介绍"]):
        return (
            f"我是你的智能桌面 AI 终端助手，负责把对话转换成 STM32 可以执行的动作。{mode_hint}",
            "AI TERMINAL",
            [],
        )

    if any(key in compact for key in ["你能做什么", "你会什么", "能做什么", "有哪些功能"]):
        return (
            "我可以回答状态问题、聊开放话题、摘要新闻，也可以控制风扇、蜂鸣器、锁定解锁和专注模式。",
            "AI SKILLS",
            [],
        )

    if is_news_query(text):
        return (
            "我可以帮你摘要新闻；当前本地规则没有实时新闻源，请确认云端模式和网络可用后再问我今天的新闻。",
            "NEWS READY",
            [],
        )

    if not has_action_intent and any(key in compact for key in ["你好", "嗨", "hello", "hi", "早上好", "晚上好"]):
        return (
            f"你好，{user_hint}我在。你可以直接问我状态，或者让我控制风扇、专注模式和锁定解锁。",
            "AI READY",
            [],
        )

    if any(key in compact for key in ["谢谢", "辛苦了", "谢了"]):
        return ("不客气，我会继续待命。", "AI READY", [])

    if any(key in compact for key in ["再见", "拜拜", "回头见"]):
        return ("好，随时叫我，我会继续守着这个桌面终端。", "AI READY", [])

    if any(key in compact for key in ["现在状态怎么样", "当前状态怎么样", "设备状态", "现在什么状态", "状态如何"]):
        return (
            device_status_phrase(device),
            "STATUS OK" if device.online else "STATUS OFF",
            [],
        )

    if any(key in compact for key in ["你记得我刚才说了什么", "刚才我说了什么", "还记得上一句吗"]):
        previous = last_user_turn(device)
        if previous:
            return (f"我记得你刚才说的是：{previous}。", "MEMORY", [])
        return ("这还是我们刚开始这一轮对话，我还没有更早的上一句。", "MEMORY", [])

    if any(key in compact for key in ["刚才执行了什么", "上一步做了什么", "你刚才做了什么"]):
        if device.last_assistant:
            return (f"我刚才的处理结果是：{device.last_assistant}", "LAST TASK", [])
        return ("当前还没有上一轮执行记录。", "LAST TASK", [])

    if any(key in compact for key in ["为什么", "为啥", "原因是什么"]):
        if device.last_assistant and device.last_text:
            return (f"因为你刚才说的是“{device.last_text}”，所以我按这个意图执行并反馈结果。", "WHY", [])
        return ("我会根据你的当轮输入、当前模式和设备状态来决定回答与动作。", "WHY", [])

    if any(key in compact for key in ["陪我聊聊", "聊聊天", "说说话", "无聊"]):
        return (
            "可以，我会一边陪你聊天，一边关注这个桌面的状态。你也可以直接问我现在的温湿度、模式，或者让我执行动作。",
            "CHAT MODE",
            [],
        )

    if any(key in compact for key in ["谁在登录", "谁登录了", "当前用户", "现在是谁"]):
        if device.current_user:
            summary = f"，上下文摘要是 {device.current_user.profile_summary}" if device.current_user.profile_summary else ""
            return (
                f"当前用户是 {device.current_user.name}，模式是 {device.current_user.mode.value}{summary}。",
                "USER READY",
                [],
            )
        return ("当前还没有已登录用户。", "NO USER", [])

    if any(key in compact for key in ["什么模式", "当前模式", "现在模式"]):
        if device.mode:
            return (f"当前模式是 {device.mode.value}。", f"{device.mode.value.upper()} MODE", [])
        return ("当前还没有设置模式。", "NO MODE", [])

    if any(key in compact for key in ["温度多少", "现在温度", "温度怎么样"]):
        temperature = sensor_number(device.sensors.get("temperature_c"))
        if device.sensors.get("aht20_ok") is True and temperature is not None:
            return (f"当前温度约 {temperature:.1f} 度。", "TEMP", [])
        return ("当前还没有读到有效温度。", "TEMP WAIT", [])

    if any(key in compact for key in ["湿度多少", "现在湿度", "湿度怎么样"]):
        humidity = sensor_number(device.sensors.get("humidity_pct"))
        if device.sensors.get("aht20_ok") is True and humidity is not None:
            return (f"当前湿度约 {humidity:.1f}%。", "HUMIDITY", [])
        return ("当前还没有读到有效湿度。", "HUM WAIT", [])

    if any(key in compact for key in ["距离多少", "距离怎么样", "前面多远", "测距"]):
        distance = sensor_number(device.sensors.get("distance_cm"))
        if device.sensors.get("distance_ok") is True and distance is not None:
            return (f"当前距离约 {distance:.1f} 厘米。", "DISTANCE", [])
        return ("当前超声波还没有有效距离数据。", "DIST WAIT", [])

    if any(key in compact for key in ["你怎么看", "你觉得呢", "给我个建议", "现在适合学习吗"]):
        temperature = sensor_number(device.sensors.get("temperature_c"))
        humidity = sensor_number(device.sensors.get("humidity_pct"))
        if temperature is not None and humidity is not None:
            return (
                f"如果你现在准备学习，环境温度大约 {temperature:.1f} 度，湿度 {humidity:.1f}%。整体还可以；如果你觉得闷，我可以顺手帮你开风扇。",
                "AI ADVICE",
                [],
            )
        return ("我建议先看一下实时状态；如果你需要，我也可以先帮你开风扇或者切专注模式。", "AI ADVICE", [])

    if heat_comfort_request:
        level = 3 if sensor_number(device.sensors.get("temperature_c")) and sensor_number(device.sensors.get("temperature_c")) >= 30 else 2
        return (
            f"我帮你把风扇开到 {level} 档。",
            "FAN ON",
            [ActionSpec(type="fan_control", payload={"state": "on", "level": level})],
        )

    if fan_on:
        level = extract_fan_level(compact)
        append_action(actions, "fan_control", {"state": "on", "level": level})
        reply_parts.append(f"已准备打开风扇 {level} 档。")
        oled = "FAN ON"
    if fan_off:
        append_action(actions, "fan_control", {"state": "off"})
        reply_parts.append("已准备关闭风扇。")
        oled = "FAN OFF"
    if beep_on:
        append_action(actions, "buzzer_alert")
        reply_parts.append("已触发蜂鸣提示。")
        oled = "BEEP"
    if music_stop:
        append_action(actions, "buzzer_music", {"preset": "stop"})
        reply_parts.append("已停止蜂鸣器音乐。")
        oled = "MUSIC STOP"
    if music_on:
        preset = "success"
        if any(key in compact for key in ["生日", "birthday", "happy"]):
            preset = "birthday"
        elif any(key in compact for key in ["报警", "警告", "alert", "warning"]):
            preset = "alert"
        elif any(key in compact for key in ["音阶", "scale"]):
            preset = "scale"
        elif any(key in compact for key in ["启动", "开机", "startup", "boot"]):
            preset = "startup"
        append_action(actions, "buzzer_music", {"preset": preset})
        reply_parts.append("已准备播放蜂鸣器音乐。")
        oled = "MUSIC"
    if focus_on:
        minutes = extract_focus_minutes(compact)
        append_action(actions, "focus_mode", {"minutes": minutes})
        reply_parts.append(f"已进入 {minutes} 分钟专注模式。")
        oled = "FOCUS MODE"
    if unlock_on:
        append_action(actions, "lock_control", {"state": "off"})
        reply_parts.append("已准备解锁桌面终端。")
        oled = "UNLOCK"
    if lock_on:
        append_action(actions, "lock_control", {"state": "on"})
        reply_parts.append("已准备锁定桌面终端。")
        oled = "LOCKED"
    if volume_mute:
        append_action(actions, "volume_control", {"level": 0})
        reply_parts.append("已静音。")
        oled = "VOLUME 0"
    elif volume_max:
        append_action(actions, "volume_control", {"level": 16})
        reply_parts.append("音量已调到最大。")
        oled = "VOLUME 16"
    elif volume_match:
        level = int(volume_match.group(1))
        append_action(actions, "volume_control", {"level": level})
        reply_parts.append(f"音量已调到 {level}。")
        oled = f"VOLUME {level}"
    elif volume_up:
        append_action(actions, "volume_control", {"level": "up"})
        reply_parts.append("音量已调大。")
        oled = "VOLUME UP"
    elif volume_down:
        append_action(actions, "volume_control", {"level": "down"})
        reply_parts.append("音量已调小。")
        oled = "VOLUME DOWN"

    if actions:
        return ("".join(reply_parts), oled, actions)

    return (
        f"收到：{text.strip()}。{device_status_phrase(device)}我会保持待机，等待下一步指令。",
        "AI READY",
        [],
    )
