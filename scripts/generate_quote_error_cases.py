"""
Case K(계산 오류 테스트용 데이터) 생성 — docs/QUOTATION_MARKDOWN_FORMAT.md의
"계산 오류 테스트 데이터" 절에서 설계한 대로, 정상 데이터(sample_quotes/QUOTE-*.md)
와 완전히 분리된 디렉터리(sample_quotes/error_cases/)에 SPEC과 연결하지 않고 만든다.

각 파일은 정확히 하나의 계산 오류만 의도적으로 심는다 — Phase 5의 계산 검증
로직이 "이 오류를 실제로 검출하는가"를 확인하는 유닛 테스트 입력으로 쓰인다.

실행:
    python scripts/generate_quote_error_cases.py
"""
from __future__ import annotations

import os

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_REPO_ROOT, "sample_quotes", "error_cases")

_DISCLAIMER = (
    "SAMPLE/TEST DATA — 실제 업체의 공식 견적이 아닙니다. 이 파일은 계산 오류 검출 "
    "로직을 검증하기 위해 의도적으로 잘못된 숫자를 담고 있습니다(실제 견적이 아님)."
)

_HEADER = """# Equipment Quotation (INTENTIONAL ERROR — TEST DATA ONLY)

<!-- INJECTED ERROR: {error_desc} -->

## General

- Manufacturer: TestVendor
- Model: TV-{num}
- Linked Specification: (none — error_cases/는 SPEC과 연결하지 않는다)
- Quote No.: Q-ERR-{num}
- Quote Date: 2026-01-01
- Currency: KRW
"""

_FOOTER = """
## Notes

{disclaimer}
"""


def _write(num: str, error_desc: str, body: str) -> None:
    content = _HEADER.format(error_desc=error_desc, num=num) + body + _FOOTER.format(disclaimer=_DISCLAIMER)
    path = os.path.join(_OUT_DIR, f"QUOTE-ERR-{num}.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print(f"작성: {path}")


def main() -> None:
    os.makedirs(_OUT_DIR, exist_ok=True)

    # ERR-001: Amount != Quantity x Unit Price (Equipment 행 자체)
    _write(
        "001",
        "Equipment Amount(30,000,000)이 Quantity(2) x Unit Price(10,000,000)=20,000,000과 다름",
        """
## Equipment

| Item | Quantity | Unit Price | Amount |
|---|---|---|---|
| TestVendor TV-001 (Main Unit) | 2 | 10,000,000 | 30,000,000 |

## Commercial Terms

- Discount: None
- VAT: 10% (included in Grand Total below)

## Total

| Item | Amount |
|---|---|
| Equipment Subtotal | 30,000,000 |
| Subtotal (before VAT) | 30,000,000 |
| VAT (10%) | 3,000,000 |
| Grand Total | 33,000,000 |
""",
    )

    # ERR-002: Options Subtotal != sum of option row amounts
    _write(
        "002",
        "Options Subtotal(15,000,000)이 옵션 행 합계(5,000,000+4,000,000=9,000,000)와 다름",
        """
## Equipment

| Item | Quantity | Unit Price | Amount |
|---|---|---|---|
| TestVendor TV-002 (Main Unit) | 1 | 50,000,000 | 50,000,000 |

## Options

| Item | Quantity | Unit Price | Amount |
|---|---|---|---|
| Option A | 1 | 5,000,000 | 5,000,000 |
| Option B | 1 | 4,000,000 | 4,000,000 |

## Commercial Terms

- Discount: None
- VAT: 10% (included in Grand Total below)

## Total

| Item | Amount |
|---|---|
| Equipment Subtotal | 50,000,000 |
| Options Subtotal | 15,000,000 |
| Subtotal (before VAT) | 65,000,000 |
| VAT (10%) | 6,500,000 |
| Grand Total | 71,500,000 |
""",
    )

    # ERR-003: VAT != 10% of Subtotal (VAT 자체가 잘못 계산됨)
    _write(
        "003",
        "VAT(15,000,000)이 Subtotal(60,000,000)의 10%(6,000,000)가 아님",
        """
## Equipment

| Item | Quantity | Unit Price | Amount |
|---|---|---|---|
| TestVendor TV-003 (Main Unit) | 1 | 60,000,000 | 60,000,000 |

## Commercial Terms

- Discount: None
- VAT: 10% (included in Grand Total below)

## Total

| Item | Amount |
|---|---|
| Equipment Subtotal | 60,000,000 |
| Subtotal (before VAT) | 60,000,000 |
| VAT (10%) | 15,000,000 |
| Grand Total | 75,000,000 |
""",
    )

    # ERR-004: Discount가 표시되었지만 Grand Total에 반영되지 않음
    _write(
        "004",
        "Discount(-8,000,000)이 표에 있지만 Grand Total(99,000,000)이 이를 반영하지 않음 "
        "(Subtotal 90,000,000 + VAT 9,000,000 = 99,000,000이어야 하는데, Discount 반영 전 "
        "Subtotal 98,000,000 + VAT 9,800,000로 계산된 값 107,800,000도 아니고 그냥 할인 무시)",
        """
## Equipment

| Item | Quantity | Unit Price | Amount |
|---|---|---|---|
| TestVendor TV-004 (Main Unit) | 1 | 98,000,000 | 98,000,000 |

## Commercial Terms

- Discount: -8,000,000 KRW
- VAT: 10% (included in Grand Total below)

## Total

| Item | Amount |
|---|---|
| Equipment Subtotal | 98,000,000 |
| Discount | -8,000,000 |
| Subtotal (before VAT) | 98,000,000 |
| VAT (10%) | 9,800,000 |
| Grand Total | 107,800,000 |
""",
    )

    # ERR-005: Grand Total = Subtotal + VAT 자체가 산술적으로 틀림(단순 합산 오류)
    _write(
        "005",
        "Grand Total(120,000,000)이 Subtotal(100,000,000) + VAT(10,000,000)=110,000,000과 다름",
        """
## Equipment

| Item | Quantity | Unit Price | Amount |
|---|---|---|---|
| TestVendor TV-005 (Main Unit) | 1 | 100,000,000 | 100,000,000 |

## Commercial Terms

- Discount: None
- VAT: 10% (included in Grand Total below)

## Total

| Item | Amount |
|---|---|
| Equipment Subtotal | 100,000,000 |
| Subtotal (before VAT) | 100,000,000 |
| VAT (10%) | 10,000,000 |
| Grand Total | 120,000,000 |
""",
    )


if __name__ == "__main__":
    main()
