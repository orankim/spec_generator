# PPT 논리 슬라이드 구조

이 문서는 **실제 PPTX 파일이 아니라**, Specification JSON을 PPT로 표현할 때 어떤
논리적 슬라이드 구성을 따르는지에 대한 문서다. 회사 지정 PPT 템플릿은 사내 PC에서
`PPT_TEMPLATE_PATH` 환경변수로 연결하며(`docs/SPECIFICATION_SCHEMA.md`의 Design
Principles 참고), 이 저장소에는 회사 템플릿 파일 자체를 포함하지 않는다.

템플릿이 없을 때 `renderers/pptx_renderer._build_default_presentation()`이 즉석에서
만드는 기본 PPTX가 바로 이 구조를 그대로 구현한 것이다 — 문서와 코드가 어긋나면 코드
(`renderers/pptx_renderer.py`)가 맞다.

## 12개 논리 슬라이드

| # | 슬라이드 | 내용 | 데이터 소스 |
|---|---|---|---|
| 1 | Title | 설비명 + 문서 제목 | `equipment.name`, 렌더링 시 지정하는 `title` |
| 2 | General Specification | Equipment 섹션 전체 | `renderers/common.py`의 `build_sections()` id=`equipment` |
| 3 | Inspection Target / Requirements | 검사 대상 + 검사 조건 | id=`inspection_target`, `inspection_requirements` (섹션 2, 3) |
| 4 | Measurement Performance | 정확도/분해능/반복성 등 수치 성능 | id=`measurement_performance` (섹션 4) |
| 5 | Spatial Performance | 공간 해상도/FOV/작업거리 | id=`spatial_performance` (섹션 5) |
| 6 | Optical System | 광학계 구성 (해당 시) | id=`optical_system` (섹션 6) |
| 7 | Defect Inspection | 결함 검사 성능/종류 | id=`defect_detection`, `inspection_performance` (섹션 7, 7-1) |
| 8 | System Configuration | 시스템 구성/PC/전원 등 | id=`system_configuration` (섹션 8) |
| 9 | Interfaces / Data | PLC/MES/네트워크 연동 | id=`interfaces` (섹션 9) |
| 10 | Environment / Safety | 설치 환경 + 안전 규격 | id=`environment`, `safety` (섹션 10, 11) |
| 11 | Validation / Acceptance | 자동 검증 결과(PASS/FAIL/이슈 목록) + Requirement Compliance | `agent.spec_validator.validate_specification()`, `build_compliance_report()` (섹션 12, 13) |
| 12 | Sources / Notes | 노트/가정/확인 필요 항목/참고 문서 | id=`sources_notes` (섹션 14) |

기본 PPTX 구현(`_build_default_presentation()`)은 슬라이드 11을 "Validation / Acceptance"와
"Requirement Compliance" 두 장으로 나눠서 만든다(`_add_data_table_slide` +
`_add_compliance_slide`) — 논리 구조상 같은 그룹(12번째 항목: 검증/판정)이지만, 표 모양이
서로 달라 한 슬라이드에 억지로 합치지 않는다. 회사 템플릿이 두 내용을 한 슬라이드에
담고 싶다면 `PPTTemplateAdapter` 구현체에서 자유롭게 재배치할 수 있다
(`templates/adapters/ppt_template_adapter.py` 참고).

## 각 슬라이드가 지켜야 하는 원칙

- **필드-라벨 매핑은 `renderers/common.py`가 유일한 소스다.** 새 필드를 추가하거나
  라벨을 바꾸고 싶으면 `renderers/common.py`의 `build_sections()`만 고친다 — PPTX 전용
  매핑을 따로 만들지 않는다.
- **PPTX는 Markdown/HTML과 동일한 `SpecificationSchema`에서 독립적으로 생성된다.**
  PPTX -> AI -> PPTX나 Markdown -> PPTX -> Markdown 같은 라운드트립 변환은 하지 않는다
  (원본 데이터 손실/왜곡 위험). PPTX에서 마크다운으로 옮기고 싶다면
  `converters/pptx_to_markdown.py`(구조 추출 전용, Specification 파이프라인과는 별개)를
  사용한다.
- **회사 템플릿이 있으면 그 템플릿의 슬라이드 배치/디자인을 따른다.** 이 문서의 12개
  슬라이드는 "템플릿이 없을 때의 기본값"이자 "회사 템플릿이 최소한 담아야 하는 내용
  체크리스트"로 쓰기 위한 것이지, 템플릿 자체의 디자인을 강제하지 않는다.
