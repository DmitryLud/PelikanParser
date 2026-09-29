from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigurationError


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigurationError(f"Раздел '{name}' должен быть объектом YAML.")
    return value


def _locator_list(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item for item in value if item.strip()]
    raise ConfigurationError(f"Поле селекторов '{name}' должно быть строкой или списком строк.")


@dataclass(slots=True)
class AppConfig:
    path: Path
    raw: dict[str, Any]

    @property
    def base_dir(self) -> Path:
        return self.path.parent

    def section(self, name: str) -> dict[str, Any]:
        return _mapping(self.raw.get(name, {}), name)

    def resolve_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else (self.base_dir / path).resolve()

    def selector_group(self, group: str) -> dict[str, list[str]]:
        selectors = _mapping(self.raw.get("selectors", {}), "selectors")
        values = _mapping(selectors.get(group, {}), f"selectors.{group}")
        return {key: _locator_list(value, f"selectors.{group}.{key}") for key, value in values.items()}


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).resolve()
    if not config_path.exists():
        raise ConfigurationError(
            f"Файл настроек не найден: {config_path}. Скопируйте config.example.yaml в config.yaml."
        )
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Ошибка YAML в {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigurationError("Корень config.yaml должен быть объектом YAML.")

    config = AppConfig(path=config_path, raw=raw)
    site = config.section("site")
    login_url = str(site.get("login_url", "")).strip()
    if not login_url or "example.com" in login_url:
        raise ConfigurationError("Укажите настоящий site.login_url в config.yaml.")
    if not config.selector_group("catalog").get("search_input"):
        raise ConfigurationError("Не заполнены selectors.catalog.search_input.")
    if not config.selector_group("results").get("item"):
        raise ConfigurationError("Не заполнены selectors.results.item.")
    return config
