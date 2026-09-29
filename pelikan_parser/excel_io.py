from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.table import Table, TableStyleInfo

from .errors import ConfigurationError
from .models import SearchResult


def _cell_to_code(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def read_eurocodes(
    path: Path,
    sheet_name: str,
    column_name: str,
    header_row: int = 1,
    deduplicate: bool = True,
) -> list[str]:
    if not path.exists():
        raise ConfigurationError(f"Входной Excel-файл не найден: {path}")
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise ConfigurationError(f"Не удалось открыть входной Excel-файл {path}: {exc}") from exc

    if sheet_name not in workbook.sheetnames:
        raise ConfigurationError(
            f"Лист '{sheet_name}' не найден. Доступные листы: {', '.join(workbook.sheetnames)}"
        )
    sheet = workbook[sheet_name]
    headers: dict[str, int] = {}
    header_cells = next(
        sheet.iter_rows(min_row=header_row, max_row=header_row),
        (),
    )
    for cell in header_cells:
        if cell.value is not None:
            headers[str(cell.value).strip().casefold()] = cell.column
    column_index = headers.get(column_name.strip().casefold())
    if column_index is None:
        visible_headers = [str(cell.value) for cell in header_cells if cell.value is not None]
        raise ConfigurationError(
            f"Столбец '{column_name}' не найден в строке {header_row}. "
            f"Найдены: {', '.join(visible_headers) or 'нет заголовков'}"
        )

    result: list[str] = []
    seen: set[str] = set()
    for row in sheet.iter_rows(
        min_row=header_row + 1,
        min_col=column_index,
        max_col=column_index,
        values_only=True,
    ):
        code = _cell_to_code(row[0] if row else None)
        if not code:
            continue
        key = code.casefold()
        if deduplicate and key in seen:
            continue
        seen.add(key)
        result.append(code)
    workbook.close()
    if not result:
        raise ConfigurationError(f"В столбце '{column_name}' нет Eurocode для обработки.")
    return result


def _as_excel_number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def write_results(path: Path, results: list[SearchResult], include_diagnostics: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Результат"
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = "A2"

    headers = ["Eurocode", "Цена", "Производитель", "Статус"]
    if include_diagnostics:
        headers.extend(["Найдено позиций", "Позиций с ценой", "Комментарий"])
    sheet.append(headers)

    for result in results:
        row: list[object] = [
            result.eurocode,
            _as_excel_number(result.price),
            result.manufacturer,
            result.status,
        ]
        if include_diagnostics:
            row.extend([result.found_positions, result.priced_positions, result.comment])
        sheet.append(row)

    yellow = "FFC61A"
    dark = "1F1F1F"
    light_border = Side(style="thin", color="D9D9D9")
    header = sheet[1]
    for cell in header:
        cell.fill = PatternFill("solid", fgColor=dark)
        cell.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = Border(bottom=Side(style="medium", color=yellow))
    sheet.row_dimensions[1].height = 24

    for row in sheet.iter_rows(min_row=2, max_row=sheet.max_row):
        for cell in row:
            cell.font = Font(name="Arial", size=10, color=dark)
            cell.alignment = Alignment(vertical="center")
            cell.border = Border(bottom=light_border)
        row[1].number_format = '#,##0.00'
        if row[3].value == "Нет в наличии":
            row[3].fill = PatternFill("solid", fgColor="FCE8E6")
            row[3].font = Font(name="Arial", size=10, color="B42318")
        elif row[3].value == "Ошибка":
            row[3].fill = PatternFill("solid", fgColor="FFE5D0")
            row[3].font = Font(name="Arial", size=10, bold=True, color="9C2A10")

    widths = {"A": 22, "B": 15, "C": 24, "D": 18, "E": 19, "F": 18, "G": 48}
    for column, width in widths.items():
        if sheet.max_column >= ord(column) - ord("A") + 1:
            sheet.column_dimensions[column].width = width
    sheet.auto_filter.ref = f"A1:{sheet.cell(row=1, column=sheet.max_column).coordinate}"
    if sheet.max_row >= 2:
        table = Table(displayName="EurocodeResults", ref=f"A1:{sheet.cell(row=sheet.max_row, column=sheet.max_column).coordinate}")
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        sheet.add_table(table)

    workbook.save(path)
