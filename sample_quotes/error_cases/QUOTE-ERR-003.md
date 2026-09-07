# Equipment Quotation (INTENTIONAL ERROR — TEST DATA ONLY)

<!-- INJECTED ERROR: VAT(15,000,000)이 Subtotal(60,000,000)의 10%(6,000,000)가 아님 -->

## General

- Manufacturer: TestVendor
- Model: TV-003
- Linked Specification: (none — error_cases/는 SPEC과 연결하지 않는다)
- Quote No.: Q-ERR-003
- Quote Date: 2026-01-01
- Currency: KRW

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

## Notes

SAMPLE/TEST DATA — 실제 업체의 공식 견적이 아닙니다. 이 파일은 계산 오류 검출 로직을 검증하기 위해 의도적으로 잘못된 숫자를 담고 있습니다(실제 견적이 아님).
