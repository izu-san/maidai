"""Natural-language wording for approval requests shown in the chat UI.

The text only restates the tool arguments; it never replaces the policy decision.
"""
from __future__ import annotations

from typing import Any

_BIG_UNITS = {"g": ("kg", 1000), "ml": ("L", 1000)}


def _number(value: Any) -> str:
    number = float(value)
    return f"{int(number):,}" if number.is_integer() else f"{number:,.2f}".rstrip("0").rstrip(".")


def amount(value: Any, unit: str) -> str:
    """Format an amount; large g/ml values also show kg/L so unit mix-ups are visible."""
    text = f"{_number(value)}{unit}"
    big = _BIG_UNITS.get(unit)
    if big and float(value) >= big[1]:
        text += f"（{_number(float(value) / big[1])}{big[0]}）"
    return text


def _register(a: dict[str, Any]) -> str:
    unit = str(a.get("unit", ""))
    parts = [f"{a.get('name', '新しい消耗品')}（{a.get('category', '')}）を管理対象に登録しますね。" if a.get("category") else f"{a.get('name', '新しい消耗品')}を管理対象に登録しますね。"]
    capacity = amount(a["capacity"], unit) if "capacity" in a else "未指定"
    remaining = f"今の残量は{amount(a['remaining'], unit)}" if a.get("remaining") is not None else "残量は満タンとして扱います"
    parts.append(f"容量は{capacity}で、{remaining}です。")
    if a.get("stock_unopened"): parts.append(f"未開封のストックは{a['stock_unopened']}個です。")
    usage = a.get("usage_model") or {}
    if usage.get("type") == "PER_DAY": parts.append(f"毎日{amount(usage['amount'], unit)}ずつ自動で減らします（登録した翌日から）。")
    elif usage.get("type") == "PER_EVENT": parts.append(f"洗濯が終わったと教えていただくたびに{amount(usage['amount'], unit)}ずつ減らします。")
    else: parts.append("残量は、教えていただいたときだけ更新します。")
    below = (a.get("reminder") or {}).get("remaining_below")
    parts.append(f"残りが{amount(below, unit)}以下になったらお知らせします。" if below is not None else "残量のお知らせは設定しません。")
    return "".join(parts)


def _finance(a: dict[str, Any]) -> str:
    kind = "支出" if a.get("kind") == "expense" else "収入"
    note = f"（メモ：{a['note']}）" if a.get("note") else ""
    return f"{a.get('occurred_on', '')}の{kind}として、{a.get('category', '')}に{_number(a.get('amount_yen', 0))}円{note}"


def describe_approval(tool: str, arguments: dict[str, Any]) -> str | None:
    """Return a Rino-style confirmation sentence, or None when the tool has no wording."""
    a = arguments if isinstance(arguments, dict) else {}
    try:
        if tool == "life.register_consumable": body = _register(a)
        elif tool == "life.deactivate_consumable": body = f"「{a['item_id']}」を管理対象から外しますね。" + (f"（理由：{a['reason']}）" if a.get("reason") else "")
        elif tool == "life.record_finance_transaction": body = _finance(a) + "を記録しますね。"
        elif tool == "life.correct_finance_transaction": body = f"取引「{a['transaction_id']}」を、" + _finance(a) + "に訂正しますね。"
        elif tool == "life.cancel_finance_transaction": body = f"取引「{a['transaction_id']}」を取り消しますね。" + (f"（理由：{a['reason']}）" if a.get("reason") else "")
        elif tool == "home.set_temperature": body = f"エアコンの設定温度を{_number(a['celsius'])}度にしますね。"
        elif tool == "home.tv_on": body = "テレビをつけますね。"
        elif tool == "home.lock_door": body = "玄関の鍵を施錠しますね。"
        else: return None
    except (KeyError, TypeError, ValueError):
        return None
    return body + "この内容でよろしいですか？（はい／いいえ）"
