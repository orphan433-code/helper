"""Gemini: natural language → ActionPlan JSON."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from agent.config import agent_settings
from agent.schema import ActionPlan
from agent.trace import agent_trace

_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

_SYSTEM = """Ты парсер команд для оператора платёжной системы PlatCore.
Пользователь пишет по-русски что сделать с сделками (отмена или редирект).
Верни ТОЛЬКО JSON без markdown.

Действия:
- decline — отменить/cancel сделки
- redirect — редирект/rematch на другого трейдера

Поля JSON:
{
  "action": "decline" | "redirect",
  "max_per_run": число (сколько сделок),
  "min_amount": число|null (USDT, минимум),
  "max_amount": число|null (USDT, максимум),
  "deal_status": "new" | "pending",
  "decline_bins": ["558328","531125","516746","548888"] — полные BIN из каталога,
  "decline_card_prefixes": ["5598","4315"] — любой префикс карты (4+ цифр), если нет в каталоге,
  "decline_tbc": true|false — TBC/4315 для decline,
  "redirect_bins": ["537524","557755"] — BIN каталога для redirect,
  "redirect_card_prefixes": ["5598","4315"] — любой префикс карты для redirect,
  "trader_labels": ["104.1","104.2","104.3"] — для redirect,
  "skip_bog": true|false — не редиректить BoG/548888,
  "visa_only": true|false — только Visa (4…),
  "max_remaining": true|false — только сделки с остатком времени МЕНЬШЕ порога,
  "max_remaining_hours": число (часы, по умолчанию 1),
  "all_matching": true|false — «все сделки» (без лимита, max_per_run=0),
  "use_ui_defaults": false — всегда false, UI не использовать,
  "confidence": 0..1,
  "explanation": "кратко по-русски что понял"
}

Правила (важно):
- use_ui_defaults всегда false — BIN, суммы, количество ТОЛЬКО из команды, не из UI
- «отмени/cancel/сними» → decline; «редирект/передай/rematch» → redirect
- «10 сделок» / «5 карт» / «1 сделку» → max_per_run, all_matching=false
- «все» / «всех» / «all» → all_matching=true, max_per_run=0
- «до 300 usdt» / «сумма до 300» → max_amount=300
- «от 100» → min_amount=100
- «меньше часа» / «остаток < 1ч» → max_remaining=true, max_remaining_hours=1
- Любые 4+ цифры карты: decline → decline_card_prefixes или decline_bins; redirect → redirect_card_prefixes или redirect_bins
- Катalog decline BIN: 558328,531125,516746,548888. Redirect BIN: 537524,557755
- «5488» → decline_bins ["548888"]; «537524» при redirect → redirect_bins
- «5598» → decline_card_prefixes или redirect_card_prefixes по action
- «tbc» → decline_tbc=true
- «pending» → deal_status=pending
- «visa» / «без bog» → visa_only / skip_bog для redirect
- Не выдумывай trader_ids; trader_labels только если явно названы (104.1…)
- Если BIN не указан — не подставляй из UI, оставь пустым
"""


def _build_prompt(text: str, ctx: dict[str, Any]) -> str:
    traders = ctx.get("available_traders") or []
    note = ""
    if isinstance(traders, list) and traders:
        labels = [
            str(t.get("label") or "").strip()
            for t in traders
            if isinstance(t, dict) and str(t.get("label") or "").strip()
        ]
        if labels:
            note = (
                "Аккаунты редиректа (только если явно названы в команде): "
                + ", ".join(labels)
                + "\n\n"
            )
    return f"{note}Команда пользователя:\n{text.strip()}\n"


def _extract_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Gemini вернул не объект JSON")
    return data


def _clip(text: str, limit: int = 1200) -> str:
    s = str(text or "")
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def _call_gemini(prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
    settings = agent_settings()
    key = settings["gemini_api_key"]
    model = settings["model"]
    if not key:
        raise RuntimeError(
            "Gemini API ключ не задан. Добавь agent.gemini_api_key в config.yaml "
            "или переменную GEMINI_API_KEY."
        )
    url = _GEMINI_URL.format(model=model) + f"?key={key}"
    body = {
        "system_instruction": {"parts": [{"text": _SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    body_json = json.dumps(body, ensure_ascii=False)
    agent_trace(f"Gemini → model={model} prompt_chars={len(prompt)} body_chars={len(body_json)}")
    agent_trace(f"Gemini → user: {_clip(prompt, 800)}")

    req = urllib.request.Request(
        url,
        data=body_json.encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        agent_trace(f"Gemini ✗ HTTP {exc.code}: {_clip(detail, 400)}")
        raise RuntimeError(f"Gemini HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        agent_trace(f"Gemini ✗ network: {exc}")
        raise RuntimeError(f"Gemini недоступен: {exc}") from exc

    usage = payload.get("usageMetadata") or {}
    prompt_tok = usage.get("promptTokenCount")
    out_tok = usage.get("candidatesTokenCount")
    total_tok = usage.get("totalTokenCount")
    agent_trace(
        f"Gemini ← tokens: prompt={prompt_tok} out={out_tok} total={total_tok}"
    )

    candidates = payload.get("candidates") or []
    if not candidates:
        agent_trace("Gemini ✗ пустой candidates")
        raise RuntimeError("Gemini: пустой ответ")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    texts = [str(p.get("text") or "") for p in parts if p.get("text")]
    if not texts:
        agent_trace("Gemini ✗ нет текста в ответе")
        raise RuntimeError("Gemini: нет текста в ответе")
    raw_text = "\n".join(texts)
    agent_trace(f"Gemini ← raw: {_clip(raw_text, 800)}")

    parsed = _extract_json(raw_text)
    meta = {
        "model": model,
        "prompt_chars": len(prompt),
        "body_chars": len(body_json),
        "usage": usage,
        "raw_text": raw_text,
        "parsed": parsed,
    }
    return parsed, meta


def parse_command_detailed(
    text: str, ctx: dict[str, Any]
) -> tuple[ActionPlan, dict[str, Any]]:
    """NL → ActionPlan + meta (tokens, raw JSON). Кеш истории — без Gemini."""
    from agent.history import lookup, remember, touch

    cleaned = str(text or "").strip()
    if not cleaned:
        raise ValueError("Пустая команда")
    agent_trace(f"parse: команда «{cleaned}»")

    cached = lookup(cleaned)
    if cached and isinstance(cached.get("plan"), dict):
        agent_trace("parse: cache HIT — Gemini не вызываем")
        plan = (
            ActionPlan.from_dict(cached["plan"])
            .apply_text_hints(cleaned)
            .merge_agent_context(ctx)
            .finalize()
        )
        err = plan.validate()
        if err:
            agent_trace(f"parse: cache устарел ({err}) — идём в Gemini")
        else:
            touch(cleaned)
            summary = plan.human_summary()
            agent_trace(f"parse: итог (cache) — {summary}")
            return plan, {
                "cached": True,
                "model": "cache",
                "prompt_chars": 0,
                "body_chars": 0,
                "usage": {},
                "raw_text": "",
                "parsed": cached["plan"],
                "summary": summary,
            }

    agent_trace(f"parse: UI ctx {_clip(json.dumps(ctx, ensure_ascii=False), 600)}")
    raw, meta = _call_gemini(_build_prompt(cleaned, ctx))
    agent_trace(
        f"parse: plan JSON {_clip(json.dumps(raw, ensure_ascii=False), 600)}"
    )
    plan = ActionPlan.from_dict(raw).apply_text_hints(cleaned)
    # В историю — до merge UI (аккаунты/суммы UI подтянутся при следующем hit)
    cache_plan = plan.to_dict()
    plan = plan.merge_agent_context(ctx).finalize()
    err = plan.validate()
    if err:
        raise ValueError(err)
    summary = plan.human_summary()
    agent_trace(f"parse: итог — {summary}")
    meta["summary"] = summary
    meta["cached"] = False
    remember(cleaned, cache_plan, summary, source="gemini")
    return plan, meta


def parse_command(text: str, ctx: dict[str, Any]) -> ActionPlan:
    plan, _meta = parse_command_detailed(text, ctx)
    return plan
