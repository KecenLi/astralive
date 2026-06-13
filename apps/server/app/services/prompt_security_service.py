from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


GENERIC_REFUSAL = (
    "这个请求涉及绕过安全规则、泄露内部提示或凭据，或未经授权启用设备权限，我不能这么做。"
    "我可以继续帮你完成正常任务、解释功能，或在你明确授权后使用摄像头、麦克风和屏幕。"
)

OUTPUT_REFUSAL = (
    "我刚才的回答触发了安全检查，可能包含内部配置、凭据或越权操作内容。"
    "这些信息不能输出，我可以改为说明可公开的功能和下一步操作。"
)


@dataclass(frozen=True)
class PromptSecurityVerdict:
    allowed: bool
    category: str = "allowed"
    reason: str = ""
    refusal: str = ""

    def raw(self) -> dict[str, str | bool]:
        return {
            "allowed": self.allowed,
            "category": self.category,
            "reason": self.reason,
        }


class PromptSecurityService:
    def assess_user_text(self, text: str) -> PromptSecurityVerdict:
        normalized, compact = _normalize(text)
        for category, reason, patterns in USER_PATTERNS:
            if _matches(patterns, normalized, compact):
                return PromptSecurityVerdict(
                    allowed=False,
                    category=category,
                    reason=reason,
                    refusal=GENERIC_REFUSAL,
                )
        return PromptSecurityVerdict(allowed=True)

    def assess_model_output(self, text: str) -> PromptSecurityVerdict:
        normalized, compact = _normalize(text)
        for category, reason, patterns in OUTPUT_PATTERNS:
            if _matches(patterns, normalized, compact):
                return PromptSecurityVerdict(
                    allowed=False,
                    category=category,
                    reason=reason,
                    refusal=OUTPUT_REFUSAL,
                )
        return PromptSecurityVerdict(allowed=True)


def _normalize(text: str) -> tuple[str, str]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    compact = re.sub(r"[\s`'\"“”‘’.,;:!?！？。，、；：()\[\]{}<>《》\-_=+|\\/]+", "", normalized)
    return normalized, compact


def _matches(patterns: tuple[str, ...], normalized: str, compact: str) -> bool:
    return any(re.search(pattern, normalized) or re.search(pattern, compact) for pattern in patterns)


USER_PATTERNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "system_prompt_exfiltration",
        "The user is asking to reveal hidden/system/developer instructions.",
        (
            r"(show|print|repeat|reveal|quote|dump|export|leak).{0,80}(system|developer|hidden|initial).{0,30}(prompt|instruction|message)",
            r"(system|developer|hidden|initial).{0,30}(prompt|instruction|message).{0,80}(show|print|repeat|reveal|quote|dump|export|leak)",
            r"(系统|开发者|隐藏|初始|内部|上面).{0,20}(提示词|指令|规则|消息|prompt).{0,30}(告诉|显示|输出|打印|复述|泄露|原文|逐字|完整)",
            r"(告诉|显示|输出|打印|复述|泄露|原文|逐字|完整).{0,30}(系统|开发者|隐藏|初始|内部|上面).{0,20}(提示词|指令|规则|消息|prompt)",
            r"(系统提示词|开发者消息|隐藏指令|初始prompt|systemprompt|developerprompt)",
        ),
    ),
    (
        "secret_exfiltration",
        "The user is asking to reveal credentials, tokens, or environment secrets.",
        (
            r"(show|print|reveal|dump|export|leak|read).{0,80}(api[_ -]?key|token|secret|password|credential|bearer|pat|env|environment)",
            r"(api[_ -]?key|token|secret|password|credential|bearer|pat|env|environment).{0,80}(show|print|reveal|dump|export|leak|read)",
            r"(显示|输出|打印|读取|导出|泄露|告诉).{0,30}(密钥|令牌|凭据|密码|环境变量|github pat|google_application_credentials|gemini_api_key)",
            r"(密钥|令牌|凭据|密码|环境变量|githubpat|googleapplicationcredentials|geminiapikey).{0,30}(显示|输出|打印|读取|导出|泄露|告诉)",
        ),
    ),
    (
        "instruction_override",
        "The user is trying to override the assistant's governing instructions.",
        (
            r"(ignore|disregard|forget|override).{0,50}(previous|above|system|developer).{0,30}(instruction|prompt|message|rule)",
            r"(jailbreak|dan mode|developer mode|god mode|system override)",
            r"(忽略|无视|忘记|覆盖|替换).{0,25}(之前|以上|上面|系统|开发者|原有).{0,20}(指令|提示|规则|设定)",
            r"(越狱|开发者模式|系统覆盖|最高权限|无视安全规则)",
        ),
    ),
    (
        "unauthorized_device_action",
        "The user is asking for silent or permission-bypassing device access.",
        (
            r"(enable|start|turn on|capture|record).{0,40}(camera|microphone|screen|display|autostart).{0,60}(without|silently|no consent|bypass)",
            r"(without|silently|no consent|bypass).{0,60}(camera|microphone|screen|display|autostart)",
            r"(静默|不要询问|无需授权|绕过权限|不弹窗|未经允许|强制).{0,40}(摄像头|麦克风|屏幕|屏幕捕捉|录音|开机自启)",
            r"(摄像头|麦克风|屏幕|屏幕捕捉|录音|开机自启).{0,40}(静默|不要询问|无需授权|绕过权限|不弹窗|未经允许|强制)",
        ),
    ),
)


OUTPUT_PATTERNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "secret_like_output",
        "The model output appears to contain credentials or environment secrets.",
        (
            r"(sk-[a-z0-9]{16,}|ghp_[a-z0-9]{16,}|ya29\.[a-z0-9_\-.]+|bearer\s+[a-z0-9_\-.]{16,})",
            r"(api[_ -]?key|token|secret|password|credential|google_application_credentials|gemini_api_key)\s*[:=]\s*\S{8,}",
            r"(密钥|令牌|凭据|密码|环境变量)\s*[:：=]\s*\S{8,}",
        ),
    ),
    (
        "system_prompt_like_output",
        "The model output appears to expose hidden/system prompt content.",
        (
            r"(system|developer|hidden).{0,20}(prompt|instruction|message)\s*[:=]",
            r"(系统|开发者|隐藏).{0,12}(提示词|指令|消息)\s*[:：=]",
        ),
    ),
)
