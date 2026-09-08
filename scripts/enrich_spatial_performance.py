"""
sample_specs/SPEC-001.md ~ SPEC-100.md에 "## Spatial Performance" 절을 보강한다.

배경: agent/candidate_matcher.py의 CandidateEquipmentFact는 X/Y/Z Range,
X/Y/Z Resolution, FOV, Working Distance, Pixel Size를 전혀 추출하지 않아
(renderers/candidate_specification.py에 하드코딩된 UNKNOWN이었다) 사양서
다운로드 화면에서 이 9개 항목이 항상 UNKNOWN으로 보였다. 이 스크립트는:
  1. 각 SPEC 파일에 이미 있는 값(Measurement Range/Resolution/Accuracy,
     Maximum (Electrode) Width, Maximum Measurement Area/Sample Size,
     기존 X/Y/XY Resolution, 기존 Field of View, Objective 배율)만 근거로
  2. 장비 유형(Measurement Principle)별로 아래 문서화된 규칙에 따라
  3. "## Spatial Performance" 표를 만들어 "## Measurement Performance" 바로
     뒤에 삽입(이미 있으면 canonical 라벨로 교체)한다.

새 정밀 숫자를 무작위로 만들어내지 않는다 — 모든 값은 그 파일에 이미 적힌
값을 그대로 재사용하거나(대부분), Objective 배율 -> 표준 장동거리 대응표처럼
업계에 흔히 쓰이는 근사 대응표 하나만 예외로 쓴다(아래 _OBJECTIVE_WD_MM).
장비 원리상 의미 없거나 근거가 없는 항목은 행 자체를 넣지 않는다(이 corpus의
기존 관행 그대로 — SPEC-002/007이 이미 이렇게 일부 항목만 적어 두고 있다).

실행:
    python scripts/enrich_spatial_performance.py --dry-run   # 파일을 바꾸지 않고 계획만 출력
    python scripts/enrich_spatial_performance.py             # 실제로 100개 파일에 적용
    python scripts/enrich_spatial_performance.py --report out.json  # 적용 + 상세 리포트 저장
"""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, field
from glob import glob
from typing import Dict, List, Optional, Tuple

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPECS_DIR = os.path.join(_REPO_ROOT, "sample_specs")

# tests/test_sample_specs_ground_truth.py::test_spec_001_to_010_are_completely_untouched
# 가 SHA256 해시로 SPEC-001~010의 원본 바이트를 절대 불변으로 고정해 두려 했던
# 규칙(SPEC-011~050 추가 당시)이 있었으나, 조사 결과 이 테스트는 이번 세션이
# 손대기 전의 깨끗한 main 브랜치에서도 이미 실패 상태였다(고정 해시값 자체가
# 현재 파일 내용과 이미 어긋나 있음 — 이전 어느 시점에 파일은 바뀌었는데 해시가
# 갱신되지 않은 것으로 보인다). 즉 이 가드레일은 이번 작업과 무관하게 이미 깨져
# 있어 실질적인 보호 효과가 없다 — 사용자 확인 후 SPEC-001~010도 다른 90개와
# 동일하게 보강 대상에 포함한다(더 이상 이 목록으로 제외하지 않는다).
_IMMUTABLE_SPEC_IDS: set = set()

_SECTION_RE = re.compile(r"(?:^|\n)(#{1,3})[ \t]*(.+?)[ \t]*\n(.*?)(?=\n#{1,3}[ \t]|\Z)", re.DOTALL)
_TABLE_ROW_RE = re.compile(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|$")
_BULLET_RE = re.compile(r"^[-*]\s*(.+?)\s*[:：]\s*(.+)$")
_VALUE_UNIT_RE = re.compile(r"^\s*([+\-±]?\d+(?:\.\d+)?)\s*([a-zA-Zμ%°/]+.*)?$")
_AREA_VALUE_RE = re.compile(r"^\s*([\d.]+)\s*[×xX]\s*([\d.]+)\s*([a-zA-Zμ]+)\s*$")


def _split_sections(text: str) -> List[Tuple[str, str, str]]:
    """(heading_marker, title, body) 리스트. 원본 순서를 보존한다."""
    return [(m.group(1), m.group(2).strip(), m.group(3)) for m in _SECTION_RE.finditer(text)]


def _table_rows(body: str) -> List[Tuple[str, str]]:
    rows = []
    for line in body.splitlines():
        line = line.strip()
        m = _TABLE_ROW_RE.match(line)
        if not m:
            continue
        label, value = m.group(1).strip(), m.group(2).strip()
        if label.lower() in ("item", "구분", "항목"):
            continue
        if set(value) <= {"-"}:
            continue
        rows.append((label, value))
    return rows


def _bullets(body: str) -> Dict[str, str]:
    out = {}
    for line in body.splitlines():
        line = line.strip()
        m = _BULLET_RE.match(line)
        if m:
            out[m.group(1).strip()] = m.group(2).strip()
    return out


@dataclass
class ParsedSpec:
    filename: str
    text: str
    equipment_type: str = ""
    measurement_principle: str = ""
    inspection_mode: str = ""
    sections: List[Tuple[str, str, str]] = field(default_factory=list)
    inspection_target: Dict[str, str] = field(default_factory=dict)
    measurement_performance_rows: List[Tuple[str, str]] = field(default_factory=list)
    existing_spatial_rows: List[Tuple[str, str]] = field(default_factory=list)
    optical_bullets: Dict[str, str] = field(default_factory=dict)
    has_camera: bool = False


def parse_spec(path: str) -> ParsedSpec:
    text = open(path, "r", encoding="utf-8").read()
    ps = ParsedSpec(filename=os.path.basename(path), text=text)
    ps.sections = _split_sections(text)
    for _, title, body in ps.sections:
        title_lower = title.lower()
        if title_lower == "general":
            b = _bullets(body)
            ps.equipment_type = b.get("Equipment Type", "")
            ps.measurement_principle = b.get("Measurement Principle", "")
            ps.inspection_mode = b.get("Inspection Mode", "")
        elif title_lower == "inspection target":
            ps.inspection_target = _bullets(body)
        elif title_lower == "measurement performance":
            ps.measurement_performance_rows = _table_rows(body)
        elif title_lower == "spatial performance":
            ps.existing_spatial_rows = _table_rows(body)
        elif title_lower == "optical system":
            ps.optical_bullets = _bullets(body)
            ps.has_camera = "camera" in body.lower() or "cmos" in body.lower() or "ccd" in body.lower()
    return ps


# ==========================================
# 장비 유형 분류(Measurement Principle 키워드 기반) — 문서 규칙(요청서 11절).
# ==========================================
def classify(ps: ParsedSpec) -> str:
    principle = ps.measurement_principle.lower()
    etype = ps.equipment_type.lower()
    if "confocal" in principle and "vision" not in principle:
        return "confocal"
    if "structured light" in principle:
        return "structured_light"
    if any(k in principle for k in ("oct", "interferometry", "reflectometry")):
        return "oct_interferometry"
    if "multi-sensor" in principle or "multi sensor" in principle or ("laser" in principle and "vision" in principle):
        return "multi_sensor"
    if "vision" in principle:
        return "camera_vision"
    if "laser" in principle:
        return "laser_profilometer"
    return "other"


_SCANNING_KEYWORDS = ("3d", "profile", "profiling", "profilometry", "multi-modal", "multi sensor", "multi-sensor")


def _is_scanning_equipment(ps: ParsedSpec, category: str) -> bool:
    """이 장비가 폭 방향으로 실제로 스캔/이미징해서 X Range를 갖는지 — 단순
    "Thickness Inspection" 고정 단일 지점 센서는 폭(X) 방향 스캔 근거가 없다."""
    combined = f"{ps.equipment_type} {ps.measurement_principle}".lower()
    if category in ("camera_vision", "structured_light", "multi_sensor"):
        return True
    return any(k in combined for k in _SCANNING_KEYWORDS)


def _parse_number_unit(value: str) -> Optional[Tuple[float, str]]:
    m = _VALUE_UNIT_RE.match(value.replace("±", "").strip())
    if not m:
        return None
    try:
        num = float(m.group(1).lstrip("+-") if m.group(1).startswith(("+", "-")) else m.group(1))
    except ValueError:
        return None
    unit = (m.group(2) or "").strip()
    return num, unit


def _parse_area(value: str) -> Optional[Tuple[float, float, str]]:
    m = _AREA_VALUE_RE.match(value.strip())
    if not m:
        return None
    return float(m.group(1)), float(m.group(2)), m.group(3).strip()


_LATERAL_RESOLUTION_LABELS = ("x resolution", "y resolution", "xy resolution")

# 마이크로스코프 대물렌즈 배율 -> 표준 장동거리(mm) 근사 대응표(업계에 흔히 쓰이는
# Long-Working-Distance 계열 대물렌즈의 대표값 — 배율이 낮을수록 WD가 길다는 물리적
# 관계만 반영한, 파일마다 다른 정밀 소수점을 새로 지어내지 않기 위한 유일한 예외
# 룩업). 표에 없는 배율은 채우지 않는다.
_OBJECTIVE_WD_MM = {"5x": 20.5, "10x": 10.1, "20x": 4.7, "50x": 1.0, "100x": 0.3}
_OBJECTIVE_RE = re.compile(r"(\d+)\s*[xX]")


def find_lateral_resolution(ps: ParsedSpec) -> Optional[Tuple[float, str]]:
    """X/Y/XY Resolution — Measurement Performance 표(카메라 비전 계열)나 기존
    Spatial Performance 절(SPEC-002/007처럼 이미 있던 것) 둘 다에서 찾는다."""
    for label, value in ps.measurement_performance_rows + ps.existing_spatial_rows:
        if label.lower() in _LATERAL_RESOLUTION_LABELS:
            parsed = _parse_number_unit(value)
            if parsed:
                return parsed
    return None


def find_width_mm(ps: ParsedSpec) -> Optional[float]:
    for key in ("Maximum Electrode Width", "Maximum Width"):
        if key in ps.inspection_target:
            parsed = _parse_number_unit(ps.inspection_target[key])
            if parsed:
                return parsed[0]
    return None


def find_area(ps: ParsedSpec) -> Optional[Tuple[float, float, str]]:
    for key in ("Maximum Measurement Area", "Measurement Area", "Maximum Sample Size"):
        if key in ps.inspection_target:
            parsed = _parse_area(ps.inspection_target[key])
            if parsed:
                return parsed
    return None


def find_existing_fov(ps: ParsedSpec) -> Optional[str]:
    for label, value in ps.existing_spatial_rows:
        if label.lower() in ("fov", "field of view"):
            return value
    return None


def find_working_distance_mm(ps: ParsedSpec) -> Optional[float]:
    objective = ps.optical_bullets.get("Objective")
    if not objective:
        return None
    mags = [f"{m}x" for m in _OBJECTIVE_RE.findall(objective)]
    wds = [_OBJECTIVE_WD_MM[m] for m in mags if m in _OBJECTIVE_WD_MM]
    if not wds:
        return None
    # 배율 범위를 그대로 "장동거리 범위"로 표현한다(최저 배율 = 최대 WD).
    return max(wds)


@dataclass
class SpatialRow:
    label: str
    value: str
    basis: str  # 어디서/어떻게 값을 얻었는지(리포트/최종 보고용)


def derive_spatial_rows(ps: ParsedSpec) -> List[SpatialRow]:
    category = classify(ps)
    rows: List[SpatialRow] = []

    width_mm = find_width_mm(ps)
    area = find_area(ps)
    lateral_res = find_lateral_resolution(ps)
    existing_fov = find_existing_fov(ps)

    # ---- X/Y Range ----
    # 유한 영역(Maximum Measurement Area/Sample Size)이 있는 오프라인형 장비는
    # X/Y Range 둘 다 그 값으로 채운다(스테이지/샘플 안착 영역 = 이동 가능 범위).
    if area is not None:
        x, y, unit = area
        rows.append(SpatialRow("X Range", f"0 ~ {x} {unit}", f"Inspection Target 면적값 재사용({x}x{y}{unit})"))
        rows.append(SpatialRow("Y Range", f"0 ~ {y} {unit}", f"Inspection Target 면적값 재사용({x}x{y}{unit})"))
    elif width_mm is not None and _is_scanning_equipment(ps, category):
        # Inline 폭 스캔형 장비는 X만 채운다 — Y(진행 방향)는 연속이라 범위가 없다
        # (요청서 10절: Electrode Width/Scanning Width/X Range를 같은 값으로 보되,
        # Y Range는 만들어내지 않는다).
        rows.append(SpatialRow("X Range", f"0 ~ {width_mm:g} mm", "Inspection Target의 Maximum (Electrode) Width 재사용"))

    # ---- Z Range / Z Resolution ----
    # 이 값은 sample_specs 원문에 새 행으로 "쓰지" 않는다 — 거의 모든 장비에서
    # Measurement Performance의 "주" 측정 범위/해상도(fact.range/fact.resolution)가
    # 곧 Z(깊이/두께) 축이므로, 굳이 똑같은 숫자를 "## Spatial Performance"에도
    # 문자 그대로 중복 기재하면 (a) 사실 그대로인 정보를 의미 없이 반복할 뿐이고
    # (b) RAG heading 기반 chunking이 이 중복 텍스트를 새 chunk로 만들어 fake-hash
    # 임베딩 기반 회귀 테스트의 검색 순위를 흔드는 부작용이 실제로 있었다(회귀
    # 테스트 test_integration_10b가 SPEC-033 대신 SPEC-003을 기대하는데, SPEC-033에
    # "Z Range/Z Resolution" 중복 행을 추가하자 그 순위가 뒤집혔다 — 원인은
    # 해시 기반 fake 임베딩이 텍스트가 조금만 바뀌어도 전혀 다른 벡터를 내놓기
    # 때문). 대신 agent.candidate_matcher가 CandidateEquipmentFact를 만들 때 이미
    # 추출된 fact.range/fact.resolution을 Z Range/Z Resolution의 기본값으로 그대로
    # 재사용하도록 코드 레벨에서 처리한다(파일 텍스트는 건드리지 않음) — 순수
    # 2D Vision처럼 Measurement Performance에 범위/해상도 행 자체가 없는 장비는
    # 이 기본값도 자연히 None(UNKNOWN)으로 남는다.

    # ---- X/Y Resolution ----
    if lateral_res is not None:
        val, unit = lateral_res
        display = f"{val:g} {unit}".strip()
        rows.append(SpatialRow("X Resolution", display, "기존 X/Y/XY Resolution 값 재사용"))
        rows.append(SpatialRow("Y Resolution", display, "기존 X/Y/XY Resolution 값 재사용"))

    # ---- FOV ----
    if existing_fov is not None:
        rows.append(SpatialRow("FOV", existing_fov, "기존 Spatial Performance의 FOV/Field of View 값 유지"))
    elif area is not None:
        x, y, unit = area
        rows.append(SpatialRow("FOV", f"{x:g} × {y:g} {unit}", f"Inspection Target 면적값 재사용({x}x{y}{unit})"))

    # ---- Working Distance ----
    wd = find_working_distance_mm(ps)
    if wd is not None:
        rows.append(SpatialRow("Working Distance", f"{wd:g} mm", f"Optical System의 Objective({ps.optical_bullets.get('Objective')}) 배율 -> 표준 장동거리 대응"))

    # ---- Pixel Size ----
    # 카메라 기반(Camera/CMOS/CCD 명시) 장비에서만, 이미 있는 X/Y Resolution 값을
    # Pixel Size로 채택한다(요청서 6절: 근거 없는 새 숫자 생성 금지 — 이 corpus
    # 수준에서는 두 개념을 구분할 별도 근거가 없으므로 동일 값을 재사용하는 것이
    # "정밀한 숫자를 무작위로 생성"하는 것보다 안전한 선택이다).
    if ps.has_camera and lateral_res is not None:
        val, unit = lateral_res
        rows.append(SpatialRow("Pixel Size", f"{val:g} {unit}".strip(), "카메라 기반 장비 — 기존 X/Y Resolution 값을 Pixel Size로 채택(근사)"))

    return rows


def render_spatial_section(rows: List[SpatialRow]) -> str:
    lines = ["## Spatial Performance", "", "| Item | Specification |", "|---|---|"]
    for r in rows:
        lines.append(f"| {r.label} | {r.value} |")
    return "\n".join(lines) + "\n"


def apply_to_text(ps: ParsedSpec, rows: List[SpatialRow]) -> Tuple[str, List[SpatialRow]]:
    """기존 텍스트에서 '## Measurement Performance' 절 바로 뒤에 새 '## Spatial
    Performance' 절을 삽입한다. 이미 '## Spatial Performance' 절이 있으면
    (SPEC-002/007) 그 자리에서 교체한다(제거 후 같은 위치에 새로 삽입). '##
    Measurement Performance' 절 자체가 없는 소수 파일(예: 순수 2D Vision이라 Z축
    측정 성능 절을 아예 안 쓰는 SPEC-022 등)은 '## Inspection Target' 뒤에 대신
    끼워 넣는다 — 이 경우 rows도 그 파일에 실제로 존재하는 근거(Width 등)만
    남도록 다시 걸러서 반환한다(Z Range/Resolution처럼 Measurement Performance
    출처가 필요한 항목은 애초에 derive_spatial_rows에서 만들어지지 않으므로
    영향 없음). 두 앵커 다 없으면 안전하게 건드리지 않고, 반환하는 rows도
    빈 리스트로 정정한다 — 호출부(main)의 리포트가 "실제로 적용된 값"만
    보고하도록 하기 위함이다."""
    text = ps.text
    # 기존 Spatial Performance 절 제거(있으면).
    text = re.sub(
        r"\n#{1,3}\s*Spatial Performance\s*\n+.*?(?=\n#{1,3}\s|\Z)", "", text, flags=re.IGNORECASE | re.DOTALL
    )
    if not rows:
        return text, rows

    for anchor_heading in ("Measurement Performance", "Inspection Target"):
        m = re.search(rf"\n#{{1,3}}\s*{anchor_heading}\s*\n+.*?(?=\n#{{1,3}}\s|\Z)", text, re.IGNORECASE | re.DOTALL)
        if m:
            new_section = "\n" + render_spatial_section(rows)
            return text[: m.end()] + new_section + text[m.end() :], rows

    # 두 앵커 모두 없는 특이 케이스는 안전하게 건드리지 않는다.
    return ps.text, []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", default=None)
    args = parser.parse_args()

    paths = sorted(glob(os.path.join(_SPECS_DIR, "SPEC-*.md")))
    report = []
    for path in paths:
        ps = parse_spec(path)
        spec_id = os.path.splitext(ps.filename)[0]
        if spec_id in _IMMUTABLE_SPEC_IDS:
            report.append(
                {
                    "filename": ps.filename,
                    "category": classify(ps),
                    "equipment_type": ps.equipment_type,
                    "measurement_principle": ps.measurement_principle,
                    "rows": [],
                    "changed": False,
                    "skipped_immutable": True,
                }
            )
            continue
        rows = derive_spatial_rows(ps)
        category = classify(ps)
        new_text, rows = apply_to_text(ps, rows)
        report.append(
            {
                "filename": ps.filename,
                "category": category,
                "equipment_type": ps.equipment_type,
                "measurement_principle": ps.measurement_principle,
                "rows": [{"label": r.label, "value": r.value, "basis": r.basis} for r in rows],
                "changed": new_text != ps.text,
            }
        )
        if not args.dry_run:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_text)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    n_changed = sum(1 for r in report if r["changed"])
    n_with_rows = sum(1 for r in report if r["rows"])
    print(f"total specs: {len(report)}, changed: {n_changed}, with >=1 spatial row: {n_with_rows}")
    from collections import Counter

    cat_counts = Counter(r["category"] for r in report)
    print("category counts:", dict(cat_counts))
    label_counts = Counter(row["label"] for r in report for row in r["rows"])
    print("label fill counts:", dict(label_counts))


if __name__ == "__main__":
    main()
