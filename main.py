import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

# .env 파일이 있으면 로드 (없어도 조용히 무시됨 - 환경변수를 직접 export해도 동일하게 동작)
load_dotenv()

# 폐쇄망 보안 정책: 외부(HuggingFace Hub 등) 네트워크 통신 원천 차단
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# 앞서 작성한 파이프라인 모듈 임포트
from agent.routes import router as agent_router
from agent.ollama_client import check_ollama_available
from agent.paths import DEFAULT_SAMPLE_SPECS_DIR

app = FastAPI(title="전극 검사기 사양서 자동 생성 AI")
app.include_router(agent_router)

# 생성된 PPTX 파일이 임시 저장될 폴더. agent/routes.py의 "/api/agent/build-pptx"가
# 이 폴더(상대경로 "./generated_files")에 파일을 쓰고, 아래 "/api/download/{file_name}"이
# 그 파일을 서빙한다 — Agent가 실제로 쓰는 공유 인프라이므로 유지한다.
OUTPUT_DIR = Path("./generated_files")
OUTPUT_DIR.mkdir(exist_ok=True)

# RAG 원본 사양서(Markdown/PPTX)가 저장되는 폴더. build_rag_ollama.py의 기본
# 입력 폴더와 항상 같은 절대경로를 가리키도록 agent/paths.py 기준값을 그대로 쓴다.
SAMPLE_SPECS_DIR = Path(DEFAULT_SAMPLE_SPECS_DIR)
SAMPLE_SPECS_DIR.mkdir(exist_ok=True)

# Ollama 서버 주소 (환경변수로 오버라이드 가능)
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

if not check_ollama_available(OLLAMA_HOST):
    logger.warning(
        "Ollama 서버(%s)에 연결할 수 없습니다. 서버는 계속 기동하지만, "
        "전극 검사기 Agent 기능은 Ollama가 켜져 있어야 동작합니다.",
        OLLAMA_HOST,
    )


# ==========================================
# 1. 공통 페이지 레이아웃 (공통 스타일)
# ==========================================
PAGE_STYLE = """
    body { font-family: '맑은 고딕', sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; background-color: #f5f6f8; }
    .container { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
    h2 { color: #1a2530; margin-bottom: 20px; }
    .nav { display: flex; gap: 10px; margin-bottom: 20px; }
    .nav a { flex: 1; text-align: center; padding: 12px; border-radius: 6px; text-decoration: none; color: #2b6cb0; background: #e8eef5; font-weight: bold; }
    .nav a.active { background: #2b6cb0; color: white; }
    textarea { width: 100%; height: 120px; padding: 12px; border: 1px solid #ccc; border-radius: 6px; font-size: 14px; box-sizing: border-box; resize: vertical; }
    input[type="file"] { width: 100%; padding: 12px; border: 1px dashed #aaa; border-radius: 6px; box-sizing: border-box; background: #fafafa; }
    button { background-color: #2b6cb0; color: white; border: none; padding: 12px 24px; border-radius: 6px; font-size: 16px; cursor: pointer; margin-top: 15px; width: 100%; }
    button:hover { background-color: #2c5282; }
    button:disabled { background-color: #a0aec0; cursor: not-allowed; }
    #loading { display: none; margin-top: 20px; color: #2b6cb0; font-weight: bold; text-align: center; }
    #result { display: none; margin-top: 20px; padding: 15px; background: #e6fffa; border: 1px solid #319795; border-radius: 6px; text-align: center; }
    a.download-btn { display: inline-block; margin-top: 10px; padding: 10px 20px; background: #319795; color: white; text-decoration: none; border-radius: 6px; font-weight: bold; }
    ul#fileList { list-style: none; padding: 0; margin: 10px 0 0; font-size: 13px; color: #555; }
    ul#fileList li { padding: 4px 0; border-bottom: 1px solid #eee; }

    .step { display: none; margin-top: 20px; }
    .step.active { display: block; }
    .field-row { margin-bottom: 12px; }
    .field-row label { display: block; font-size: 13px; color: #444; margin-bottom: 4px; }
    .field-row input[type="text"], .field-row input[type="number"], .field-row select {
        width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 6px; box-sizing: border-box; font-size: 14px;
    }
    .checkbox-group { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
    .checkbox-group label { background: #f0f2f5; border: 1px solid #ddd; border-radius: 20px; padding: 6px 14px; font-size: 13px; cursor: pointer; }
    .checkbox-group input { margin-right: 4px; }
    .summary-box { background: #f8f9fb; border: 1px solid #e0e0e0; border-radius: 8px; padding: 15px; margin: 15px 0; font-size: 14px; line-height: 1.7; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; font-weight: bold; margin-left: 6px; }
    .badge-error { background: #fed7d7; color: #9b2c2c; }
    .badge-warning { background: #feebc8; color: #9c4221; }
    .badge-info { background: #bee3f8; color: #2c5282; }
    .issue-list { list-style: none; padding: 0; margin: 10px 0; }
    .issue-list li { padding: 6px 10px; border-radius: 6px; margin-bottom: 6px; font-size: 13px; }
    .issue-list li.error { background: #fff5f5; color: #9b2c2c; border-left: 3px solid #e53e3e; }
    .issue-list li.warning { background: #fffaf0; color: #9c4221; border-left: 3px solid #dd6b20; }
    .issue-list li.info { background: #ebf8ff; color: #2c5282; border-left: 3px solid #3182ce; }
    .issue-list li.success { background: #f0fff4; color: #276749; border-left: 3px solid #38a169; }
    .tab-toggle { display: flex; gap: 8px; margin-bottom: 15px; }
    .tab-toggle button { width: auto; flex: 1; background: #e8eef5; color: #2b6cb0; margin-top: 0; }
    .tab-toggle button.active { background: #2b6cb0; color: white; }
"""


def render_page(title: str, body_html: str) -> str:
    """
    페이지 공통 레이아웃. 전극 검사기 AI가 유일한 기능이므로 더 이상 탭 네비게이션이
    필요 없다 — 상단에 고정 타이틀만 표시한다.
    """
    return f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title}</title>
        <style>{PAGE_STYLE}</style>
    </head>
    <body>
        <div class="container">
            <div class="nav">
                <span style="flex:1; text-align:center; padding:12px; border-radius:6px; background:#2b6cb0; color:white; font-weight:bold;">🔬 전극 검사기 AI</span>
            </div>
            {body_html}
        </div>
    </body>
    </html>
    """


@app.get("/", include_in_schema=False)
async def read_root():
    """루트 접속 시 바로 전극 검사기 AI 화면으로 이동한다 (유일한 사용자 기능)."""
    return RedirectResponse(url="/agent")


# ==========================================
# 2. (제거됨) 사양서 제작하기 / 사양서 업로드하기
# ==========================================
# 기존에는 여기에 "/"(자연어 요구사항으로 PPTX 생성)와 "/upload"(RAG 학습용 PPTX
# 업로드) 페이지가 있었다. 전극 검사기 AI(/agent)만 사용자 기능으로 남기기로 하여
# UI/라우트를 제거했다. 이 기능들이 쓰던 generator.py(SpecGenerator)/pptx_builder.py
# (PPTXBuilder) 모듈 자체는 삭제하지 않았다 — preprocess_specs.py가 계속
# import하고, pptx_builder.py는 agent/pptx_electrode_builder.py(Agent의 PPTX 출력
# 기능)가 재사용하는 공통 모듈이기 때문이다.
# ==========================================
# 3. 전극 검사기 사양서 자동 생성 AI Agent 페이지
# ==========================================
@app.get("/agent", response_class=HTMLResponse)
async def agent_page():
    """
    전극 검사기 사양서 자동 생성 Agent 화면.
    자연어 입력 / 조건 선택 입력 -> 요구사항 확인(부족한 정보는 추가 질문) ->
    사내 사양서 검색 및 사양서 생성 -> 검증 결과 확인 -> PPTX 생성 순서로 진행된다.
    """
    body_html = """
            <h2>🔬 전극 검사기 사양서 자동 생성 AI</h2>
            <p>요구사항을 자연어로 입력하거나 조건을 직접 선택하세요. AI가 이해한 내용을 먼저 확인시켜 드리고, 부족한 정보는 추가로 여쭤봅니다.</p>

            <!-- STEP 1: 입력 -->
            <div id="step1" class="step active">
                <div class="tab-toggle">
                    <button id="modeTextBtn" class="active" onclick="switchMode('text')" type="button">자연어로 입력</button>
                    <button id="modeSelectBtn" onclick="switchMode('select')" type="button">조건 직접 선택</button>
                </div>

                <div id="modeText">
                    <textarea id="nlInput" placeholder="예: 500mm 폭 전극의 두께와 표면 결함을 검사할 수 있는 비접촉 검사기가 필요해."></textarea>
                </div>

                <div id="modeSelect" style="display:none;">
                    <div class="field-row">
                        <label>검사 대상</label>
                        <div class="checkbox-group">
                            <label><input type="radio" name="selMaterial" value="양극"> 양극</label>
                            <label><input type="radio" name="selMaterial" value="음극"> 음극</label>
                            <label><input type="radio" name="selMaterial" value="분리막"> 분리막</label>
                            <label><input type="radio" name="selMaterial" value="전극"> 전극(공통)</label>
                        </div>
                    </div>
                    <div class="field-row">
                        <label>폭 (mm)</label>
                        <input type="number" id="selWidth" placeholder="예: 500">
                    </div>
                    <div class="field-row">
                        <label>검사 항목</label>
                        <div class="checkbox-group">
                            <label><input type="checkbox" class="inspItem" value="thickness"> 두께</label>
                            <label><input type="checkbox" class="inspItem" value="surface_defect"> 표면 결함</label>
                            <label><input type="checkbox" class="inspItem" value="profile_3d"> 3D 프로파일</label>
                            <label><input type="checkbox" class="inspItem" value="coating"> 코팅</label>
                        </div>
                    </div>
                    <div class="field-row">
                        <label>측정 방식</label>
                        <div class="checkbox-group">
                            <label><input type="radio" name="selMethod" value="non_contact"> 비접촉</label>
                            <label><input type="radio" name="selMethod" value="contact"> 접촉</label>
                        </div>
                    </div>
                    <div class="field-row">
                        <label>측정 원리</label>
                        <div class="checkbox-group">
                            <label><input type="radio" name="selPrinciple" value="laser"> Laser</label>
                            <label><input type="radio" name="selPrinciple" value="oct"> OCT</label>
                            <label><input type="radio" name="selPrinciple" value="interferometry"> Interferometry</label>
                            <label><input type="radio" name="selPrinciple" value="vision"> Vision</label>
                            <label><input type="radio" name="selPrinciple" value="other"> 기타</label>
                        </div>
                    </div>
                </div>

                <button id="analyzeBtn" onclick="analyze()">요구사항 분석</button>
            </div>

            <!-- STEP 2: 요구사항 확인 + 추가 질문 -->
            <div id="step2" class="step">
                <h3>AI가 이해한 요구사항</h3>
                <div id="reqSummary" class="summary-box"></div>

                <div id="followupSection" style="display:none;">
                    <p><strong>추가로 다음 정보가 필요합니다.</strong></p>
                    <ul id="questionList" class="issue-list"></ul>
                    <div id="followupFields"></div>
                    <button onclick="submitFollowup()">추가 정보 제출</button>
                </div>

                <button id="proceedBtn" onclick="proceedToGenerate()" style="display:none;">사내 사양서 검색 &amp; 사양서 생성</button>
                <button onclick="goToStep('step1')" style="background:#a0aec0;">◀ 다시 입력하기</button>
            </div>

            <!-- STEP 3: 생성된 사양서 확인 -->
            <div id="step3" class="step">
                <h3>생성된 사양서 (검토 후 PPTX로 만드세요)</h3>
                <div id="specSummary" class="summary-box"></div>

                <div id="hardReqWrap">
                    <p><strong>사용자 요구조건 검증 (Hard Requirement)</strong></p>
                    <ul id="hardReqList" class="issue-list"></ul>
                </div>

                <div id="issuesWrap">
                    <p><strong>자동 검증 결과</strong></p>
                    <ul id="issuesList" class="issue-list"></ul>
                </div>

                <div id="confirmWrap">
                    <p><strong>사용자 확인이 필요한 항목 (AI 추정값)</strong></p>
                    <ul id="confirmList" class="issue-list"></ul>
                </div>

                <button onclick="buildPptx()">📄 PPTX 사양서 생성</button>
                <button onclick="goToStep('step2')" style="background:#a0aec0;">◀ 요구사항 다시 확인</button>

                <div id="agentResult" style="display:none; margin-top:15px; padding:15px; background:#e6fffa; border:1px solid #319795; border-radius:6px; text-align:center;">
                    <h3>🎉 사양서가 생성되었습니다!</h3>
                    <a id="agentDownloadLink" class="download-btn" href="#" download>PPTX 사양서 다운로드</a>
                </div>
            </div>

            <div id="loading">⏳ 처리 중입니다...</div>

            <script>
                const state = { requirement: null, validation: null, specification: null, specValidation: null };

                const FIELD_LABELS = {
                    'target.material': '검사 대상 (예: 양극, 음극, 분리막, 전극)',
                    'target.width_mm': '검사 대상 폭 (mm, 숫자만)',
                    'inspection_items': '검사 항목 (쉼표로 구분, 예: thickness,surface_defect)',
                    'target.thickness_range_um': '두께 범위 (예: 0~200)',
                    'required_accuracy_um': '요구 정확도 (um, 숫자만)',
                    'minimum_defect_size_um': '최소 검출 결함 크기 (um, 숫자만)',
                };
                const NUMERIC_PATHS = ['target.width_mm', 'required_accuracy_um', 'minimum_defect_size_um'];

                function setLoading(on) { document.getElementById('loading').style.display = on ? 'block' : 'none'; }

                function goToStep(id) {
                    document.querySelectorAll('.step').forEach(el => el.classList.remove('active'));
                    document.getElementById(id).classList.add('active');
                }

                function switchMode(mode) {
                    document.getElementById('modeText').style.display = mode === 'text' ? 'block' : 'none';
                    document.getElementById('modeSelect').style.display = mode === 'select' ? 'block' : 'none';
                    document.getElementById('modeTextBtn').classList.toggle('active', mode === 'text');
                    document.getElementById('modeSelectBtn').classList.toggle('active', mode === 'select');
                }

                function setByPath(obj, path, value) {
                    const keys = path.split('.');
                    let cur = obj;
                    for (let i = 0; i < keys.length - 1; i++) {
                        if (cur[keys[i]] === undefined || cur[keys[i]] === null) cur[keys[i]] = {};
                        cur = cur[keys[i]];
                    }
                    cur[keys[keys.length - 1]] = value;
                }

                function collectSelection() {
                    const material = document.querySelector('input[name="selMaterial"]:checked');
                    const width = document.getElementById('selWidth').value;
                    const items = [...document.querySelectorAll('.inspItem:checked')].map(el => el.value);
                    const method = document.querySelector('input[name="selMethod"]:checked');
                    const principle = document.querySelector('input[name="selPrinciple"]:checked');
                    return {
                        target: {
                            material: material ? material.value : null,
                            width_mm: width ? parseFloat(width) : null,
                        },
                        inspection_items: items,
                        measurement_method: method ? method.value : null,
                        measurement_principle: principle ? principle.value : null,
                    };
                }

                async function analyze() {
                    const isTextMode = document.getElementById('modeText').style.display !== 'none';
                    let payload;
                    if (isTextMode) {
                        const text = document.getElementById('nlInput').value.trim();
                        if (!text) { alert('요구사항을 입력해 주세요.'); return; }
                        payload = { user_text: text };
                    } else {
                        payload = { selection: collectSelection() };
                    }
                    await callAnalyze(payload);
                }

                async function callAnalyze(payload) {
                    setLoading(true);
                    try {
                        const res = await fetch('/api/agent/analyze-requirement', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload),
                        });
                        const data = await res.json();
                        if (!res.ok) throw new Error(data.detail || '요구사항 분석 실패');
                        state.requirement = data.requirement;
                        state.validation = data.validation;
                        renderRequirementSummary();
                        goToStep('step2');
                    } catch (err) {
                        alert('요구사항 분석 중 오류가 발생했습니다:\\n\\n' + err.message);
                    } finally {
                        setLoading(false);
                    }
                }

                function fmtRange(range) {
                    if (!range || range.min === null || range.min === undefined || range.max === null || range.max === undefined) return '미정';
                    return `${range.min} ~ ${range.max} ${range.unit || ''}`.trim();
                }

                function fmtReqValue(rv, withPlusMinus) {
                    if (!rv || rv.value === null || rv.value === undefined) return '미정';
                    const opLabel = {'<=': '이하', '>=': '이상', '<': '미만', '>': '초과'}[rv.operator] || '';
                    const prefix = withPlusMinus ? '±' : '';
                    return `${prefix}${rv.value} ${rv.unit || ''} ${opLabel}`.trim();
                }

                function renderRequirementSummary() {
                    const req = state.requirement;
                    const val = state.validation;

                    document.getElementById('reqSummary').innerHTML = `
                        <strong>검사 대상:</strong> ${req.target.material || '미정'}<br>
                        <strong>폭:</strong> ${req.target.width_mm ?? '미정'} mm<br>
                        <strong>검사 항목:</strong> ${(req.inspection_items || []).join(', ') || '미정'}<br>
                        <strong>측정 범위:</strong> ${fmtRange(req.measurement_range)}<br>
                        <strong>요구 정확도:</strong> ${fmtReqValue(req.accuracy, true)}<br>
                        <strong>측정 방식:</strong> ${req.measurement_method || '미정'}<br>
                        <strong>측정 원리:</strong> ${req.measurement_principle || '미정'}
                    `;

                    const followupSection = document.getElementById('followupSection');
                    const proceedBtn = document.getElementById('proceedBtn');
                    const questionList = document.getElementById('questionList');
                    const followupFields = document.getElementById('followupFields');
                    questionList.innerHTML = '';
                    followupFields.innerHTML = '';

                    if (!val.is_valid) {
                        followupSection.style.display = 'block';
                        proceedBtn.style.display = 'none';
                        (val.questions || []).forEach(q => {
                            const li = document.createElement('li');
                            li.className = 'info';
                            li.textContent = q;
                            questionList.appendChild(li);
                        });
                        (val.missing_fields || []).forEach(path => {
                            const label = FIELD_LABELS[path] || path;
                            const row = document.createElement('div');
                            row.className = 'field-row';
                            row.innerHTML = `<label>${label}</label><input type="text" data-path="${path}">`;
                            followupFields.appendChild(row);
                        });
                    } else {
                        followupSection.style.display = 'none';
                        proceedBtn.style.display = 'block';
                    }
                }

                async function submitFollowup() {
                    const updated = JSON.parse(JSON.stringify(state.requirement));
                    document.querySelectorAll('#followupFields input').forEach(inp => {
                        const path = inp.dataset.path;
                        let val = inp.value.trim();
                        if (!val) return;
                        if (path === 'inspection_items') {
                            val = val.split(',').map(s => s.trim()).filter(Boolean);
                        } else if (NUMERIC_PATHS.includes(path)) {
                            val = parseFloat(val);
                        }
                        setByPath(updated, path, val);
                    });
                    await callAnalyze({ existing_requirement: updated });
                }

                async function proceedToGenerate() {
                    setLoading(true);
                    try {
                        const res = await fetch('/api/agent/generate-spec', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ requirement: state.requirement }),
                        });
                        const data = await res.json();
                        if (!res.ok) throw new Error(data.detail || '사양서 생성 실패');
                        state.specification = data.specification;
                        state.specValidation = data.validation;
                        renderSpecSummary(data.retrieved_sources || [], data.hard_requirement_report || []);
                        goToStep('step3');
                    } catch (err) {
                        alert('사양서 생성 중 오류가 발생했습니다:\\n\\n' + err.message);
                    } finally {
                        setLoading(false);
                    }
                }

                function fmtSourced(sn) {
                    if (!sn || sn.value === null || sn.value === undefined) return 'N/A';
                    const statusLabel = {USER_DEFINED: '사용자 요구사항', VERIFIED: (sn.source && sn.source.document) || '문서', INFERRED: 'AI 추정', UNKNOWN: '근거 없음'}[sn.status] || sn.status || '-';
                    return `${sn.value}${sn.unit ? ' ' + sn.unit : ''} (${statusLabel})`;
                }

                function fmtSourcedRange(sr) {
                    if (!sr || sr.min === null || sr.min === undefined || sr.max === null || sr.max === undefined) return 'N/A';
                    const statusLabel = {USER_DEFINED: '사용자 요구사항', VERIFIED: (sr.source && sr.source.document) || '문서', INFERRED: 'AI 추정', UNKNOWN: '근거 없음'}[sr.status] || sr.status || '-';
                    return `${sr.min} ~ ${sr.max} ${sr.unit || ''} (${statusLabel})`.replace('  (', ' (');
                }

                function renderHardRequirementReport(records) {
                    const list = document.getElementById('hardReqList');
                    list.innerHTML = '';
                    if (!records || records.length === 0) {
                        list.innerHTML = '<li class="info">평가할 hard requirement가 없습니다(요구사항에 측정 범위/정확도가 지정되지 않음).</li>';
                        return;
                    }
                    const cls = { PASS: 'success', FAIL: 'error', UNKNOWN: 'warning' };
                    records.forEach(r => {
                        const li = document.createElement('li');
                        li.className = cls[r.result] || 'info';
                        li.textContent = `[${r.item}] ${r.reason} → 판정: ${r.result}`;
                        list.appendChild(li);
                    });
                }

                function renderSpecSummary(retrievedSources, hardRequirementReport) {
                    const spec = state.specification;
                    const val = state.specValidation;
                    const req = state.requirement || {};

                    const noResultsWarning = retrievedSources.length === 0
                        ? `<div style="margin-top:8px; padding:8px 10px; background:#fff5f5; border:1px solid #feb2b2; border-radius:4px; color:#822727;">
                               ⚠️ 조건에 맞는 참고 사양서를 찾지 못했습니다 (검색된 chunk 0개). 아래 값은 사용자가 직접 입력한 요구사항 외에는 근거가 없습니다.
                           </div>`
                        : '';

                    const requiredAccuracyDisplay = req.accuracy
                        ? fmtReqValue(req.accuracy, true)
                        : (req.required_accuracy_um != null ? `±${req.required_accuracy_um} um 이하` : '미정');

                    const primarySources = (spec.primary_sources && spec.primary_sources.length > 0)
                        ? spec.primary_sources
                        : (spec.sources || []);

                    document.getElementById('specSummary').innerHTML = `
                        <strong>설비명:</strong> ${spec.equipment.name || 'N/A'}<br>
                        <strong>검사 대상:</strong> ${spec.inspection_target.material || 'N/A'} (${spec.inspection_target.width_mm ?? '?'} mm)<br>
                        <strong>검사 항목:</strong> ${(spec.inspection_items || []).join(', ') || 'N/A'}<br>
                        <strong>측정 범위:</strong> ${fmtSourcedRange(spec.measurement_performance.measurement_range_full)}<br>
                        <strong>요구 정확도:</strong> ${requiredAccuracyDisplay}<br>
                        <strong>장비 정확도:</strong> ${fmtSourced(spec.measurement_performance.equipment_accuracy_um)}<br>
                        <strong>분해능:</strong> ${fmtSourced(spec.measurement_performance.resolution_um)}<br>
                        <strong>최소 검출 결함 크기:</strong> ${fmtSourced(spec.defect_detection.minimum_defect_size_um)}<br>
                        <strong>참고 문서:</strong> ${primarySources.join(', ') || '없음'} (검색된 chunk ${retrievedSources.length}개)
                        ${noResultsWarning}
                    `;

                    renderHardRequirementReport(hardRequirementReport);

                    const issuesList = document.getElementById('issuesList');
                    issuesList.innerHTML = '';
                    if (!val.issues || val.issues.length === 0) {
                        issuesList.innerHTML = '<li class="info">발견된 문제가 없습니다.</li>';
                    } else {
                        val.issues.forEach(issue => {
                            const li = document.createElement('li');
                            li.className = issue.level;
                            li.textContent = `[${issue.field}] ${issue.message}`;
                            issuesList.appendChild(li);
                        });
                    }

                    const confirmList = document.getElementById('confirmList');
                    confirmList.innerHTML = '';
                    if (!spec.needs_confirmation || spec.needs_confirmation.length === 0) {
                        confirmList.innerHTML = '<li class="info">AI가 추정한 값이 없습니다.</li>';
                    } else {
                        spec.needs_confirmation.forEach(path => {
                            const li = document.createElement('li');
                            li.className = 'info';
                            li.textContent = `확인 필요: ${path}`;
                            confirmList.appendChild(li);
                        });
                    }

                    document.getElementById('agentResult').style.display = 'none';
                }

                async function buildPptx() {
                    setLoading(true);
                    try {
                        const res = await fetch('/api/agent/build-pptx', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ specification: state.specification }),
                        });
                        const data = await res.json();
                        if (!res.ok) throw new Error(data.detail || 'PPTX 생성 실패');
                        document.getElementById('agentDownloadLink').href = data.download_url;
                        document.getElementById('agentResult').style.display = 'block';
                    } catch (err) {
                        alert('PPTX 생성 중 오류가 발생했습니다:\\n\\n' + err.message);
                    } finally {
                        setLoading(false);
                    }
                }
            </script>
    """
    return HTMLResponse(content=render_page("전극 검사기 사양서 AI Agent", body_html))


# ==========================================
# 4. PPTX 파일 다운로드 API
# ==========================================
# agent/routes.py의 "/api/agent/build-pptx"가 OUTPUT_DIR(./generated_files)에 PPTX를
# 쓰고 download_url로 이 엔드포인트를 가리킨다 — 전극 검사기 AI가 실제로 쓰는
# 공유 인프라이므로 유지한다 (예전 "/api/generate-spec"이 쓰던 것과 같은 폴더/엔드포인트).
@app.get("/api/download/{file_name}")
async def download_file(file_name: str):
    """
    생성된 PPTX 파일을 다운로드합니다.
    """
    file_path = OUTPUT_DIR / file_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

    return FileResponse(
        path=file_path,
        filename=f"설비사양서_{file_name}",
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )


# ==========================================
# 실행부 (서버 개방)
# ==========================================
if __name__ == "__main__":
    import sys

    from cli_commands import run_cli

    # `python main.py render-md ...` 같은 서브커맨드면 CLI로 처리하고 종료한다.
    # 인자가 없거나 알려진 서브커맨드가 아니면(기존 `python main.py` 그대로)
    # 아래로 내려가 기존과 동일하게 웹 서버를 띄운다.
    if run_cli(sys.argv):
        sys.exit(0)

    import uvicorn
    # host="0.0.0.0" 으로 지정해야 사내망 다른 PC에서 IP로 접속 가능
    # 포트는 AGENT_PORT 환경변수로 오버라이드 가능 (기본값 8000은 기존 동작과 동일)
    port = int(os.environ.get("AGENT_PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
