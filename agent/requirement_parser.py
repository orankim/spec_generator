"""
RequirementParser — 자연어 또는 조건 선택 UI 입력을 RequirementSchema로 변환한다.

두 입력 방식(자연어 / 조건 선택) 모두 최종적으로 동일한 RequirementSchema를
만들어내므로, 이후 파이프라인(Validator → Retriever → Generator)은 입력 방식과
무관하게 동일하게 동작한다 (기획안 9절).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from . import categorical_match, ollama_client, units
from .schemas import RequirementRange, RequirementSchema, RequirementValue

PARSE_PROMPT = """당신은 전극 검사기(인라인 계측 설비) 요구사항 분석 전문가입니다.
아래 [사용자 입력]을 읽고 요구사항을 구조화된 JSON으로 정리하세요.

반드시 지켜야 할 규칙:
- 사용자가 명시적으로 말하지 않은 값은 절대로 추측하지 마세요. 반드시 null(또는 빈 배열)로 남기세요.
  예: 사용자가 정확도를 언급하지 않았다면 required_accuracy_um은 null이어야 합니다.
- inspection_items에는 사용자가 실제로 언급한 검사 항목만 담으세요. 사용자가 구체적인
  결함 이름(스크래치, 오염/이물, 파티클, 핀홀, 보이드, 코팅 불균일, 엣지 크랙 등)을
  말했다면 상위 개념(surface_defect 등)으로 뭉뚱그리지 말고 그 구체적인 이름을 그대로
  담으세요. 가능한 값: thickness, surface_defect, profile_3d, coating, edge_defect,
  scratch, contamination, particle, pinhole, void, coating_non_uniformity, coating_defect, edge_crack.
- measurement_method는 "비접촉/무접촉"이면 non_contact, "접촉식"이면 contact, 언급이 없으면 null로 두세요.
- measurement_principle은 레이저/OCT/간섭계/비전 중 사용자가 명시한 것만 채우고, 아니면 null로 두세요.
- "0~200 μm", "0-200um", "0 to 200 mm" 처럼 측정 범위가 언급되면 measurement_range에
  {{"min": 0, "max": 200, "unit": "um"}} 형태로 채우세요.
- "±1 μm 이하", "1um 이하 정확도" 처럼 정확도가 언급되면 accuracy에
  {{"value": 1.0, "unit": "um", "operator": "<="}} 형태로 채우세요(required_accuracy_um도 동일한 값으로 채우세요).

[사용자 입력]
{user_text}
"""


def parse_requirement_text(
    user_text: str,
    model: Optional[str] = None,
    host: Optional[str] = None,
) -> RequirementSchema:
    """자연어 요구사항 -> RequirementSchema (Ollama 구조화 출력 사용)."""
    prompt = PARSE_PROMPT.format(user_text=user_text)
    requirement = ollama_client.parse_structured(prompt, RequirementSchema, model=model, host=host)
    requirement.raw_text = user_text
    # LLM이 사용자가 언급하지 않은 검사 항목을 임의로 추가하는 경우(실제로 관찰됨 —
    # "표면 결함"을 언급하지 않았는데도 surface_defect가 채워짐)를 여기서만(최초
    # LLM 파싱 직후) 걸러낸다. 후속 질문 답변 라운드(existing_requirement 경로)에서는
    # 사용자가 직접 입력/수정한 inspection_items를 건드리면 안 되므로 다시 적용하지 않는다.
    requirement.inspection_items = _filter_hallucinated_items(requirement.inspection_items, user_text)
    # 세부 결함 이름(스크래치/오염 등)이 raw_text에 있는데 LLM이 상위 카테고리
    # (surface_defect 등)로 뭉뚱그렸거나 아예 놓쳤을 수 있으므로, 결정론적 추출로
    # 보강한다(문제2) — 세부 항목이 있으면 그 항목이 속한 상위 카테고리는
    # inspection_items에서 빼고 inspection_categories(검색 확장 전용)로 옮긴다.
    fine_items, categories = _extract_inspection_items_and_categories(user_text)
    for item in fine_items:
        if item not in requirement.inspection_items:
            requirement.inspection_items.append(item)
    for category in categories:
        if category in requirement.inspection_items:
            requirement.inspection_items.remove(category)
        if category not in requirement.inspection_categories:
            requirement.inspection_categories.append(category)
    # trust_llm_guess=False: 소형 LLM이 raw_text에 없는 값을 환각으로 채우는 경우가
    # 실제로 보고되었다(예: "전극 표면" -> material="양극", "1~500 μm" -> "0~500000",
    # 정확도를 언급하지 않았는데 accuracy=1.0 생성). LLM 결과를 신뢰하지 않고,
    # raw_text에 실제 증거가 있으면 그 값으로 덮어쓰고 증거가 없으면 LLM이 뭘
    # 채웠든 지운다 — "이 최초 파싱 결과"에 한해서만 결정론적 추출이 항상 이긴다.
    apply_deterministic_extraction(requirement, trust_llm_guess=False)
    return requirement


# ==========================================
# 검사 항목 hallucination 방지 — LLM이 사용자가 말하지 않은 검사 항목을 임의로
# 추가하지 못하게 raw_text에 실제 근거(키워드)가 있는지 확인한다.
#
# "thickness"는 이 앱의 도메인(전극 검사기)에서 가장 기본적인 검사 항목이고,
# 사용자가 보고한 실제 사례("0~200 μm 측정 범위와 ±1 μm 이하 정확도가 필요한 전극
# 검사기를 찾아줘.")에서도 리터럴 키워드("두께") 없이 LLM이 thickness를 채운 것
# 자체는 문제로 지적되지 않았다(오히려 후속 흐름에서 정상 전제로 쓰임) — 그래서
# thickness는 이 필터에서 제외하고, 텍스트 근거 없이 추가되기 쉬운 나머지 항목
# (surface_defect 등)만 걸러낸다.
# ==========================================
_INSPECTION_ITEM_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    # 구체적 결함 이름 없이 포괄적으로만 언급된 경우에 쓰는 상위 카테고리 키워드
    # (구체적 이름은 아래 _FINE_DEFECT_ITEM_KEYWORDS가 별도로 다룬다 — 문제2).
    # 바레(qualifier 없는) "결함"/"defect"는 넣지 않는다 — 이 corpus의 Defect
    # Types 표기는 "Edge Defect"/"Coating Defect"처럼 다른 canonical item의
    # 이름에도 "Defect"가 포함되어 있어, 바레 키워드로는 "Edge Defect와 Edge
    # Crack을 검출"처럼 edge_defect만 요구한 문장에서도 surface_defect가 잘못
    # 함께 잡히는 문제가 실제로 발견됐다(T009 회귀 테스트로 확인). "표면"/
    # "surface" 한정어가 있을 때만 surface_defect로 인정한다.
    "surface_defect": ("표면 결함", "표면결함", "surface defect", "surface_defect"),
    "profile_3d": ("3d", "프로파일", "profile", "형상", "높이"),
    "coating": ("코팅", "coating", "도포", "loading"),
    "edge_defect": ("엣지", "edge", "가장자리", "버", "burr"),
}
# 세부 결함 이름(canonical item) — 사용자가 구체적인 결함 종류를 언급하면 상위
# 카테고리(surface_defect 등) 하나로 뭉개지 않고 그 세부 항목을 그대로 담는다
# (실사용자 보고 문제2: "스크래치와 오염" -> inspection_items=["scratch",
# "contamination"]이어야 하는데 surface_defect 하나로 합쳐져 후보 장비가 둘 중
# 하나만 지원해도 PASS로 잘못 판정될 위험이 있었다).
_FINE_DEFECT_ITEM_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "scratch": ("스크래치", "긁힘", "scratch"),
    "contamination": ("오염", "이물", "contamination", "contaminant"),
    "particle": ("파티클", "입자", "particle"),
    "pinhole": ("핀홀", "핀 홀", "pin hole", "pinhole"),
    "void": ("보이드", "공극", "void"),
    "coating_non_uniformity": (
        "코팅 불균일", "코팅불균일", "coating non-uniformity", "coating nonuniformity", "coating non uniformity",
    ),
    "edge_crack": ("엣지 크랙", "엣지크랙", "edge crack"),
    "coating_defect": ("코팅 결함", "코팅결함", "coating defect"),
}
# 세부 항목이 속하는 상위 카테고리 — RequirementSchema.inspection_categories(검색
# 확장 전용)에만 쓰고, 세부 항목이 이미 있으면 그 상위 카테고리를 inspection_items
# (Hard Requirement 판정 대상)에는 넣지 않는다.
_FINE_ITEM_CATEGORY: Dict[str, str] = {
    "scratch": "surface_defect",
    "contamination": "surface_defect",
    "particle": "surface_defect",
    "pinhole": "surface_defect",
    "coating_non_uniformity": "coating",
    "coating_defect": "coating",
}


def _extract_inspection_items_and_categories(text: str) -> Tuple[List[str], List[str]]:
    """
    raw_text에서 검사 항목을 결정론적으로 뽑는다. (items, categories)를 반환한다.
    세부 결함 이름이 있으면 그 세부 canonical item을 items에 담고, 그 세부
    항목이 속한 상위 카테고리는 categories에만 넣는다(items에는 넣지 않음 —
    문제2). thickness는 raw_text에 "두께"/"thickness" 키워드가 있을 때만
    담는다(과거에는 무조건 신뢰했으나, "3D Profile 검사기를 찾아줘"처럼 다른
    항목이 명시적으로 언급된 문장에서도 thickness가 끼어드는 문제3의 근본
    원인이었다 — 이 함수 자체는 이제 근거 없이 thickness를 추가하지 않는다.
    "아무 항목도 언급되지 않은 모호한 문장"에서 thickness를 기본값으로 쓰는
    정책은 _filter_hallucinated_items()에서 별도로 처리한다).
    """
    text_lower = text.lower()
    items: List[str] = []
    categories: List[str] = []
    covered_families: set = set()

    if any(kw in text for kw in _THICKNESS_KEYWORDS):
        items.append("thickness")
        if "코팅 두께" in text_lower or "coating thickness" in text_lower or "코팅두께" in text_lower:
            covered_families.add("coating")
            if "coating" not in categories:
                categories.append("coating")

    for item, keywords in _FINE_DEFECT_ITEM_KEYWORDS.items():
        if any(kw.lower() in text_lower for kw in keywords):
            items.append(item)
            family = _FINE_ITEM_CATEGORY.get(item)
            if family:
                covered_families.add(family)
                if family not in categories:
                    categories.append(family)

    for item, keywords in _INSPECTION_ITEM_KEYWORDS.items():
        if item in covered_families:
            continue
        if any(kw.lower() in text_lower for kw in keywords):
            items.append(item)

    return items, categories


def _filter_hallucinated_items(items: list, raw_text: str) -> list:
    """
    raw_text에 해당 검사 항목을 가리키는 키워드가 전혀 없으면 그 항목을 제거한다.
    키워드 목록이 없는(알 수 없는) 항목은 안전하게 그대로 유지한다(과도한
    필터링으로 정당한 항목까지 지우지 않기 위함).

    thickness는 특별 취급한다: 리터럴 키워드("두께"/"thickness")가 있으면 당연히
    유지하고, 없더라도 raw_text에 다른 구체적 검사 항목 근거가 "전혀" 없을 때는
    이 앱의 기본 검사 항목으로 보고 유지한다(실사용자 사례: "0~200 μm 측정
    범위와 ±1 μm 이하 정확도가 필요한 전극 검사기를 찾아줘."처럼 항목을 특정하지
    않은 질문). 하지만 raw_text에 다른 항목이 명시적으로 언급됐다면(예: "3D
    Profile 검사기") 그 근거 없이 thickness를 끼워 넣지 않는다(문제3: "3D
    Profile"이 thickness로 잘못 파싱되는 버그의 원인이었다).

    안전장치: 필터링 결과 inspection_items가 통째로 비어버리면(raw_text가 짧은
    placeholder이거나 키워드 사전에 없는 표현만 쓰인 경우 등) 필터링 자체를
    신뢰할 수 없다는 뜻이므로 원본 목록을 그대로 유지한다 — "전부 삭제"가
    "일부 오탐 유지"보다 더 나쁜 실패이기 때문이다.
    """
    text_lower = (raw_text or "").lower()
    all_item_keywords: Dict[str, Tuple[str, ...]] = {**_FINE_DEFECT_ITEM_KEYWORDS, **_INSPECTION_ITEM_KEYWORDS}
    has_other_item_evidence = any(
        any(kw.lower() in text_lower for kw in keywords) for keywords in all_item_keywords.values()
    )
    filtered = []
    for item in items:
        if item == "thickness":
            if any(kw in raw_text for kw in _THICKNESS_KEYWORDS) or not has_other_item_evidence:
                filtered.append(item)
            continue
        keywords = all_item_keywords.get(item)
        if keywords is None or any(kw.lower() in text_lower for kw in keywords):
            filtered.append(item)
    if items and not filtered:
        return items
    return filtered


def requirement_from_selection(selection: Dict[str, Any]) -> RequirementSchema:
    """
    조건 선택 UI(체크박스/드롭다운 등)에서 넘어온 값을 RequirementSchema로 변환한다.
    LLM을 거치지 않는 결정론적 매핑이며, selection의 키는 RequirementSchema 필드와
    1:1로 대응하도록 UI에서 구성한다 (예: {"target": {...}, "inspection_items": [...]}).
    """
    requirement = RequirementSchema(**selection)
    apply_deterministic_extraction(requirement)
    return requirement


# ==========================================
# 결정론적(코드 기반) 수치 추출 — LLM 결과와 무관하게 raw_text에서 직접 뽑는다.
#
# 배경: 소형 LLM(예: qwen2.5:3b)은 "0~200 μm 측정 범위와 ±1 μm 이하 정확도가
# 필요한 전극 검사기를 찾아줘." 같은 문장에서 measurement_range/accuracy를
# 놓치는 경우가 실제로 관찰되었다. 이 값들은 이후 후보 장비를 PASS/FAIL로
# 비교하는 hard requirement로 쓰이므로(agent.units.evaluate_hard_requirements),
# LLM의 자연어 이해에만 의존하지 않고 agent.units의 정규식/단위 파싱으로
# 직접 재확인한다 — 이미 채워진 값(사용자가 조건 선택 UI로 명시했거나 LLM이
# 이미 채운 값)은 덮어쓰지 않는다(LLM이 맞게 채웠다면 그 값을 신뢰).
# ==========================================
_ACCURACY_KEYWORDS: Tuple[str, ...] = ("정확도", "accuracy")
_RESOLUTION_KEYWORDS: Tuple[str, ...] = ("분해능", "resolution")
# "3 μm 이하 크기의 스크래치와 오염을 검출할 수 있는..."처럼 "결함"이라는 단어
# 자체는 없이 "~크기의 <결함이름>"으로만 표현되는 경우가 실제로 관찰되었다
# (문제4) — "결함 크기"류 키워드만으로는 이런 문장에서 최소 검출 결함 크기를
# 놓친다. "크기"/"크기의"/"이하 크기"를 추가해 값+단위가 바로 옆에 있는지로
# 판단한다("크기"라는 단어 자체는 흔하지만, 이 필드 전용 window 탐색에서만
# 쓰이므로 다른 필드(정확도/폭 등)와 충돌하지 않는다).
_DEFECT_KEYWORDS: Tuple[str, ...] = (
    "결함 크기", "결함크기", "defect size", "결함",
    "크기의", "크기 이하", "이하 크기", "이하의 크기", "크기",
)
_RANGE_KEYWORDS: Tuple[str, ...] = ("측정 범위", "측정범위", "measurement range", "범위", "최대")
_SPEED_KEYWORDS: Tuple[str, ...] = ("검사 속도", "검사속도", "속도", "speed")

_KEYWORD_WINDOW = 20


def _find_keyword_value(
    text: str, keywords: Tuple[str, ...]
) -> Optional[Tuple[float, str, Optional[str], int, int]]:
    """
    text에서 keywords 중 하나가 처음 등장하는 위치 주변(앞뒤 _KEYWORD_WINDOW자)에서
    가장 먼저(왼쪽부터) 발견되는 (value, unit)과 operator를 찾는다. 못 찾으면 None.
    "정확도 1um 이하"처럼 값이 키워드 뒤에 오는 경우와 "1um 이하 정확도"처럼 앞에
    오는 경우를 모두 지원한다. 매치된 (value, unit)의 절대 span(start, end)도 함께
    반환해, 호출부가 그 구간을 마스킹하고 다음 키워드를 이어서 찾을 수 있게 한다 —
    이렇게 하지 않으면 같은 숫자가 range/accuracy 등 여러 필드에 중복으로 잡힐 수
    있다.

    주의: window 안에 값+단위가 여러 개 있을 때 "keyword에 가장 가까운 값"을
    고르는 방식은(과거 시도) "200 μm 이하 측정 범위, ±1 μm 이하 정확도가
    필요해." 같은 문장에서 콤마로 분리된 다음 절(정확도 절)의 값이 "측정 범위"
    키워드에 더 가깝다는 이유로 잘못 선택되는 회귀를 실제로 일으켰다. 그래서
    항상 왼쪽부터 첫 매치를 쓰는 단순한 규칙으로 되돌린다 — width_mm처럼 이미
    다른 필드로 소비된 숫자는(아래 apply_deterministic_extraction에서) 호출
    전에 마스킹해 애초에 window 후보에서 배제하는 방식으로 처리한다.
    """
    for kw in keywords:
        idx = text.find(kw)
        if idx == -1:
            continue
        window_start = max(0, idx - _KEYWORD_WINDOW)
        window_end = idx + len(kw) + _KEYWORD_WINDOW
        window = text[window_start:window_end]
        found = units.parse_value_unit_with_span(window)
        if found is None:
            continue
        value, unit, rel_start, rel_end = found
        operator = units.parse_operator(window)
        return value, unit, operator, window_start + rel_start, window_start + rel_end
    return None


def _mask(text: str, start: int, end: int) -> str:
    return text[:start] + (" " * (end - start)) + text[end:]


# ==========================================
# target.material / target.width_mm 결정론적 추출
#
# 배경: LLM이 "음극 폭 5 mm의 두께를 0~300 μm 범위에서 ±0.5 μm 이하 정확도로
# 측정할 수 있는 검사기를 찾아줘." 같은 문장에서 measurement_range/accuracy는
# 정확히 뽑으면서도 material/width_mm는 null로 반환하는 회귀가 실제로 관찰되었다
# (기존 apply_deterministic_extraction()이 이 두 필드는 전혀 다루지 않았음).
#
# material은 "양극/음극/분리막" 3개 구체적 어휘만 대상으로 하는 단순 부분 문자열
# 매칭이라 오탐 위험이 낮다. 일부러 "전극"(범용어)은 후보에서 제외한다 — 이 앱
# 자체가 "전극 검사기"이므로 "전극"은 거의 모든 문장(예: "좋은 전극 검사기를
# 찾아줘")에 등장하는 도메인 명칭일 뿐 사용자가 특정 소재를 지정했다는 신호가
# 아니다(실제로 이걸 신호로 오인해 모호한 질문에서도 material을 잘못 채우는
# 회귀가 있었다). width_mm은 "폭"/"width" 키워드 근처의 값+단위를 찾는 기존
# _find_keyword_value() 패턴을 그대로 재사용한다.
#
# 다른 필드(measurement_range 등)와 달리, 이미 값이 있어도 raw_text에 명확한
# 근거(위 3개 구체적 소재명 중 하나)가 있으면 그 값을 우선한다(요청서 3절) — LLM이
# 이 두 필드를 잘못 채웠을 가능성까지 감안한 조치다. raw_text에서 못 찾으면 기존
# 값(LLM 결과 또는 None)을 그대로 유지한다.
# ==========================================
_MATERIAL_SPECIFIC_KEYWORDS: Tuple[str, ...] = ("음극", "양극", "분리막")
_WIDTH_KEYWORDS: Tuple[str, ...] = ("폭", "width")
_ADJACENT_NUMBER_RE = re.compile(r"^\s{0,2}\d")


def _extract_material(text: str) -> Optional[str]:
    for keyword in _MATERIAL_SPECIFIC_KEYWORDS:
        if keyword in text:
            return keyword
    return None


def _extract_width_mm_with_span(text: str) -> Optional[Tuple[float, int, int]]:
    """폭(width)을 raw_text에서 찾아 (mm 환산값, 매치 span)을 반환한다. 못 찾으면 None.
    반환하는 span은 호출부(apply_deterministic_extraction)가 이후 measurement_range
    등을 찾을 때 같은 숫자를 재사용하지 않도록 마스킹하는 데 쓰인다."""
    found = _find_keyword_value(text, _WIDTH_KEYWORDS)
    if found is not None:
        value, unit, _operator, start, end = found
        if unit is None:
            return None
        try:
            return units.convert(value, unit, "mm"), start, end
        except units.UnitError:
            return None

    # "폭"/"width" 키워드가 아예 없어도 "양극 10 mm의 thickness를..."처럼 재질명
    # 바로 뒤에 (공백만 사이에 두고) 숫자+길이단위가 바로 이어지면 그것이 폭을
    # 가리키는 경우가 실제로 관찰되었다. 다른 단어가 하나라도 끼어 있으면(예: "음극의
    # 두께를 5mm...") 폭이라고 확신할 수 없으므로, 재질명 바로 뒤에 숫자가 곧바로
    # 시작하는 경우로만 좁게 적용한다(오탐 방지).
    for material_kw in _MATERIAL_SPECIFIC_KEYWORDS:
        idx = text.find(material_kw)
        if idx == -1:
            continue
        after = text[idx + len(material_kw):]
        if not _ADJACENT_NUMBER_RE.match(after):
            continue
        candidate = units.parse_value_unit_with_span(after)
        if candidate is None:
            continue
        value, unit, rel_start, rel_end = candidate
        if unit is None or units.unit_dimension(unit) != "length":
            continue
        start = idx + len(material_kw) + rel_start
        end = idx + len(material_kw) + rel_end
        try:
            return units.convert(value, unit, "mm"), start, end
        except units.UnitError:
            return None
    return None


def _extract_width_mm(text: str) -> Optional[float]:
    found = _extract_width_mm_with_span(text)
    if found is None:
        return None
    value_mm, _start, _end = found
    return value_mm


def apply_deterministic_extraction(requirement: RequirementSchema, *, trust_llm_guess: bool = True) -> None:
    """
    raw_text에 담긴 구체적 수치(측정 범위/정확도/분해능/최소 결함 크기)와 검사
    대상/장비 조건(material/width_mm/inline_offline/measurement_method/
    measurement_principle)을 agent.units/agent.categorical_match의 정규식 매칭으로
    직접 뽑아 채운다.

    trust_llm_guess(기본 True, 기존 동작과 동일 — 하위호환):
      - True: 이미 값이 채워져 있으면 건드리지 않는다. 이 모드는 팔로우업 질문에
        대한 사용자의 직접 답변(agent/routes.py의 existing_requirement 경로,
        raw_text는 원문 그대로지만 필드 값은 사용자가 폼에 새로 입력한 것)을
        절대 덮어쓰거나 지우면 안 되는 곳에서 쓴다.
      - False: raw_text에서 찾은 값이 항상 이긴다 — 증거가 있으면 기존 값을
        덮어쓰고, 증거가 없으면 기존 값을 None으로 지운다. LLM(parse_requirement_text)
        직후 딱 한 번만 이 모드로 호출된다. 소형 LLM이 raw_text에 없는 값을
        환각으로 채우는 경우가 실제로 보고되었다(예: "전극 표면" -> material="양극",
        "1~500 μm" -> "0~500000"으로 둔갑, 정확도 미언급인데 accuracy=1.0 생성) —
        이 모드가 그 환각을 raw_text 재검증으로 걸러낸다.

    마지막에 RequirementSchema.sync_legacy_fields()를 호출해 레거시 float 필드
    (required_accuracy_um 등)도 함께 채워, RequirementValidator/기존 코드가
    그대로 동작하도록 한다.
    """
    text = requirement.raw_text
    if not text:
        return
    # "음극"/"양극"/"분리막"/"폭"/"정확도" 등 키워드 매칭은 전부 리터럴 부분 문자열
    # 비교(in)나 이를 기반으로 한 정규식이라 텍스트가 Unicode 정규화 형태(NFC/NFD)에
    # 따라 다르게 취급된다 — 예: 한글 "음극"이 완성형(NFC, 코드포인트 2개)이 아니라
    # 자모 분해형(NFD, 코드포인트 4개)으로 들어오면 소스 코드의 리터럴 "음극"(NFC)과
    # 바이트 단위로 달라 매칭이 조용히 실패한다. 사용자가 다른 앱에서 복사한 단어를
    # 문장 중간에 붙여넣는 경우 등 실제로 관찰되었다(재현: material만 빠지고
    # 폭/측정범위/정확도는 정상 추출됨 — 그 필드들은 숫자/단위 정규식이라 한글
    # 정규화와 무관해 영향을 받지 않았다). raw_text 필드 자체(사용자 원문 표시/감사
    # 목적)는 건드리지 않고, 매칭에만 쓰는 로컬 변수만 NFC로 정규화한다.
    text = unicodedata.normalize("NFC", text)

    material = _extract_material(text)
    if material is not None:
        requirement.target.material = material
    elif not trust_llm_guess:
        requirement.target.material = None

    width_span = _extract_width_mm_with_span(text)
    working_text = text
    if width_span is not None:
        width_mm, width_start, width_end = width_span
        requirement.target.width_mm = width_mm
        # width로 이미 소비된 숫자(예: "10 mm")가 뒤이은 measurement_range 탐색에서
        # 다시 후보로 잡히지 않도록 마스킹한다 — 그렇지 않으면 "폭 10 mm의 두께를
        # 최대 200 μm까지..."에서 "최대" 키워드 근처 윈도에 폭 값 "10 mm"까지 함께
        # 걸려 measurement_range가 폭 값을 잘못 재사용하는 회귀가 생긴다(실측됨).
        working_text = _mask(working_text, width_start, width_end)
    elif not trust_llm_guess:
        requirement.target.width_mm = None

    if requirement.measurement_range is None or not trust_llm_guess:
        range_result = units.parse_range_with_span(working_text)
        if range_result is not None:
            lo, hi, unit, start, end = range_result
            requirement.measurement_range = RequirementRange(min=lo, max=hi, unit=unit)
            # 이후 정확도 등을 찾을 때 범위의 숫자(예: "200")가 섞여 들어가지 않도록
            # 매치된 구간을 공백으로 마스킹한다(문자열 길이/위치는 그대로 유지).
            working_text = _mask(working_text, start, end)
        else:
            # "0~200 μm" 같은 완전한 범위가 없으면 "200 μm 이하"/"최대 200 μm"처럼
            # 상한만 있는 표현을 "측정 범위" 키워드 근처에서 찾는다(하한은 0으로 간주
            # — 두께/갭 계열 측정 범위는 관례상 0부터 시작하므로 안전한 가정이다).
            bound = _find_keyword_value(working_text, _RANGE_KEYWORDS)
            if bound is not None:
                value, unit, operator, start, end = bound
                if operator in (None, "<="):
                    requirement.measurement_range = RequirementRange(min=0.0, max=value, unit=unit)
                    working_text = _mask(working_text, start, end)
                elif not trust_llm_guess:
                    requirement.measurement_range = None
            elif not trust_llm_guess:
                requirement.measurement_range = None

    if (requirement.accuracy is None and requirement.required_accuracy_um is None) or not trust_llm_guess:
        found = _find_keyword_value(working_text, _ACCURACY_KEYWORDS)
        if found is not None:
            value, unit, operator, start, end = found
            requirement.accuracy = RequirementValue(value=value, unit=unit, operator=operator or "<=")
            working_text = _mask(working_text, start, end)
        elif not trust_llm_guess:
            requirement.accuracy = None
            requirement.required_accuracy_um = None

    if (requirement.resolution is None and requirement.required_resolution_um is None) or not trust_llm_guess:
        found = _find_keyword_value(working_text, _RESOLUTION_KEYWORDS)
        if found is not None:
            value, unit, operator, start, end = found
            requirement.resolution = RequirementValue(value=value, unit=unit, operator=operator or "<=")
            working_text = _mask(working_text, start, end)
        elif not trust_llm_guess:
            requirement.resolution = None
            requirement.required_resolution_um = None

    if (requirement.minimum_defect_size is None and requirement.minimum_defect_size_um is None) or not trust_llm_guess:
        found = _find_keyword_value(working_text, _DEFECT_KEYWORDS)
        if found is not None:
            value, unit, operator, start, end = found
            requirement.minimum_defect_size = RequirementValue(value=value, unit=unit, operator=operator or "<=")
            working_text = _mask(working_text, start, end)
        elif not trust_llm_guess:
            requirement.minimum_defect_size = None
            requirement.minimum_defect_size_um = None

    # 검사 속도 — 정확도/분해능/결함크기와 달리 "작을수록 좋다"가 아니라 "빠를수록
    # 좋다"이므로 명시적 operator가 없으면 기본값을 ">="로 둔다(요구서 예시:
    # "검사 속도는 500 mm/s 이상으로 추가해줘" -> "이상" -> ">=").
    if requirement.measurement_speed is None or not trust_llm_guess:
        found = _find_keyword_value(working_text, _SPEED_KEYWORDS)
        if found is not None:
            value, unit, operator, start, end = found
            requirement.measurement_speed = RequirementValue(value=value, unit=unit, operator=operator or ">=")
            working_text = _mask(working_text, start, end)
        elif not trust_llm_guess:
            requirement.measurement_speed = None

    # Inline/Offline, 접촉/비접촉, 측정 원리 — 숫자가 아니라 범주형 값이므로
    # agent.categorical_match의 키워드 매칭으로 판단한다(요청서 6절: "무리하게
    # LLM으로 PASS/FAIL을 판단하지 마세요" — 추출 자체도 Python 코드로 결정론적으로).
    inline_offline = categorical_match.extract_inspection_mode(text)
    if inline_offline is not None:
        requirement.inline_offline = inline_offline
    elif not trust_llm_guess:
        requirement.inline_offline = None

    measurement_method = categorical_match.extract_measurement_method(text)
    if measurement_method is not None:
        requirement.measurement_method = measurement_method
    elif not trust_llm_guess:
        requirement.measurement_method = None

    measurement_principle = categorical_match.extract_measurement_principle(text)
    if measurement_principle is not None:
        requirement.measurement_principle = measurement_principle
    elif not trust_llm_guess:
        requirement.measurement_principle = None

    requirement.sync_legacy_fields()


# ==========================================
# 대화형 조건 추가/변경/삭제(챗봇 UI) — 이미 여러 턴에 걸쳐 조건이 쌓인
# RequirementSchema에, 새로 들어온 한 메시지만 근거로 삼아 "패치"를 적용한다.
#
# apply_deterministic_extraction()의 두 모드 중 어느 쪽도 이 용도에 맞지 않는다:
#   - trust_llm_guess=True: 이미 값이 있으면 절대 안 건드린다 -> "정확도를 ±2 μm로
#     변경해줘"처럼 기존 값을 바꾸려는 메시지가 무시된다.
#   - trust_llm_guess=False: 이 메시지에 근거가 없는 필드는 전부 None으로 지운다 ->
#     "Inline으로 사용할 거야."처럼 한 조건만 말하는 메시지가 이전 턴에 확정된
#     다른 조건(측정 범위 등)까지 지워버린다.
# 그래서 세 번째 규칙이 필요하다: "이 메시지에 근거가 있으면 덮어쓰고, 없으면
# 이전 값을 그대로 둔다." 명시적 삭제 의도("~는 빼줘")만 예외적으로 필드를 지운다.
# 이 경로는 LLM을 전혀 호출하지 않는다(요청서 22절 원칙 6: "대화형 UI라고 해서
# 모든 내용을 LLM에게 다시 판단시키지 않는다") — parse_requirement_text()가 이미
# 검증한 동일한 정규식/단위 파싱 함수만 재사용한다.
# ==========================================
_REMOVE_INTENT_KEYWORDS: Tuple[str, ...] = ("빼줘", "빼주세요", "제거", "삭제", "없애", "제외해", "제외할")
_THICKNESS_KEYWORDS: Tuple[str, ...] = ("두께", "thickness")

# 삭제 의도 키워드와 함께 등장하면 해당 필드를 지운다고 판단할, 필드별 키워드.
_FIELD_REMOVE_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "target.width_mm": ("폭", "width"),
    "measurement_range": ("측정 범위", "측정범위", "범위"),
    "accuracy": ("정확도", "accuracy"),
    "resolution": ("분해능", "resolution"),
    "minimum_defect_size": ("결함 크기", "결함크기", "최소 검출"),
    "measurement_speed": ("속도", "speed"),
    "inline_offline": ("검사 모드", "inline", "offline", "인라인", "오프라인"),
    "measurement_method": ("측정 방식", "접촉", "contact"),
    "measurement_principle": ("측정 원리", "원리"),
}


def _detect_removed_fields(text: str) -> set:
    """"폭 조건은 빼줘"처럼 특정 조건을 명시적으로 제거하라는 의도를 감지한다.
    짧은 후속 메시지 하나 안에서 삭제 의도 키워드와 필드 키워드가 함께 등장하면
    그 필드를 제거 대상으로 본다 — 문장이 짧아 근접도까지 따지면 오히려 정상
    케이스를 놓치는 경우가 많으므로 co-occurrence만으로 판단한다."""
    if not any(kw in text for kw in _REMOVE_INTENT_KEYWORDS):
        return set()
    removed = set()
    for field, keywords in _FIELD_REMOVE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            removed.add(field)
    return removed


def apply_conversational_patch(requirement: RequirementSchema, message_text: str) -> RequirementSchema:
    """
    대화 중 새로 들어온 메시지(message_text)만 근거로 기존 requirement를 "패치"한다
    (요청서 7/8절: 조건 추가/변경/삭제). 이 메시지에 근거가 있는 필드만 덮어쓰고,
    나머지는 이전 턴에서 확정된 값을 그대로 보존한다. requirement는 in-place로
    수정되며 그대로 반환한다(호출부 편의를 위함).
    """
    text = unicodedata.normalize("NFC", message_text)
    removed_fields = _detect_removed_fields(text)
    working_text = text

    material = _extract_material(text)
    if material is not None:
        requirement.target.material = material

    if "target.width_mm" in removed_fields:
        requirement.target.width_mm = None
    else:
        width_span = _extract_width_mm_with_span(working_text)
        if width_span is not None:
            width_mm, start, end = width_span
            requirement.target.width_mm = width_mm
            working_text = _mask(working_text, start, end)

    if "measurement_range" in removed_fields:
        requirement.measurement_range = None
    else:
        range_result = units.parse_range_with_span(working_text)
        if range_result is not None:
            lo, hi, unit, start, end = range_result
            requirement.measurement_range = RequirementRange(min=lo, max=hi, unit=unit)
            working_text = _mask(working_text, start, end)
        else:
            bound = _find_keyword_value(working_text, _RANGE_KEYWORDS)
            if bound is not None:
                value, unit, operator, start, end = bound
                if operator in (None, "<="):
                    requirement.measurement_range = RequirementRange(min=0.0, max=value, unit=unit)
                    working_text = _mask(working_text, start, end)

    if "accuracy" in removed_fields:
        requirement.accuracy = None
        requirement.required_accuracy_um = None
    else:
        found = _find_keyword_value(working_text, _ACCURACY_KEYWORDS)
        if found is not None:
            value, unit, operator, start, end = found
            requirement.accuracy = RequirementValue(value=value, unit=unit, operator=operator or "<=")
            working_text = _mask(working_text, start, end)

    if "resolution" in removed_fields:
        requirement.resolution = None
        requirement.required_resolution_um = None
    else:
        found = _find_keyword_value(working_text, _RESOLUTION_KEYWORDS)
        if found is not None:
            value, unit, operator, start, end = found
            requirement.resolution = RequirementValue(value=value, unit=unit, operator=operator or "<=")
            working_text = _mask(working_text, start, end)

    if "minimum_defect_size" in removed_fields:
        requirement.minimum_defect_size = None
        requirement.minimum_defect_size_um = None
    else:
        found = _find_keyword_value(working_text, _DEFECT_KEYWORDS)
        if found is not None:
            value, unit, operator, start, end = found
            requirement.minimum_defect_size = RequirementValue(value=value, unit=unit, operator=operator or "<=")
            working_text = _mask(working_text, start, end)

    if "measurement_speed" in removed_fields:
        requirement.measurement_speed = None
        requirement.scan_speed_requirement = None
    else:
        found = _find_keyword_value(working_text, _SPEED_KEYWORDS)
        if found is not None:
            value, unit, operator, start, end = found
            requirement.measurement_speed = RequirementValue(value=value, unit=unit, operator=operator or ">=")
            working_text = _mask(working_text, start, end)

    if "inline_offline" in removed_fields:
        requirement.inline_offline = None
    else:
        inline_offline = categorical_match.extract_inspection_mode(text)
        if inline_offline is not None:
            requirement.inline_offline = inline_offline

    if "measurement_method" in removed_fields:
        requirement.measurement_method = None
    else:
        measurement_method = categorical_match.extract_measurement_method(text)
        if measurement_method is not None:
            requirement.measurement_method = measurement_method

    if "measurement_principle" in removed_fields:
        requirement.measurement_principle = None
    else:
        measurement_principle = categorical_match.extract_measurement_principle(text)
        if measurement_principle is not None:
            requirement.measurement_principle = measurement_principle

    # 검사 항목은 교체가 아니라 "추가"가 기본이다 — "표면 결함도 봐줘" 같은 후속
    # 메시지가 이전에 확정된 다른 항목(thickness 등)을 지우면 안 된다. 세부
    # 결함 이름이 있으면 그 세부 항목을 추가하고, 상위 카테고리는 검색 확장
    # 전용 inspection_categories로만 보낸다(문제2, parse_requirement_text와 동일 원칙).
    fine_items, categories = _extract_inspection_items_and_categories(text)
    for item in fine_items:
        if item not in requirement.inspection_items:
            requirement.inspection_items.append(item)
    for category in categories:
        if category in requirement.inspection_items:
            requirement.inspection_items.remove(category)
        if category not in requirement.inspection_categories:
            requirement.inspection_categories.append(category)

    requirement.raw_text = ((requirement.raw_text or "") + "\n" + message_text).strip()
    requirement.sync_legacy_fields()
    return requirement
