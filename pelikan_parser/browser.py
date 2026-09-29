from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Locator, Page, Playwright, sync_playwright

from .config import AppConfig
from .errors import ConfigurationError, LocatorNotFoundError
from .models import Offer, SearchResult, select_minimum_offer
from .text_parsing import clean_labeled_value, extract_first, extract_prices, normalize_space


class SiteParser:
    def __init__(
        self,
        config: AppConfig,
        email: str,
        password: str,
        headless_override: bool | None = None,
    ) -> None:
        self.config = config
        self.email = email
        self.password = password
        self.browser_settings = config.section("browser")
        self.site = config.section("site")
        self.patterns = config.section("patterns")
        self.login_selectors = config.selector_group("login")
        self.catalog_selectors = config.selector_group("catalog")
        self.result_selectors = config.selector_group("results")
        self.headless = (
            headless_override
            if headless_override is not None
            else bool(self.browser_settings.get("headless", False))
        )
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None

    @property
    def timeout_ms(self) -> int:
        return int(self.browser_settings.get("timeout_ms", 20000))

    def __enter__(self) -> "SiteParser":
        self._playwright = sync_playwright().start()
        launch: dict[str, Any] = {
            "headless": self.headless,
            "slow_mo": int(self.browser_settings.get("slow_mo_ms", 0)),
        }
        channel = str(self.browser_settings.get("channel", "")).strip()
        if channel:
            launch["channel"] = channel
        self._browser = self._playwright.chromium.launch(**launch)

        context_options: dict[str, Any] = {
            "ignore_https_errors": bool(self.browser_settings.get("ignore_https_errors", False)),
            "viewport": {"width": 1440, "height": 1000},
        }
        state_path = self._storage_state_path()
        if state_path and state_path.exists():
            context_options["storage_state"] = str(state_path)
        self._context = self._browser.new_context(**context_options)
        self.page = self._context.new_page()
        self.page.set_default_timeout(self.timeout_ms)
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

    def _storage_state_path(self) -> Path | None:
        raw = str(self.browser_settings.get("storage_state_path", "")).strip()
        return self.config.resolve_path(raw) if raw else None

    @staticmethod
    def _locator(scope: Page | Locator, spec: str) -> Locator:
        spec = spec.strip()
        if spec.startswith("css=") or spec.startswith("xpath="):
            return scope.locator(spec)
        if spec.startswith("placeholder="):
            return scope.get_by_placeholder(spec.split("=", 1)[1], exact=False)
        if spec.startswith("label="):
            return scope.get_by_label(spec.split("=", 1)[1], exact=False)
        if spec.startswith("text="):
            return scope.get_by_text(spec.split("=", 1)[1], exact=False)
        if spec.startswith("testid="):
            return scope.get_by_test_id(spec.split("=", 1)[1])
        if spec.startswith("role="):
            payload = spec.split("=", 1)[1]
            role, separator, name = payload.partition("|")
            return scope.get_by_role(role.strip(), name=name.strip() if separator else None, exact=False)
        return scope.locator(spec)

    def _first_matching(
        self,
        scope: Page | Locator,
        specs: list[str],
        description: str,
        required: bool = True,
    ) -> Locator | None:
        errors: list[str] = []
        for spec in specs:
            try:
                locator = self._locator(scope, spec)
                if locator.count() > 0:
                    return locator.first
            except Exception as exc:
                errors.append(f"{spec}: {exc}")
        if required:
            suffix = f" Ошибки: {'; '.join(errors)}" if errors else ""
            raise LocatorNotFoundError(
                f"Не найден элемент '{description}'. Проверьте его список в config.yaml.{suffix}"
            )
        return None

    def _any_visible(self, scope: Page | Locator, specs: list[str]) -> bool:
        for spec in specs:
            try:
                locator = self._locator(scope, spec)
                if locator.count() and locator.first.is_visible():
                    return True
            except Exception:
                continue
        return False

    def _wait_until_visible(self, specs: list[str], timeout_ms: int) -> bool:
        assert self.page is not None
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            if self._any_visible(self.page, specs):
                return True
            self.page.wait_for_timeout(250)
        return False

    def login(self) -> None:
        assert self.page is not None
        search_specs = self.catalog_selectors.get("search_input", [])
        catalog_url = str(self.site.get("catalog_url", "")).strip()
        start_url = catalog_url or str(self.site["login_url"])
        self.page.goto(start_url, wait_until="domcontentloaded")
        if self._wait_until_visible(search_specs, min(self.timeout_ms, 5000)):
            return

        self.page.goto(str(self.site["login_url"]), wait_until="domcontentloaded")
        if not self.email or not self.password:
            raise ConfigurationError(
                "Для входа нужны PELIKAN_EMAIL и PELIKAN_PASSWORD в файле .env."
            )
        email = self._first_matching(self.page, self.login_selectors.get("email", []), "поле email")
        password = self._first_matching(self.page, self.login_selectors.get("password", []), "поле пароля")
        submit = self._first_matching(self.page, self.login_selectors.get("submit", []), "кнопка входа")
        assert email is not None and password is not None and submit is not None
        email.fill(self.email)
        password.fill(self.password)
        submit.click()

        success_specs = self.login_selectors.get("success_marker", []) + search_specs
        manual_seconds = int(self.browser_settings.get("manual_login_timeout_seconds", 0))
        wait_ms = max(self.timeout_ms, manual_seconds * 1000)
        if not self._wait_until_visible(success_specs, wait_ms):
            if catalog_url:
                self.page.goto(catalog_url, wait_until="domcontentloaded")
            if not self._wait_until_visible(search_specs, self.timeout_ms):
                raise LocatorNotFoundError(
                    "Вход не подтвержден: поле поиска каталога не появилось. "
                    "Проверьте логин, пароль и selectors.login/success_marker."
                )

        state_path = self._storage_state_path()
        if state_path and bool(self.browser_settings.get("save_session", True)):
            state_path.parent.mkdir(parents=True, exist_ok=True)
            assert self._context is not None
            self._context.storage_state(path=str(state_path))

    def _all_matching(self, scope: Page | Locator, specs: list[str]) -> Locator | None:
        for spec in specs:
            try:
                locator = self._locator(scope, spec)
                if locator.count() > 0:
                    return locator
            except Exception:
                continue
        return None

    def _extract_text(self, scope: Locator, specs: list[str]) -> str:
        locator = self._all_matching(scope, specs)
        if locator is None:
            return ""
        texts: list[str] = []
        for index in range(locator.count()):
            current = locator.nth(index)
            text = normalize_space(current.inner_text())
            if not text:
                for attribute in ("data-price", "content", "value", "aria-label"):
                    text = normalize_space(current.get_attribute(attribute) or "")
                    if text:
                        break
            texts.append(text)
        return "\n".join(text for text in texts if text)

    def _extract_offer(self, item: Locator) -> Offer:
        expand = self._first_matching(
            item,
            self.result_selectors.get("expand", []),
            "раскрытие карточки",
            required=False,
        )
        if expand is not None:
            try:
                if expand.is_visible():
                    expand.click()
                    assert self.page is not None
                    self.page.wait_for_timeout(
                        int(self.browser_settings.get("after_expand_delay_ms", 300))
                    )
            except Exception:
                pass

        raw_text = item.inner_text()
        manufacturer_text = self._extract_text(item, self.result_selectors.get("manufacturer", []))
        manufacturer = clean_labeled_value(manufacturer_text, "Производитель")
        if not manufacturer:
            manufacturer = extract_first(
                raw_text,
                str(self.patterns.get("manufacturer", r"(?im)Производитель\s*:\s*([^\r\n]+)")),
            )

        price_text = self._extract_text(item, self.result_selectors.get("price", []))
        price_pattern = str(self.patterns.get("price", ""))
        prices = extract_prices(price_text, price_pattern) if price_text and price_pattern else []
        if not prices and price_pattern:
            prices = extract_prices(raw_text, price_pattern)

        availability_text = self._extract_text(item, self.result_selectors.get("availability", []))
        availability = clean_labeled_value(availability_text, "Наличие на складе")
        if not availability:
            availability = extract_first(
                raw_text,
                str(self.patterns.get("availability", r"(?im)Наличие(?: на складе)?\s*:\s*([^\r\n]+)")),
            )
        return Offer(
            manufacturer=manufacturer,
            price=min(prices) if prices else None,
            availability=availability,
            raw_text=raw_text,
        )

    def search(self, eurocode: str) -> SearchResult:
        assert self.page is not None
        previous_items = self._all_matching(self.page, self.result_selectors.get("item", []))
        previous_signature = ""
        if previous_items is not None:
            try:
                previous_signature = "\n".join(previous_items.all_inner_texts())
            except Exception:
                previous_signature = ""

        clear = self._first_matching(
            self.page,
            self.catalog_selectors.get("clear", []),
            "кнопка очистки",
            required=False,
        )
        if clear is not None:
            try:
                if clear.is_visible():
                    clear.click()
            except Exception:
                pass

        search_input = self._first_matching(
            self.page,
            self.catalog_selectors.get("search_input", []),
            "поле поиска",
        )
        assert search_input is not None
        search_input.fill(eurocode)
        submit = self._first_matching(
            self.page,
            self.catalog_selectors.get("search_submit", []),
            "кнопка поиска",
            required=False,
        )
        if submit is not None:
            submit.click()
        else:
            search_input.press("Enter")

        deadline = time.monotonic() + int(self.browser_settings.get("results_timeout_ms", 15000)) / 1000
        items: Locator | None = None
        while time.monotonic() < deadline:
            items = self._all_matching(self.page, self.result_selectors.get("item", []))
            if items is not None and items.count() > 0:
                try:
                    current_signature = "\n".join(items.all_inner_texts())
                    contains_code = eurocode.casefold() in current_signature.casefold()
                    if contains_code or not previous_signature or current_signature != previous_signature:
                        break
                except Exception:
                    break
            if self._any_visible(self.page, self.result_selectors.get("empty", [])):
                break
            self.page.wait_for_timeout(250)
        self.page.wait_for_timeout(int(self.browser_settings.get("after_search_delay_ms", 1200)))
        items = self._all_matching(self.page, self.result_selectors.get("item", []))
        if items is None:
            return select_minimum_offer(eurocode, [])

        offers: list[Offer] = []
        seen: set[tuple[str, object, str]] = set()
        for index in range(items.count()):
            offer = self._extract_offer(items.nth(index))
            key = (offer.manufacturer.casefold(), offer.price, normalize_space(offer.raw_text))
            if key not in seen:
                seen.add(key)
                offers.append(offer)
        return select_minimum_offer(eurocode, offers)

    def save_debug(self, directory: Path, label: str) -> tuple[Path, Path]:
        assert self.page is not None
        directory.mkdir(parents=True, exist_ok=True)
        safe_label = re.sub(r"[^A-Za-z0-9А-Яа-я_-]+", "_", label)[:80] or "error"
        screenshot = directory / f"{safe_label}.png"
        html = directory / f"{safe_label}.html"
        self.page.screenshot(path=str(screenshot), full_page=True)
        html.write_text(self.page.content(), encoding="utf-8")
        return screenshot, html
