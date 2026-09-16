#!/usr/bin/env python3
"""
Generate a handful of sample documents into data/inbox/ so you can try
the pipeline immediately: a text-layer invoice PDF, a scanned (image-only)
invoice PDF that exercises OCR, and a two-row expenses CSV.

Usage:
    python examples/generate_sample_docs.py
"""

import sys
from pathlib import Path

import pymupdf as fitz

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "data" / "inbox"


def _text_invoice(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 90), "INVOICE", fontsize=20)
    page.insert_text((72, 120), "GLOBEX CORPORATION", fontsize=14)
    page.insert_text((72, 140), "94 Star Lane, Germany")
    page.insert_text((72, 170), "Invoice # INV-2026-0099")
    page.insert_text((72, 190), "Date: 2026-03-21")
    page.insert_text((72, 230), "Service                  Amount")
    page.insert_text((72, 250), "Consulting                850.00")
    page.insert_text((72, 270), "Software license          240.00")
    page.insert_text((72, 300), "TOTAL                   $1,090.00")
    page.insert_text((72, 340), "Due upon receipt. EUR")
    doc.save(path)
    doc.close()


def _scanned_invoice(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 90), "INVOICE", fontsize=20)
    page.insert_text((72, 120), "UMBRELLA RECEPTION")
    page.insert_text((72, 140), "Invoice # INV-2026-0100")
    page.insert_text((72, 160), "Date: 04/05/2026")
    page.insert_text((72, 200), "Room hire     150.00")
    page.insert_text((72, 220), "Catering      210.50")
    page.insert_text((72, 250), "TOTAL        $360.50")
    page.insert_text((72, 290), "Payment within 30 days. USD")

    scan = fitz.open()
    spage = scan.new_page()
    pix = page.get_pixmap(dpi=150)
    spage.insert_image(spage.rect, pixmap=pix)
    scan.save(path)
    scan.close()
    doc.close()


def _expenses_csv(path: Path) -> None:
    path.write_text(
        "date,invoice_number,vendor_name,total_amount,currency\n"
        "2026-05-01,CSV-01,Northwind Traders,99.99,USD\n"
        "2026-05-02,CSV-02,Contoso Ltd,150.00,USD\n"
    )


def main() -> None:
    INBOX.mkdir(parents=True, exist_ok=True)
    _text_invoice(INBOX / "invoice_text.pdf")
    _scanned_invoice(INBOX / "invoice_scan.pdf")
    _expenses_csv(INBOX / "expenses.csv")
    print("Sample documents written to data/inbox/:")
    for p in sorted(INBOX.glob("*.pdf")) + sorted(INBOX.glob("*.csv")):
        print(f"  {p.name}")


if __name__ == "__main__":
    sys.exit(main())