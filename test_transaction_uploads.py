import io
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

from services.transaction_uploads import (
    MAX_UPLOAD_BYTES,
    UploadValidationError,
    parse_transactions,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = PROJECT_ROOT / "data" / "sample_transactions.csv"
HEADERS = (
    "transaction_id",
    "transaction_date",
    "invoice_number",
    "vendor_name",
    "amount",
    "transaction_type",
    "document_reference",
)


class TransactionUploadTests(unittest.TestCase):
    def test_synthetic_sample_has_36_valid_transactions(self):
        transactions = parse_transactions(
            "sample_transactions.csv",
            SAMPLE_PATH.read_bytes(),
        )

        self.assertEqual(len(transactions), 36)
        self.assertEqual(len({row["vendor_name"] for row in transactions}), 5)
        self.assertEqual(
            sum(Decimal(row["amount"]) for row in transactions),
            Decimal("119019.35"),
        )
        self.assertTrue(any(not row["document_reference"] for row in transactions))
        self.assertTrue(
            any(date.fromisoformat(row["transaction_date"]).isoweekday() > 5
                for row in transactions)
        )
        self.assertTrue(
            any(row["transaction_type"] == "Manual Journal" for row in transactions)
        )

    def test_xlsx_upload_accepts_excel_dates_and_blank_document_reference(self):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(HEADERS)
        worksheet.append(
            ("TX-XLSX-1", datetime(2025, 3, 8), "INV-XLSX-1",
             "Fictional Vendor", 50.25, "Payment", None)
        )
        content = io.BytesIO()
        workbook.save(content)

        transactions = parse_transactions("transactions.xlsx", content.getvalue())

        self.assertEqual(transactions[0]["transaction_date"], "2025-03-08")
        self.assertEqual(transactions[0]["amount"], "50.25")
        self.assertEqual(transactions[0]["document_reference"], "")

    def test_rejects_missing_columns_and_invalid_values(self):
        header = ",".join(HEADERS)
        with self.assertRaisesRegex(UploadValidationError, "Missing required columns"):
            parse_transactions("missing.csv", b"transaction_id,vendor_name\nTX-1,Vendor\n")
        with self.assertRaisesRegex(UploadValidationError, "invalid transaction_date"):
            parse_transactions(
                "invalid-date.csv",
                f"{header}\nTX-1,not-a-date,INV-1,Vendor,10,Invoice,DOC-1\n".encode(),
            )
        with self.assertRaisesRegex(UploadValidationError, "invalid numerical amount"):
            parse_transactions(
                "invalid-amount.csv",
                f"{header}\nTX-1,2025-03-03,INV-1,Vendor,ten,Invoice,DOC-1\n".encode(),
            )
        with self.assertRaisesRegex(UploadValidationError, "missing a value"):
            parse_transactions(
                "missing-value.csv",
                f"{header}\nTX-1,2025-03-03,,Vendor,10,Invoice,DOC-1\n".encode(),
            )

    def test_rejects_unsupported_oversized_and_corrupted_files(self):
        with self.assertRaisesRegex(UploadValidationError, "CSV"):
            parse_transactions("transactions.xls", b"file")
        with self.assertRaisesRegex(UploadValidationError, "5 MB"):
            parse_transactions("large.csv", b"x" * (MAX_UPLOAD_BYTES + 1))
        with self.assertRaisesRegex(UploadValidationError, "corrupted"):
            parse_transactions("broken.xlsx", b"not an Excel workbook")


if __name__ == "__main__":
    unittest.main()
