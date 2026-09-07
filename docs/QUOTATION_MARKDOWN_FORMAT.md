# Quotation Markdown Format

`sample_quotes/QUOTE-*.md`의 표준 입력 포맷을 정의한다. `sample_specs/SPEC-*.md`가
"장비 사양"의 사람이 직접 관리하는 원본 소스 문서인 것과 대칭으로, 이 포맷은
"장비 견적"의 원본 소스 문서다 — `agent/spec_retriever.py`류의 RAG 인덱서가
아니라 향후 견적 분석 엔진(Phase 5, `agent/quote_parser.py` 예정)이 파싱할
대상이다. 이 문서는 데이터 구조 설계(Phase 3) 산출물이며, 파서 구현(Phase 5)
이전에 확정한다.

## 왜 Markdown이고 왜 SPEC과 같은 스타일인가

- `sample_specs/*.md`와 동일한 이유(diff 가능, 사람이 직접 검수/수정 가능,
  이미 이 저장소의 표준 데이터 포맷)로 Markdown을 그대로 쓴다.
- **숫자 계산(Quantity × Unit Price, Subtotal, VAT, Grand Total)은 이 문서에
  적힌 값을 코드가 그대로 재계산해 검증하는 대상이지, LLM이 읽고 계산하는
  대상이 아니다** (요청서 5단계 핵심 원칙). 그래서 표 형식은 사람이 검산하기
  쉽도록 "Quantity/Unit Price/Amount"를 전부 명시적으로 나열한다 — Amount가
  Quantity×Unit Price와 다르면 그 자체가 "계산 오류 테스트 케이스"가 된다
  (아래 "계산 오류 테스트 데이터" 절 참고).

## SPEC ↔ QUOTE 연결 규칙

```text
sample_specs/SPEC-001.md  ↔  sample_quotes/QUOTE-001.md
sample_specs/SPEC-002.md  ↔  sample_quotes/QUOTE-002.md
...
sample_specs/SPEC-100.md  ↔  sample_quotes/QUOTE-100.md
```

- 파일명 번호가 곧 연결 키다 — 이 저장소가 이미 SPEC 파일명을 후보 식별자로
  쓰고 있으므로(`agent/candidate_matcher.py`, `tests/regression_lib.py`의
  `candidate_spec_ids`) 새 필드나 별도 매핑 테이블을 추가하지 않는다.
- 한 SPEC에 견적이 여러 개(동일 장비, 서로 다른 구성 — 요청서 4단계 Case H)
  존재해야 하는 경우에만 `QUOTE-001-B.md`처럼 접미사를 붙인다. 접미사 없는
  파일(`QUOTE-001.md`)이 항상 존재해야 하는 "기본 견적"이다.
- 모든 SPEC이 반드시 QUOTE을 가질 필요는 없다(요청서 10단계 테스트 13:
  "견적 없는 장비 처리") — 이 경우 QUOTE 파일이 아예 없으며, 파서는 이를
  UNKNOWN이 아니라 "이 장비의 견적 정보가 없음"으로 명확히 구분해야 한다.

## 전체 구조

```markdown
# Equipment Quotation

## General
## Equipment
## Options
## Additional Cost
## Excluded Items
## Commercial Terms
## Total
## Notes
```

### 1. General

```markdown
## General

- Manufacturer: ConfocalTech
- Model: CT-100
- Linked Specification: SPEC-053.md
- Quote No.: Q-2026-0053
- Quote Date: 2026-03-15
- Currency: KRW
```

- `Manufacturer`/`Model`은 반드시 연결된 SPEC의 값과 문자 그대로 일치해야
  한다(다르면 SPEC↔QUOTE 연결이 잘못됐다는 신호) — 향후 검증 스크립트가
  이 일치 여부를 자동으로 확인한다(SPEC 쪽 `scripts/audit_sample_specs.py`와
  같은 원칙의 QUOTE판, Phase 4에서 작성).
- `Linked Specification`은 사람이 읽을 명시적 교차 참조이며, 실제 연결은
  위 "SPEC ↔ QUOTE 연결 규칙"의 파일명 규칙이 1차 소스다(이 필드는 이중
  확인용).
- `Currency`는 항상 명시한다 — 생략 시 파서가 추측하지 않고 UNKNOWN으로
  둔다.

### 2/3. Equipment / Options

```markdown
## Equipment

| Item | Quantity | Unit Price | Amount |
|---|---|---|---|
| ConfocalTech CT-100 (Main Unit) | 1 | 150,000,000 | 150,000,000 |

## Options

| Item | Quantity | Unit Price | Amount |
|---|---|---|---|
| PLC Interface Module | 1 | 5,000,000 | 5,000,000 |
| Extended Warranty (+1yr) | 2 | 4,000,000 | 8,000,000 |
```

- 숫자는 천 단위 콤마(`,`)를 허용한다 — 파서(Phase 5)가 콤마를 제거하고
  숫자로 변환한다(`agent/units.py`와 동일하게 정규식 기반, LLM 미사용).
  통화 기호(₩, $)는 넣지 않는다 — `General`의 `Currency` 하나로 문서 전체의
  통화를 결정한다(행마다 다른 통화가 섞이는 경우는 지원하지 않는다).
- `Amount`는 반드시 `Quantity × Unit Price`와 일치해야 "정상" 데이터다.
  일치하지 않는 행은 계산 오류 테스트용으로만 의도적으로 만든다(아래 절).
- 옵션이 없는 장비는 `## Options` 섹션 자체를 생략하거나(권장) 본문에
  `- None`만 남긴다 — 파서는 두 경우 모두 "옵션 없음"으로 처리한다.

### 4. Additional Cost

```markdown
## Additional Cost

| Item | Amount |
|---|---|
| Installation | 10,000,000 |
| Commissioning | 5,000,000 |
| Training | 3,000,000 |
| Spare Parts | 2,000,000 |
```

- `Item`은 자유 텍스트이지만(요청서 예시: Installation/Commissioning/
  Training/Spare Parts/기타), 파서(Phase 5)가 의미 분류(본체/옵션/부대비용)를
  LLM에게 맡길 항목이 바로 이 섹션이다 — 금액 자체(코드가 합산)와 "이 항목이
  무엇을 뜻하는지 설명"(LLM)을 분리하는 설계 원칙(요청서 5단계)이 여기서
  적용된다.
- 별도 비용이 전혀 없는 견적은 이 섹션을 생략한다(빈 표를 강제하지 않는다).

### 5. Excluded Items

```markdown
## Excluded Items

- Site preparation (customer responsibility)
- Network/PLC integration on customer production line
- Consumables beyond the included spare parts kit
```

- 항목이 없으면(모두 포함된 견적) 섹션 자체를 생략하거나 `- None`만 남긴다.
- 이 목록은 금액이 없는 서술 항목이다 — Phase 7의 "제외 항목 생성 금지"
  원칙에 따라 파서는 여기 없는 항목을 "제외됨"이라고 만들어내지 않는다.

### 6. Commercial Terms

```markdown
## Commercial Terms

- Discount: 3% (or a fixed amount, e.g. 5,000,000)
- Payment: 30% advance, 60% on delivery, 10% after acceptance
- Delivery: 12 weeks after order
- Warranty: 12 months parts and labor
- VAT: 10% (or "Included", or "Not applicable")
```

- `Discount`는 퍼센트(`3%`) 또는 정액(`5,000,000`) 둘 다 허용한다 — 파서가
  `%` 포함 여부로 구분한다(둘 다 원칙적으로 지원, `agent/units.py`의 비율
  파싱과 동일 패턴).
- `VAT`는 세 가지 표현을 허용한다: 퍼센트(`10%`), `Included`(총액에 이미
  포함), `Not applicable`(면세/해당 없음 — 요청서 4단계 Case E "VAT 별도"와
  대비되는 케이스). 생략하면 UNKNOWN이며 코드가 임의로 10%를 가정하지 않는다.

### 7. Total

```markdown
## Total

| Item | Amount |
|---|---|
| Equipment Subtotal | 150,000,000 |
| Options Subtotal | 13,000,000 |
| Additional Cost Subtotal | 20,000,000 |
| Discount | -5,000,000 |
| Subtotal (before VAT) | 178,000,000 |
| VAT (10%) | 17,800,000 |
| Grand Total | 195,800,000 |
```

- 이 섹션의 모든 값은 **코드가 위 Equipment/Options/Additional Cost/
  Commercial Terms 섹션에서 재계산해 검증하는 대상**이다(Phase 5). 문서에
  적힌 `Total` 값과 코드 재계산 값이 다르면 "계산 오류"로 검출한다 — 이
  섹션이 있다고 해서 코드가 이 값을 그냥 신뢰하고 넘어가지 않는다.
- `Discount`가 금액이면 음수로 표기(`-5,000,000`)해 부호만으로 가산/차감을
  구분할 수 있게 한다.
- 행 이름(`Item` 열의 문자열)은 이 문서에 나열된 것과 정확히 일치시킨다 —
  파서가 라벨 문자열 매칭으로 각 행을 찾는다(`agent/candidate_matcher.py`가
  SPEC 라벨을 매칭하는 방식과 동일한 원칙).

### 8. Notes

```markdown
## Notes

SAMPLE/TEST DATA — 실제 업체의 공식 견적이 아닙니다. 개발 및 테스트 목적으로만
사용됩니다. 가격은 시장가격이나 적정가격을 나타내지 않습니다.
```

- **모든 QUOTE 파일은 이 고지 문구를 반드시 포함한다** — 요청서 4단계
  "가격 생성 원칙"(실제 업체 공식 견적처럼 표현 금지)을 데이터 자체에
  새겨 넣는다. UI/Agent 답변이 이 출처를 표시할 때도 이 고지를 함께 노출할
  수 있도록, 문구 자체를 파싱 가능한 고정 위치(`## Notes` 첫 줄)에 둔다.

## 계산 오류 테스트 데이터 (Case K)

요청서 4단계는 "계산 오류가 있는 테스트용 데이터"를 요구하되 "일반 Sample과
구분하여 관리"하라고 명시한다. 이 저장소에서는:

```text
sample_quotes/QUOTE-001.md ~ QUOTE-100.md        <- 정상 데이터(계산 항상 일치)
sample_quotes/error_cases/QUOTE-ERR-001.md ...    <- 의도적 계산 오류 데이터
```

- `error_cases/` 하위 파일은 **SPEC과 연결하지 않는다**(파일명이 `QUOTE-ERR-*`
  형태로 `QUOTE-\d+` 패턴과 겹치지 않아, SPEC↔QUOTE 자동 연결 로직이 절대
  이 파일들을 정상 후보로 집어 들지 않는다 — 정규식/glob 패턴을 분리하는
  것만으로 충분하며 별도 allowlist가 필요 없다).
  각 파일 맨 위에 어떤 오류가 의도적으로 심어졌는지 주석으로 남긴다(예:
  "Amount != Quantity × Unit Price", "Grand Total이 VAT 반영 누락" 등).
- Phase 5의 계산 검증 유닛 테스트가 이 디렉터리를 입력으로 삼아 "오류가
  실제로 검출되는가"를 확인한다(정상 데이터로는 오류 미검출을 증명할 수
  없으므로 이 파일들이 반드시 필요하다).

## Amount 필드가 없는 예외 케이스

Excluded Items처럼 원래 금액이 없는 섹션 외에, `## Additional Cost`의
`Item` 자체가 없는(전혀 부대비용이 없는) 경우처럼 "섹션 생략 = 정보 없음"과
"섹션은 있지만 행이 0개 = 확인했지만 없음"을 구분해야 하는 지점이 향후
Phase 5에서 명확히 정의될 것이다. 이 문서(Phase 3)는 정상 케이스의 포맷만
확정하며, 파서의 결측값 처리 세부 규칙은 Phase 5에서 구현과 함께 기록한다.
