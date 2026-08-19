"""
RequirementParser — 자연어 또는 조건 선택 UI 입력을 RequirementSchema로 변환한다.

두 입력 방식(자연어 / 조건 선택) 모두 최종적으로 동일한 RequirementSchema를
만들어내므로, 이후 파이프라인(Validator → Retriever → Generator)은 입력 방식과
무관하게 동일하게 동작한다 (기획안 9절).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from . import categorical_match, ollama_client, units
from .schemas import RequirementRange, RequirementSchema, RequirementValue

PARSE_PROMPT = """당신은 전극 검사기(인라인 계측 설비) 요구사항 분석 전문가입니다.
아래 [사용자 입력]을 읽고 요구사항을 구조화된 JSON으로 정리하세요.

반드시 지켜야 할 규칙:
- 사용자가 명시적으로 말하지 않은 값은 절대로 추측하지 마세요. 반드시 null(또는 빈 배열)로 남기세요.
  예: 사용자가 정확도를 언급하지 않았다면 required_accuracy_um은 null이어야 합니다.
- inspection_items에는 사용자가 실제로 언급한 검사 항목만 담으세요.
  (thickness, surface_defect, profile_3d, coating, edge_defect 등 중 해당하는 것만)
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
_ALWAYS_TRUSTED_ITEMS = {"thickness"}
_INSPECTION_ITEM_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "surface_defect": (
        "표면 결함", "표면결함", "결함", "이물", "크랙", "핀홀", "긁힘", "스크래치",
        "defect", "scratch", "crack", "pinhole",
    ),
    "profile_3d": ("3d", "프로파일", "profile", "형상", "높이"),
    "coating": ("코팅", "coating", "도포", "loading"),
    "edge_defect": ("엣지", "edge", "가장자리", "버", "burr"),
}


def _filter_hallucinated_items(items: list, raw_text: str) -> list:
    """
    raw_text에 해당 검사 항목을 가리키는 키워드가 전혀 없으면 그 항목을 제거한다.
    키워드 목록이 없는(알 수 없는) 항목이나 _ALWAYS_TRUSTED_ITEMS는 안전하게 그대로
    유지한다(과도한 필터링으로 정당한 항목까지 지우지 않기 위함).

    안전장치: 필터링 결과 inspection_items가 통째로 비어버리면(raw_text가 짧은
    placeholder이거나 키워드 사전에 없는 표현만 쓰인 경우 등) 필터링 자체를
    신뢰할 수 없다는 뜻이므로 원본 목록을 그대로 유지한다 — "전부 삭제"가
    "일부 오탐 유지"보다 더 나쁜 실패이기 때문이다.
    """
    text_lower = (raw_text or "").lower()
    filtered = []
    for item in items:
        if item in _ALWAYS_TRUSTED_ITEMS:
            filtered.append(item)
            continue
        keywords = _INSPECTION_ITEM_KEYWORDS.get(item)
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
_DEFECT_KEYWORDS: Tuple[str, ...] = ("결함 크기", "결함크기", "defect size", "결함")
_RANGE_KEYWORDS: Tuple[str, ...] = ("측정 범위", "측정범위", "measurement range", "범위", "최대")

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
