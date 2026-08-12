import logging
import os
import uuid
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

# .env 파일이 있으면 로드 (없어도 조용히 무시됨 - 환경변수를 직접 export해도 동일하게 동작)
load_dotenv()

# 폐쇄망 보안 정책: 외부(HuggingFace Hub 등) 네트워크 통신 원천 차단
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# 앞서 작성한 파이프라인 모듈 임포트
from generator import SpecGenerator
from pptx_builder import PPTXBuilder
from agent.routes import router as agent_router
from agent.ollama_client import check_ollama_available

app = FastAPI(title="사내망 설비 사양서 자동 생성 시스템")
app.include_router(agent_router)

# 생성된 PPTX 파일이 임시 저장될 폴더
OUTPUT_DIR = Path("./generated_files")
OUTPUT_DIR.mkdir(exist_ok=True)

# 업로드된(RAG 학습용) 기존 사양서 PPTX가 저장될 폴더
SAMPLE_SPECS_DIR = Path("./sample_specs")
SAMPLE_SPECS_DIR.mkdir(exist_ok=True)

# 템플릿 파일 경로
TEMPLATE_PATH = "template.pptx"

# Ollama 서버/모델 설정 (환경변수로 오버라이드 가능, 기본값은 기존 하드코딩 값과 동일)
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# SpecGenerator & PPTXBuilder 인스턴스 초기화
print("=== AI 엔진 및 RAG DB 로딩 중... ===")
generator = SpecGenerator(
    db_path="./chroma_db_specs",
    ollama_base_url=OLLAMA_HOST
)
builder = PPTXBuilder(template_path=TEMPLATE_PATH)
print("=== 서비스 준비 완료 ===")

if not check_ollama_available(OLLAMA_HOST):
    logger.warning(
        "Ollama 서버(%s)에 연결할 수 없습니다. 서버는 계속 기동하지만, "
        "사양서 생성/전극 검사기 Agent 기능은 Ollama가 켜져 있어야 동작합니다.",
        OLLAMA_HOST,
    )


# 요청 Body 데이터 구조
class SpecRequest(BaseModel):
    prompt: str


# ==========================================
# 1. 공통 페이지 레이아웃 (탭 네비게이션 + 공통 스타일)
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
    .tab-toggle { display: flex; gap: 8px; margin-bottom: 15px; }
    .tab-toggle button { width: auto; flex: 1; background: #e8eef5; color: #2b6cb0; margin-top: 0; }
    .tab-toggle button.active { background: #2b6cb0; color: white; }
"""


def render_page(title: str, active: str, body_html: str) -> str:
    """
    두 페이지(사양서 제작하기 / 업로드하기)가 공유하는 상단 네비게이션과 스타일을 적용해
    완성된 HTML 문서를 만듭니다.
    """
    nav_generate_class = "active" if active == "generate" else ""
    nav_upload_class = "active" if active == "upload" else ""
    nav_agent_class = "active" if active == "agent" else ""
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
                <a href="/" class="{nav_generate_class}">📋 사양서 제작하기</a>
                <a href="/upload" class="{nav_upload_class}">📤 사양서 업로드하기</a>
                <a href="/agent" class="{nav_agent_class}">🔬 전극 검사기 AI</a>
            </div>
            {body_html}
        </div>
    </body>
    </html>
    """


# ==========================================
# 2. 사양서 제작하기 페이지
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def read_root():
    """
    자연어 요구사항으로 새 사양서 PPTX를 생성하는 화면
    """
    body_html = """
            <h2>⚙️ 사내망 설비 사양서 자동 생성기</h2>
            <p>원하는 설비 사양 조건(전압, 크기, 성능 등)을 자연어로 자유롭게 입력하세요.</p>

            <textarea id="promptInput" placeholder="예시: 300mm 웨이퍼 처리용 고진공 챔버 설비 사양서 만들어줘. 전압은 380V 삼상 사용하고, 도달 진공도는 10^-6 Torr 이상이어야 해."></textarea>
            <button id="generateBtn" onclick="generateSpec()">사양서 PPTX 생성하기</button>

            <div id="loading">⏳ 기존 사양 DB 참조 및 PPTX 사양서를 생성 중입니다... (약 10~20초 소요)</div>

            <div id="result">
                <h3>🎉 사양서가 성공적으로 생성되었습니다!</h3>
                <a id="downloadLink" class="download-btn" href="#" download>PPTX 사양서 다운로드</a>
            </div>

            <script>
                async function generateSpec() {
                    const prompt = document.getElementById('promptInput').value.trim();
                    if (!prompt) {
                        alert('설비 요구사항을 입력해 주세요.');
                        return;
                    }

                    const btn = document.getElementById('generateBtn');
                    const loading = document.getElementById('loading');
                    const result = document.getElementById('result');

                    btn.disabled = true;
                    loading.style.display = 'block';
                    result.style.display = 'none';

                    try {
                        const response = await fetch('/api/generate-spec', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ prompt: prompt })
                        });

                        const data = await response.json();

                        if (!response.ok) {
                            throw new Error(data.detail || '생성 실패');
                        }

                        document.getElementById('downloadLink').href = data.download_url;
                        result.style.display = 'block';
                    } catch (err) {
                        alert('사양서 생성 중 오류가 발생했습니다:\\n\\n' + err.message);
                    } finally {
                        btn.disabled = false;
                        loading.style.display = 'none';
                    }
                }
            </script>
    """
    return HTMLResponse(content=render_page("설비 사양서 자동 생성 시스템", "generate", body_html))


# ==========================================
# 3. 사양서 업로드하기 페이지
# ==========================================
@app.get("/upload", response_class=HTMLResponse)
async def upload_page():
    """
    RAG 학습용 기존 사양서 PPTX를 클라이언트 PC에서 서버로 업로드하는 화면.
    업로드된 파일은 sample_specs/ 폴더에 저장되며, 이후 서버 관리자가
    preprocess_specs.py(전처리) → build_rag_ollama.py(Vector DB 구축)를
    실행해야 실제 검색/생성에 반영됩니다.
    """
    body_html = """
            <h2>📤 기존 사양서 업로드하기</h2>
            <p>RAG 학습에 사용할 기존 설비 사양서 PPTX 파일을 업로드하세요. (여러 개 동시 선택 가능)</p>
            <p style="font-size:13px;color:#888;">업로드된 파일은 서버의 <code>sample_specs/</code> 폴더에 저장됩니다. 검색에 실제로 반영되려면 서버 관리자가 전처리 및 Vector DB 재구축 스크립트를 실행해야 합니다.</p>

            <input type="file" id="fileInput" accept=".pptx" multiple>
            <button id="uploadBtn" onclick="uploadSpecs()">업로드하기</button>

            <div id="loading">⏳ 업로드 중입니다...</div>

            <div id="result">
                <h3 id="resultTitle">🎉 업로드가 완료되었습니다!</h3>
                <ul id="fileList"></ul>
            </div>

            <script>
                async function uploadSpecs() {
                    const input = document.getElementById('fileInput');
                    if (!input.files.length) {
                        alert('업로드할 PPTX 파일을 선택해 주세요.');
                        return;
                    }

                    const formData = new FormData();
                    for (const file of input.files) {
                        formData.append('files', file);
                    }

                    const btn = document.getElementById('uploadBtn');
                    const loading = document.getElementById('loading');
                    const result = document.getElementById('result');

                    btn.disabled = true;
                    loading.style.display = 'block';
                    result.style.display = 'none';

                    try {
                        const response = await fetch('/api/upload-specs', {
                            method: 'POST',
                            body: formData
                        });

                        const data = await response.json();

                        if (!response.ok) {
                            throw new Error(data.detail || '업로드 실패');
                        }

                        const fileList = document.getElementById('fileList');
                        fileList.innerHTML = '';
                        data.saved.forEach(name => {
                            const li = document.createElement('li');
                            li.textContent = '✅ ' + name;
                            fileList.appendChild(li);
                        });
                        data.skipped.forEach(name => {
                            const li = document.createElement('li');
                            li.textContent = '⚠️ ' + name + ' (.pptx 파일이 아니라 건너뜀)';
                            fileList.appendChild(li);
                        });

                        document.getElementById('resultTitle').textContent =
                            `🎉 ${data.saved.length}개 파일 업로드 완료!`;
                        result.style.display = 'block';
                        input.value = '';
                    } catch (err) {
                        alert('업로드 중 오류가 발생했습니다:\\n\\n' + err.message);
                    } finally {
                        btn.disabled = false;
                        loading.style.display = 'none';
                    }
                }
            </script>
    """
    return HTMLResponse(content=render_page("기존 사양서 업로드", "upload", body_html))


# ==========================================
# 3-1. 전극 검사기 사양서 자동 생성 AI Agent 페이지
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

                function renderRequirementSummary() {
                    const req = state.requirement;
                    const val = state.validation;

                    document.getElementById('reqSummary').innerHTML = `
                        <strong>검사 대상:</strong> ${req.target.material || '미정'}<br>
                        <strong>폭:</strong> ${req.target.width_mm ?? '미정'} mm<br>
                        <strong>검사 항목:</strong> ${(req.inspection_items || []).join(', ') || '미정'}<br>
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
                        renderSpecSummary(data.retrieved_sources || []);
                        goToStep('step3');
                    } catch (err) {
                        alert('사양서 생성 중 오류가 발생했습니다:\\n\\n' + err.message);
                    } finally {
                        setLoading(false);
                    }
                }

                function fmtSourced(sn) {
                    if (!sn || sn.value === null || sn.value === undefined) return 'N/A';
                    const sourceLabel = {user_requirement: '사용자 요구사항', document: sn.source || '문서', inferred: 'AI 추정', default: '기본값'}[sn.source_type] || '-';
                    return `${sn.value}${sn.unit ? ' ' + sn.unit : ''} (${sourceLabel})`;
                }

                function renderSpecSummary(retrievedSources) {
                    const spec = state.specification;
                    const val = state.specValidation;

                    document.getElementById('specSummary').innerHTML = `
                        <strong>설비명:</strong> ${spec.equipment.name || 'N/A'}<br>
                        <strong>검사 대상:</strong> ${spec.inspection_target.material || 'N/A'} (${spec.inspection_target.width_mm ?? '?'} mm)<br>
                        <strong>검사 항목:</strong> ${(spec.inspection_items || []).join(', ') || 'N/A'}<br>
                        <strong>정확도:</strong> ${fmtSourced(spec.measurement_performance.accuracy_um)}<br>
                        <strong>분해능:</strong> ${fmtSourced(spec.measurement_performance.resolution_um)}<br>
                        <strong>최소 검출 결함 크기:</strong> ${fmtSourced(spec.defect_detection.minimum_defect_size_um)}<br>
                        <strong>참고 문서:</strong> ${(spec.sources || []).join(', ') || '없음'} (검색된 chunk ${retrievedSources.length}개)
                    `;

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
    return HTMLResponse(content=render_page("전극 검사기 사양서 AI Agent", "agent", body_html))


# ==========================================
# 4. 사양서 생성 API 엔드포인트
# ==========================================
@app.post("/api/generate-spec")
async def generate_spec_api(req: SpecRequest):
    """
    1) RAG + Ollama로 JSON 사양서 데이터 생성
    2) PPTX 파일로 합성 후 다운로드 URL 반환
    """
    try:
        # 1) LLM + RAG 기반 JSON 생성
        spec_json = generator.generate_spec_json(req.prompt)

        if "error" in spec_json:
            reason = spec_json.get("reason", "알 수 없는 오류")
            raw = spec_json.get("raw_response", "")[:500]
            raise HTTPException(
                status_code=500,
                detail=f"JSON 생성 실패: {reason} | LLM 원문 응답: {raw}"
            )

        # 2) 고유한 파일명 생성
        file_id = str(uuid.uuid4())[:8]
        output_filename = f"spec_{file_id}.pptx"
        output_filepath = OUTPUT_DIR / output_filename

        # 3) PPTX 합성
        builder.build(spec_json, output_path=str(output_filepath))

        return {
            "status": "success",
            "file_name": output_filename,
            "download_url": f"/api/download/{output_filename}"
        }

    except Exception as e:
        print(f"API 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# 5. PPTX 파일 다운로드 API
# ==========================================
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
# 6. 기존 사양서 업로드 API (sample_specs/ 에 저장)
# ==========================================
@app.post("/api/upload-specs")
async def upload_specs_api(files: List[UploadFile] = File(...)):
    """
    클라이언트 PC에서 올린 기존 사양서 PPTX 파일들을 sample_specs/ 폴더에 저장합니다.
    .pptx가 아닌 파일은 저장하지 않고 skipped 목록으로 반환합니다.
    """
    saved, skipped = [], []

    for upload in files:
        # Path(...).name 으로 경로 구분자를 제거해 경로 조작(디렉터리 탈출)을 방지
        safe_name = Path(upload.filename or "").name
        if not safe_name.lower().endswith(".pptx"):
            skipped.append(upload.filename or "(파일명 없음)")
            continue

        dest_path = SAMPLE_SPECS_DIR / safe_name
        content = await upload.read()
        dest_path.write_bytes(content)
        saved.append(safe_name)

    return {"status": "success", "saved": saved, "skipped": skipped}


# ==========================================
# 실행부 (서버 개방)
# ==========================================
if __name__ == "__main__":
    import uvicorn
    # host="0.0.0.0" 으로 지정해야 사내망 다른 PC에서 IP로 접속 가능
    # 포트는 AGENT_PORT 환경변수로 오버라이드 가능 (기본값 8000은 기존 동작과 동일)
    port = int(os.environ.get("AGENT_PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
