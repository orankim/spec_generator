# Specification Markdown Format

`renderers/markdown_renderer.render_markdown()`이 생성하고, `converters/markdown_to_spec.markdown_to_spec()`이
역파싱하는 표준 포맷이다. **라벨-필드 매핑의 유일한 소스는 `renderers/common.py`의 `build_sections()`/
`build_notes_section()`이며, 이 문서는 그 결과를 사람이 읽을 수 있게 옮겨 적은 것이다.** 실제 렌더링
결과와 이 문서가 어긋나면 코드가 맞다 — 문서를 갱신해야 한다.

`markdown_to_spec()`은 **이 표준 포맷만** 대상으로 한다. 임의의 마크다운 문서를 일반적으로 파싱하지
않으며, 표준 포맷에 없는 라벨/섹션은 조용히 건너뛴다(에러를 내지 않는다).

빈 스켈레톤(값이 전부 채워지지 않은 상태)이 필요하면 `templates/specification.md`를 참고한다.
전체 필드/타입/단위/Status 의미에 대한 상세 설명은 `docs/SPECIFICATION_SCHEMA.md`를 참고한다.

## 전체 구조

```markdown
# {Title}

## 1. General Specification
## 2. Inspection Target
## 3. Inspection Requirements
## 4. Measurement Performance
## 5. Spatial Performance
## 6. Optical System
## 7. Defect Inspection
## 7-1. Inspection Performance   <- SpecificationSchema에 이미 존재하는 필드라 유지 (표준 13개 섹션 목록 외 레거시)
## 8. System Configuration
## 9. Interfaces / Data
## 10. Environment
## 11. Safety
## 12. Validation / Acceptance   <- SpecificationSchema에는 저장되지 않는 파생 정보
## 13. Requirement Compliance    <- SpecificationSchema에는 저장되지 않는 파생 정보
## 14. Sources / Notes
```

## 두 가지 표 형식

**A. 수치 성능 필드가 있는 섹션** (Measurement Performance, Spatial Performance,
Inspection Performance, Defect Inspection) — `SourcedNumber` 필드를 담는다.

```markdown
| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Accuracy | um | 0.5 | VERIFIED | vendor_spec.pptx, slide 4 |
| Repeatability | um | 0.3 | INFERRED | - |
| Reproducibility | - | UNKNOWN | UNKNOWN | - |
```

- `Specification`이 `UNKNOWN`이면 해당 `SourcedNumber.value`가 `None`이라는 뜻이다.
- `Status`는 `USER_DEFINED` / `VERIFIED` / `INFERRED` / `UNKNOWN` 중 하나다 (의미는
  `docs/SPECIFICATION_SCHEMA.md` "Status 정의" 절 참고).
- `Source`는 근거 문서/위치를 사람이 읽을 요약으로 표시한다 (예: `vendor_spec.pptx, slide 4`,
  `datasheet.pdf, p.12`). 근거가 없으면 `-`.
- 이 표는 **Requirement와 비교하지 않는다** — 요구사항 대비 PASS/FAIL은 별도의
  "13. Requirement Compliance" 섹션에서만 다룬다 (Requirement/Specification 혼동 금지 원칙).

**B. 그 외 섹션** (서술/분류형 필드, `SourcedNumber`가 아닌 필드)

```markdown
| Item | Specification |
|---|---|
| Equipment Name | XXX |
| Manufacturer | UNKNOWN |
```

## 12. Validation / Acceptance 섹션

`SpecificationSchema`에는 저장되지 않는 **파생 정보**다. `agent.spec_validator.validate_specification()`의
결과(`ValidationResult`)를 렌더링 시점에 표로 보여줄 뿐이며, `markdown_to_spec()`으로 역파싱할 때도
이 섹션은 무시한다(스키마에 되돌릴 필드가 없으므로).

```markdown
| Level / Field | Message |
|---|---|
| [WARNING] measurement_performance.accuracy_um | 값은 있는데 status가 UNKNOWN입니다(근거 불명확). |
```

## 13. Requirement Compliance 섹션

역시 `SpecificationSchema`에는 저장되지 않는 파생 정보다. `RequirementSchema`가 주어졌을 때만
`agent.spec_validator.build_compliance_report()`가 계산하며, 주어지지 않으면 섹션 본문은
"No requirement provided for comparison." 한 줄만 남는다. 비교 로직이 정의된 항목(Accuracy,
Resolution, Minimum Defect Size)만 표에 나타난다 — 비교 기준이 없는 필드까지 채워서 표를
불필요하게 늘리지 않는다.

```markdown
| Item | Unit | Requirement | Specification | Result | Reason |
|---|---|---|---|---|---|
| Accuracy | um | 1.0 | 0.5 | PASS | 0.5um <= 1.0um |
| Resolution | um | UNKNOWN | 0.1 | UNKNOWN | 이 항목에 대한 요구사항이 지정되지 않았습니다. |
```

`markdown_to_spec()`은 이 섹션도 무시한다.

## 14. Sources / Notes 섹션

```markdown
| Item | Specification |
|---|---|
| Note | 첫 번째 노트 |
| Note | 두 번째 노트 |
| Needs Confirmation | measurement_performance.accuracy_um, ... |
| Sources | vendor_spec.pptx, another_doc.pptx |
```

`Note`/`Assumption`은 항목 하나당 행 하나(라벨이 여러 번 반복)이고, `Needs Confirmation`/`Sources`는
리스트 전체가 콤마로 join된 행 하나다 — 서로 다른 파싱 규칙이 필요하므로 혼동하지 않도록 주의.

## UNKNOWN 값

`SpecificationSchema`의 어떤 필드든 값이 `None`이면 렌더러는 항상 문자열 `UNKNOWN`을 출력한다.
빈 문자열이나 공백으로 표시하지 않는다 — "값이 없다"와 "표 셀이 비어 있다(파싱 실패)"를 구분하기 위함이다.
`markdown_to_spec()`은 `UNKNOWN` 문자열을 다시 `None`으로 되돌린다.

## 예시

```markdown
# Electrode Inspection Equipment Specification

## 1. General Specification

| Item | Specification |
|---|---|
| Equipment Name | 전극 두께 검사기 |
| Manufacturer | UNKNOWN |
| Model | UNKNOWN |
| Measurement Principle | laser triangulation |

## 4. Measurement Performance

| Item | Unit | Specification | Status | Source |
|---|---|---|---|---|
| Measurement Range | - | UNKNOWN | UNKNOWN | - |
| Resolution | - | UNKNOWN | UNKNOWN | - |
| Accuracy | um | 0.5 | VERIFIED | vendor_spec.pptx |
| Repeatability | um | 0.3 | INFERRED | - |
| Reproducibility | - | UNKNOWN | UNKNOWN | - |

## 13. Requirement Compliance

| Item | Unit | Requirement | Specification | Result | Reason |
|---|---|---|---|---|---|
| Accuracy | um | 1.0 | 0.5 | PASS | 0.5um <= 1.0um |
```

완전한 예시 하나는 `docs/examples/example_specification.json` (Specification JSON) +
그것을 렌더링한 Markdown/HTML을 참고한다.
