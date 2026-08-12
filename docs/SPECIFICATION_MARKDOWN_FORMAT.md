# Specification Markdown Format

`renderers/markdown_renderer.render_markdown()`이 생성하고, `converters/markdown_to_spec.markdown_to_spec()`이
역파싱하는 표준 포맷이다. **라벨-필드 매핑의 유일한 소스는 `renderers/common.py`의 `build_sections()`/
`build_notes_section()`이며, 이 문서는 그 결과를 사람이 읽을 수 있게 옮겨 적은 것이다.** 실제 렌더링
결과와 이 문서가 어긋나면 코드가 맞다 — 문서를 갱신해야 한다.

`markdown_to_spec()`은 **이 표준 포맷만** 대상으로 한다. 임의의 마크다운 문서를 일반적으로 파싱하지
않으며, 표준 포맷에 없는 라벨/섹션은 조용히 건너뛴다(에러를 내지 않는다).

## 전체 구조

```markdown
# {Title}

## 1. Equipment
## 2. Inspection Target
## 3. Inspection Requirements
## 4. Measurement Performance
## 5. Spatial Performance
## 6. Optical System
## 7. Defect Inspection
## 8. Inspection Performance   <- SpecificationSchema에 이미 존재하는 필드라 유지 (요청 목록엔 없었음)
## 9. System Configuration
## 10. Interfaces / Data
## 11. Environment
## 12. Safety
## 13. Validation / Acceptance  <- SpecificationSchema에는 저장되지 않는 파생 정보 (아래 참고)
## 14. Sources / Notes
```

## 두 가지 표 형식

**A. 수치 성능 필드가 있는 섹션** (Measurement/Spatial/Inspection Performance, Defect Inspection)

```markdown
| Item | Unit | Requirement | Specification | Result |
|---|---|---|---|---|
| Accuracy | um | 1.0 | 0.5 | PASS |
| Repeatability | um | - | 0.3 | - |
```

- `Requirement`/`Result`가 `-`이면 "이 필드는 요구사항과 비교 대상이 아님"을 뜻한다 (요구사항 자체가
  없는 게 아니라, 이 필드에 대한 비교 로직이 아직 없다는 뜻. `renderers/common.py`의 `_cmp_le` 참고).
- `Specification`이 `UNKNOWN`이면 해당 `SourcedNumber` 필드의 `value`가 `None`이라는 뜻이다.
- `Result`는 `PASS` / `FAIL` / `UNKNOWN` 중 하나이며, `UNKNOWN`은 "요구사항은 있는데 실제 값이 없어서
  비교할 수 없음"을 뜻한다. **이 판정은 저장되지 않고 렌더링 시점에 매번 다시 계산된다.**

**B. 그 외 섹션** (서술/분류형 필드)

```markdown
| Item | Specification |
|---|---|
| Equipment Name | XXX |
| Manufacturer | UNKNOWN |
```

## Source 정보 보존

수치 필드 중 `source_type`이 있는 필드는 표 아래에 blockquote로 근거를 남긴다.

```markdown
> Source: vendor_spec.pptx — Accuracy
> Source: user_requirement — Repeatability
```

`Source:` 뒤 값이 `document`/`user_requirement`/`inferred`/`default` 중 하나면 `source_type`으로,
그 외(파일명 등)면 `source_type=document, source=<그 값>`으로 해석한다.

## 13. Validation / Acceptance 섹션

`SpecificationSchema`에는 저장되지 않는 **파생 정보**다. `agent.spec_validator.validate_specification()`의
결과(`ValidationResult`)를 렌더링 시점에 표로 보여줄 뿐이며, `markdown_to_spec()`으로 역파싱할 때도
이 섹션은 무시한다(스키마에 되돌릴 필드가 없으므로).

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

## 1. Equipment

| Item | Specification |
|---|---|
| Equipment Name | 전극 두께 검사기 |
| Manufacturer | UNKNOWN |
| Model | UNKNOWN |
| Measurement Principle | laser triangulation |

## 4. Measurement Performance

| Item | Unit | Requirement | Specification | Result |
|---|---|---|---|---|
| Measurement Range | - | - | UNKNOWN | UNKNOWN |
| Resolution | - | - | UNKNOWN | UNKNOWN |
| Accuracy | um | 1.0 | 0.5 | PASS |
| Repeatability | um | - | 0.3 | - |
| Reproducibility | - | - | UNKNOWN | UNKNOWN |

> Source: vendor_spec.pptx — Accuracy
> Source: user_requirement — Repeatability
```
