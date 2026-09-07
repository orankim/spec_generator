# Equipment Quotation (INTENTIONAL ERROR — TEST DATA ONLY)

<!-- INJECTED ERROR: Equipment Amount(30,000,000)이 Quantity(2) x Unit Price(10,000,000)=20,000,000과 다름 -->

## General

- Manufacturer: TestVendor
- Model: TV-001
- Linked Specification: (none — error_cases/는 SPEC과 연결하지 않는다)
- Quote No.: Q-ERR-001
- Quote Date: 2026-01-01
- Currency: KRW

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

## Notes

SAMPLE/TEST DATA — 실제 업체의 공식 견적이 아닙니다. 이 파일은 계산 오류 검출 로직을 검증하기 위해 의도적으로 잘못된 숫자를 담고 있습니다(실제 견적이 아님).
