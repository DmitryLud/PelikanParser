from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(slots=True)
class Offer:
    manufacturer: str = ""
    price: Decimal | None = None
    availability: str = ""
    raw_text: str = ""


@dataclass(slots=True)
class SearchResult:
    eurocode: str
    price: Decimal | None = None
    manufacturer: str = ""
    status: str = "Нет в наличии"
    found_positions: int = 0
    priced_positions: int = 0
    comment: str = ""
    offers: list[Offer] = field(default_factory=list)


def select_minimum_offer(eurocode: str, offers: list[Offer]) -> SearchResult:
    priced = [offer for offer in offers if offer.price is not None]
    if not priced:
        return SearchResult(
            eurocode=eurocode,
            status="Нет в наличии",
            found_positions=len(offers),
            priced_positions=0,
            comment="У найденных позиций цена не указана" if offers else "Позиции не найдены",
            offers=offers,
        )

    best = min(priced, key=lambda offer: offer.price)  # type: ignore[arg-type]
    return SearchResult(
        eurocode=eurocode,
        price=best.price,
        manufacturer=best.manufacturer or "Не указан",
        status="В наличии",
        found_positions=len(offers),
        priced_positions=len(priced),
        offers=offers,
    )
