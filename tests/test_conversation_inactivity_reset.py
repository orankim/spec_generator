"""
회귀 테스트: 좌측 대화 목록이 브라우저를 껐다가 다시 열어도 무한정 유지되던 문제.

배경: "컴퓨터를 재시작하면 초기화, 브라우저만 껐다 켜면 유지"는 웹 페이지 입장에서
구분이 불가능하다(둘 다 그냥 "새 프로세스가 처음부터 시작"으로 보이고, 그 차이를
localStorage 같은 영속 저장소에 남길 방법이 없다). 그래서 실용적인 대안으로 "일정
시간(8시간) 이상 비활성 상태면 전체 대화 기록을 초기화"를 택했다(main.py의
INACTIVITY_CLEAR_MS, pruneInactiveConversations(), boot()).

이 테스트는 main.py가 렌더링하는 /agent 페이지의 실제 JS 소스에서 해당 함수를
그대로 뽑아 Node.js로 실행해, 문자열 존재 여부가 아니라 실제 동작(8시간 이내면
유지, 초과하면 비움)을 검증한다.
"""
import json
import re
import subprocess

from fastapi.testclient import TestClient

import main


def _client():
    return TestClient(main.app)


def _extract_js_function(body: str, name: str) -> str:
    pattern = rf"function {name}\(.*?\n                \}}\n"
    match = re.search(pattern, body, re.S)
    assert match, f"{name} not found in rendered /agent page"
    return match.group(0)


def _run_prune(conversations, now_ms, inactivity_ms=8 * 60 * 60 * 1000):
    body = _client().get("/agent").text
    prune_fn = _extract_js_function(body, "pruneInactiveConversations")

    script = f"""
    const INACTIVITY_CLEAR_MS = {inactivity_ms};
    const _fixedNow = {now_ms};
    Date.now = () => _fixedNow;
    {prune_fn}
    const result = pruneInactiveConversations({json.dumps(conversations)});
    process.stdout.write(JSON.stringify(result));
    """
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_agent_page_defines_8_hour_inactivity_threshold():
    body = _client().get("/agent").text
    assert "INACTIVITY_CLEAR_MS = 8 * 60 * 60 * 1000" in body


def test_recent_conversations_are_kept():
    now = 1_000_000_000_000
    conversations = [{"id": "c1", "updatedAt": now - 60_000, "createdAt": now - 120_000}]
    assert _run_prune(conversations, now) == conversations


def test_conversations_inactive_over_8_hours_are_cleared():
    now = 1_000_000_000_000
    eight_hours_ms = 8 * 60 * 60 * 1000
    conversations = [{"id": "c1", "updatedAt": now - eight_hours_ms - 1, "createdAt": now - eight_hours_ms - 1}]
    assert _run_prune(conversations, now) == []


def test_conversations_at_exactly_8_hours_are_kept():
    """경계값: 정확히 8시간이면 아직 초과가 아니므로 유지한다."""
    now = 1_000_000_000_000
    eight_hours_ms = 8 * 60 * 60 * 1000
    conversations = [{"id": "c1", "updatedAt": now - eight_hours_ms, "createdAt": now - eight_hours_ms}]
    assert _run_prune(conversations, now) == conversations


def test_empty_conversation_list_is_unaffected():
    assert _run_prune([], 1_000_000_000_000) == []


def test_boot_wires_prune_into_state_and_persists_cleared_result():
    body = _client().get("/agent").text
    boot_fn = _extract_js_function(body, "boot")
    assert "pruneInactiveConversations(loaded)" in boot_fn
    assert "saveConversations()" in boot_fn
