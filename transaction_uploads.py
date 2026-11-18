import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
from pathlib import Path
from typing import Iterable, Sequence
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
REQUIRED_COLUMNS = (
    "transaction_id",
    "transaction_date",
    "invoice_number",
    "vendor_name",
    "amount",
    "transaction_type",
    "document_reference",
)
_FIELDS_WITH_REQUIRED_VALUES = REQUIRED_COLUMNS[:-1]


class UploadValidationError(ValueError):
    """Raised when an uploaded transaction file is invalid."""


def parse_transactions(filename: str, content: bytes) -> list[dict]:
    extension = Path(filename).suffix.lower()
    if extension not in {".csv", ".xlsx"}:
        raise UploadValidationError("Upload a CSV (.csv) or Excel workbook (.xlsx) file.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadValidationError("The file exceeds the 5 MB upload limit.")
    if not content:
        raise UploadValidationError("The uploaded file is empty.")

    if extension == ".csv":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise UploadValidationError("The CSV must use UTF-8 text encoding.") from error
        try:
            reader = csv.reader(StringIO(text, newline=""), strict=True)
            headers = next(reader, None)
            if headers is None:
                raise UploadValidationError("The CSV file does not contain a header row.")
            return _read_records(headers, reader)
        except csv.Error as error:
            raise UploadValidationError("The CSV file is malformed or corrupted.") from error

    return _read_excel(content)


def _read_excel(content: bytes) -> list[dict]:
    workbook = None
    try:
        workbook = load_workbook(
            BytesIO(content),
            read_only=True,
            data_only=True,
            keep_links=False,
        )
        worksheet = workbook.active
        rows = worksheet.iter_rows(values_only=True)
        headers = next(rows, None)
        if headers is None:
            raise UploadValidationError("The Excel workbook does not contain a header row.")
        return _read_records(headers, rows)
    except UploadValidationError:
        raise
    except (BadZipFile, InvalidFileException, OSError, ValueError) as error:
        raise UploadValidationError(
            "The Excel workbook is invalid or corrupted. Save it as .xlsx and try again."
        ) from error
    finally:
        if workbook is not None:
            workbook.close()


def _read_records(headers: Sequence, rows: Iterable[Sequence]) -> list[dict]:
    normalized_headers = [
        str(header).strip().lower() if header is not None else ""
        for header in headers
    ]
    nonempty_headers = [header for header in normalized_headers if header]
    if len(nonempty_headers) != len(set(nonempty_headers)):
        raise UploadValidationError("The file contains duplicate column names.")

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in normalized_headers]
    if missing_columns:
        raise UploadValidationError(
            "Missing required columns: " + ", ".join(missing_columns) + "."
        )
    column_indexes = {
        column: normalized_headers.index(column) for column in REQUIRED_COLUMNS
    }

    transactions = []
    for row_number, row in enumerate(rows, start=2):
        values = list(row)
        if not any(value is not None and str(value).strip() for value in values):
            continue
        if len(values) > len(normalized_headers):
            raise UploadValidationError(
                f"Row {row_number} has more values than the header row."
            )
        values.extend([None] * (len(normalized_headers) - len(values)))
        transactions.append(_validate_row(values, column_indexes, row_number))

    if not transactions:
        raise UploadValidationError("The file does not contain any transaction rows.")
    return transactions


def _validate_row(values: list, indexes: dict, row_number: int) -> dict:
    record = {
        column: values[indexes[column]]
        for column in REQUIRED_COLUMNS
    }

    for column in _FIELDS_WITH_REQUIRED_VALUES:
        value = record[column]
        if value is None or not str(value).strip():
            raise UploadValidationError(
                f"Row {row_number} is missing a value for {column}."
            )

    transaction_date = _parse_date(record["transaction_date"], row_number)
    try:
        amount = Decimal(str(record["amount"]).strip())
    except (InvalidOperation, ValueError):
        raise UploadValidationError(
            f"Row {row_number} has an invalid numerical amount."
        )
    if not amount.is_finite():
        raise UploadValidationError(f"Row {row_number} has a non-finite amount.")

    normalized = {
        column: str(record[column]).strip()
        for column in _FIELDS_WITH_REQUIRED_VALUES
    }
    normalized["transaction_date"] = transaction_date.isoformat()
    normalized["amount"] = format(amount, "f")
    # A blank document reference is retained for later audit review.
    normalized["document_reference"] = (
        "" if record["document_reference"] is None
        else str(record["document_reference"]).strip()
    )
    return normalized


def _parse_date(value, row_number: int) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        raise UploadValidationError(
            f"Row {row_number} has an invalid transaction_date. Use YYYY-MM-DD."
        )
