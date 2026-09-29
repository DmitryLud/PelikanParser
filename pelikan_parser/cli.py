from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from .browser import SiteParser
from .config import AppConfig, load_config
from .errors import ConfigurationError, ParserError
from .excel_io import read_eurocodes, write_results
from .models import SearchResult


def _read_input_settings(config: AppConfig) -> tuple[Path, str, str, int, bool]:
    settings = config.section("input")
    return (
        config.resolve_path(str(settings.get("path", "input/eurocodes.xlsx"))),
        str(settings.get("sheet", "Eurocodes")),
        str(settings.get("column", "Eurocode")),
        int(settings.get("header_row", 1)),
        bool(settings.get("deduplicate", True)),
    )


def _load_credentials(config: AppConfig, env_path: str) -> tuple[str, str]:
    path = Path(env_path)
    if not path.is_absolute():
        path = config.base_dir / path
    load_dotenv(path, override=False)
    return os.getenv("PELIKAN_EMAIL", "").strip(), os.getenv("PELIKAN_PASSWORD", "")


def command_init(args: argparse.Namespace) -> int:
    root = Path(args.directory).resolve()
    source_root = Path(__file__).resolve().parent.parent
    created: list[str] = []
    for source_name, target_name in (("config.example.yaml", "config.yaml"), (".env.example", ".env")):
        target = root / target_name
        if target.exists() and not args.force:
            continue
        shutil.copyfile(source_root / source_name, target)
        created.append(str(target))
    print("Созданы файлы:" if created else "Файлы уже существуют.")
    for path in created:
        print(f"  {path}")
    return 0


def command_check(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    email, password = _load_credentials(config, args.env)
    input_path, sheet, column, header_row, deduplicate = _read_input_settings(config)
    eurocodes = read_eurocodes(input_path, sheet, column, header_row, deduplicate)
    print(f"Настройки: {config.path}")
    print(f"Входной файл: {input_path}")
    print(f"Eurocode для обработки: {len(eurocodes)}")
    print(f"Email: {'задан' if email else 'не задан'}")
    print(f"Пароль: {'задан' if password else 'не задан'}")
    print("Базовая проверка завершена. Селекторы страницы проверяются командой run.")
    return 0


def command_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    email, password = _load_credentials(config, args.env)
    input_path, sheet, column, header_row, deduplicate = _read_input_settings(config)
    eurocodes = read_eurocodes(input_path, sheet, column, header_row, deduplicate)
    if args.limit is not None:
        eurocodes = eurocodes[: args.limit]

    output_settings = config.section("output")
    output_path = config.resolve_path(str(output_settings.get("path", "output/results.xlsx")))
    include_diagnostics = bool(output_settings.get("include_diagnostics", True))
    debug_settings = config.section("debug")
    debug_dir = config.resolve_path(str(debug_settings.get("directory", "debug")))
    save_on_error = bool(debug_settings.get("save_on_error", True))
    delay_ms = int(config.section("browser").get("delay_between_codes_ms", 1000))

    headless_override: bool | None = None
    if args.headful:
        headless_override = False
    elif args.headless:
        headless_override = True

    results: list[SearchResult] = []
    print(f"Запуск. Eurocode: {len(eurocodes)}. Результат: {output_path}")
    with SiteParser(config, email, password, headless_override=headless_override) as parser:
        try:
            parser.login()
        except Exception:
            if save_on_error:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                screenshot, html = parser.save_debug(debug_dir, f"login_{stamp}")
                print(f"Диагностика входа: {screenshot}; {html}", file=sys.stderr)
            raise

        for index, eurocode in enumerate(eurocodes, start=1):
            print(f"[{index}/{len(eurocodes)}] {eurocode}")
            try:
                result = parser.search(eurocode)
                results.append(result)
                price = str(result.price) if result.price is not None else "—"
                print(f"  {result.status}; цена: {price}; производитель: {result.manufacturer or '—'}")
            except Exception as exc:
                results.append(
                    SearchResult(
                        eurocode=eurocode,
                        status="Ошибка",
                        comment=str(exc),
                    )
                )
                print(f"  Ошибка: {exc}", file=sys.stderr)
                if save_on_error:
                    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    parser.save_debug(debug_dir, f"{eurocode}_{stamp}")
            if index < len(eurocodes) and delay_ms > 0:
                assert parser.page is not None
                parser.page.wait_for_timeout(delay_ms)

    write_results(output_path, results, include_diagnostics=include_diagnostics)
    print(f"Готово: {output_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pelikan-parser",
        description="Локальный парсер минимальной цены по Eurocode.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Создать config.yaml и .env из примеров")
    init.add_argument("--directory", default=".")
    init.add_argument("--force", action="store_true", help="Перезаписать существующие файлы")
    init.set_defaults(func=command_init)

    check = subparsers.add_parser("check", help="Проверить конфигурацию и входной Excel")
    check.add_argument("--config", default="config.yaml")
    check.add_argument("--env", default=".env")
    check.set_defaults(func=command_check)

    run = subparsers.add_parser("run", help="Выполнить парсинг")
    run.add_argument("--config", default="config.yaml")
    run.add_argument("--env", default=".env")
    run.add_argument("--limit", type=int, default=None, help="Обработать только первые N кодов")
    display = run.add_mutually_exclusive_group()
    display.add_argument("--headful", action="store_true", help="Показать браузер")
    display.add_argument("--headless", action="store_true", help="Скрыть браузер")
    run.set_defaults(func=command_run)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        raise SystemExit(args.func(args))
    except (ConfigurationError, ParserError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except KeyboardInterrupt:
        print("Остановлено пользователем.", file=sys.stderr)
        raise SystemExit(130)
