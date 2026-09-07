# Equipment Quotation (INTENTIONAL ERROR — TEST DATA ONLY)

<!-- INJECTED ERROR: Discount(-8,000,000)이 표에 있지만 Grand Total(99,000,000)이 이를 반영하지 않음 (Subtotal 90,000,000 + VAT 9,000,000 = 99,000,000이어야 하는데, Discount 반영 전 Subtotal 98,000,000 + VAT 9,800,000로 계산된 값 107,800,000도 아니고 그냥 할인 무시) -->

## General

- Manufacturer: TestVendor
- Model: TV-004
- Linked Specification: (none — error_cases/는 SPEC과 연결하지 않는다)
- Quote No.: Q-ERR-004
- Quote Date: 2026-01-01
- Currency: KRW

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

## Notes

SAMPLE/TEST DATA — 실제 업체의 공식 견적이 아닙니다. 이 파일은 계산 오류 검출 로직을 검증하기 위해 의도적으로 잘못된 숫자를 담고 있습니다(실제 견적이 아님).
