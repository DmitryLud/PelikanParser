from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


def normalize_space(value: str) -> str:
    return re.sub(r"[\t \u00a0]+", " ", value or "").strip()


def clean_labeled_value(value: str, label: str) -> str:
    text = normalize_space(value)
    text = re.sub(rf"(?i)^.*?{re.escape(label)}\s*:\s*", "", text, count=1)
    return text.splitlines()[0].strip()


def decimal_from_price_token(token: str) -> Decimal | None:
    # Берем только числовую часть. Иначе точка в сокращении «руб.» может
    # ошибочно стать десятичным разделителем.
    numeric_match = re.search(r"\d+(?:[\s\u00a0.,]\d+)*", token or "")
    if not numeric_match:
        return None
    cleaned = numeric_match.group(0)
    cleaned = re.sub(r"[\s\u00a0]+", "", cleaned)
    if not cleaned or not re.search(r"\d", cleaned):
        return None

    if "," in cleaned and "." in cleaned:
        decimal_mark = "," if cleaned.rfind(",") > cleaned.rfind(".") else "."
        thousands_mark = "." if decimal_mark == "," else ","
        cleaned = cleaned.replace(thousands_mark, "").replace(decimal_mark, ".")
    elif "," in cleaned:
        head, tail = cleaned.rsplit(",", 1)
        cleaned = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) else cleaned.replace(",", "")
    elif "." in cleaned:
        head, tail = cleaned.rsplit(".", 1)
        cleaned = f"{head.replace('.', '')}.{tail}" if len(tail) in (1, 2) else cleaned.replace(".", "")

    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return value if value > 0 else None


def extract_prices(text: str, pattern: str) -> list[Decimal]:
    prices: list[Decimal] = []
    for match in re.finditer(pattern, text or ""):
        token = match.groupdict().get("price")
        if token is None:
            token = match.group(1) if match.lastindex else match.group(0)
        value = decimal_from_price_token(token)
        if value is not None:
            prices.append(value)
    return prices


def extract_first(text: str, pattern: str, label: str = "") -> str:
    match = re.search(pattern, text or "")
    if not match:
        return ""
    value = match.group(1) if match.lastindex else match.group(0)
    return clean_labeled_value(value, label) if label else normalize_space(value)
