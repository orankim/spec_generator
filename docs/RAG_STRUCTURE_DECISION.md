# RAG 구조 결정 — SPEC과 QUOTE를 같은 검색 공간에 넣지 않는다

## 결정

**QUOTE 데이터(`sample_quotes/*.md`)는 Chroma(`chroma_db_specs`)에 인덱싱하지
않는다.** SPEC 검색(RAG, 의미 기반 유사도 검색)과 QUOTE 조회(파일명 기반 결정론적
직접 조회)는 서로 다른 메커니즘을 쓴다:

```text
사양 질문           -> agent.spec_retriever.retrieve_for_requirement()  (RAG, 의미 검색)
견적 질문           -> agent.quote_parser.load_quotations_for_spec()    (파일명 기반 직접 조회, 검색 아님)
사양 + 견적 질문     -> 위 둘을 순서대로: 먼저 SPEC 후보를 RAG로 찾고,
                        그 후보의 source_document(파일명)로 QUOTE를 직접 연결
```

## 왜 이렇게 했는가

1. **SPEC↔QUOTE 연결이 이미 결정론적이다.** `docs/QUOTATION_MARKDOWN_FORMAT.md`가
   정의한 대로 `QUOTE-NNN.md`는 파일명 번호로 `SPEC-NNN.md`와 1:1 연결된다. 후보
   장비(SPEC)가 이미 정해지면 그 견적은 "찾는" 게 아니라 "정해진 파일을 여는" 문제다
   — 의미 기반 유사도 검색이 필요한 지점이 아니다. 오히려 벡터 검색을 쓰면 엉뚱한
   견적이 top-k에 섞여 들어올 위험만 생긴다(요청서 6단계 "근거 오류: 장비 A의 사양을
   장비 B의 정보로 잘못 연결" 위험과 정확히 같은 종류의 문제).
2. **하나의 검색 공간에 섞으면 SPEC Retrieval 품질이 떨어질 위험이 있다.** SPEC은
   기술 사양(측정 범위/정확도/검사 항목)을, QUOTE는 상업 조건(가격/할인/납기)을
   담고 있어 임베딩 공간에서 서로 다른 의미 축을 가진다. 같은 컬렉션에 넣으면
   "두께 정확도 ±1um" 같은 질의가 가격표 chunk와 경쟁하게 되어 Phase 2에서 어렵게
   회복한 Recall(k_per_query=20, 97.6%)이 다시 흔들릴 수 있다 — 이미 Phase 1~2에서
   corpus 크기 증가만으로도 Recall이 눈에 띄게 떨어지는 것을 실측했으므로
   (`agent/spec_retriever.py` k_per_query 변경 이력 참고), 이질적인 데이터를 더
   섞는 결정은 특히 조심스럽게 접근해야 한다.
3. **금액 계산은 코드가 전담한다는 원칙(요청서 5단계)과도 맞는다.** QUOTE를 RAG로
   "검색된 chunk 텍스트"로 다루면, 표의 일부 행만 chunk로 쪼개져 검색될 위험이
   있다(예: "Options" 표만 검색되고 "Total" 표는 안 됨) — `agent.quote_parser`는
   항상 파일 전체를 구조화해서 읽으므로 이런 부분 검색 문제가 원천적으로 없다.

## 그래서 실제로 무엇이 바뀌는가

`agent/pipeline.py`의 두 진입점이 이 결정을 그대로 구현한다:

- `analyze_with_quotes()`: 기존 `retrieve_and_generate()`(SPEC RAG) + `candidate_matcher`
  (Hard Requirement 판정)를 손대지 않고 그대로 실행한 뒤, 도출된 각 후보의
  `source_document`로 `quote_parser.load_quotations_for_spec()`을 호출한다 — RAG는
  SPEC에만 쓰이고, QUOTE 연결은 그 결과에 얇게 이어붙는다.
- `analyze_named_equipment()`: 사용자가 장비명을 직접 언급한 경우(예: "ES-200의
  견적") RAG를 아예 거치지 않는다 — `agent/equipment_lookup.py`가 파일명 매칭으로
  SPEC을 확정하고, 그 확정된 spec_id로 QUOTE를 직접 연다.

## 향후 재검토가 필요한 경우

만약 나중에 "이 견적서에 이런 조건이 있었나?" 같은 **견적 문서 자체의 자유 텍스트
검색**(예: Commercial Terms의 서술 조건으로 견적을 찾는 기능)이 필요해지면, 그때는
QUOTE 전용의 **별도 Chroma 컬렉션**을 새로 만드는 것을 권장한다(SPEC 컬렉션과
공유하지 않음) — 이 문서의 핵심 결정(SPEC과 QUOTE를 같은 검색 공간에 넣지 않는다)은
유지한 채로 확장 가능하다.
