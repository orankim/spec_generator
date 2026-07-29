import os
import uuid
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

# 폐쇄망 보안 정책: 외부(HuggingFace Hub 등) 네트워크 통신 원천 차단
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# 앞서 작성한 파이프라인 모듈 임포트
from generator import SpecGenerator
from pptx_builder import PPTXBuilder

app = FastAPI(title="사내망 설비 사양서 자동 생성 시스템")

# 생성된 PPTX 파일이 임시 저장될 폴더
OUTPUT_DIR = Path("./generated_files")
OUTPUT_DIR.mkdir(exist_ok=True)

# 업로드된(RAG 학습용) 기존 사양서 PPTX가 저장될 폴더
SAMPLE_SPECS_DIR = Path("./sample_specs")
SAMPLE_SPECS_DIR.mkdir(exist_ok=True)

# 템플릿 파일 경로
TEMPLATE_PATH = "template.pptx"

# SpecGenerator & PPTXBuilder 인스턴스 초기화
print("=== AI 엔진 및 RAG DB 로딩 중... ===")
generator = SpecGenerator(
    db_path="./chroma_db_specs",
    ollama_base_url="http://localhost:11434"
)
builder = PPTXBuilder(template_path=TEMPLATE_PATH)
print("=== 서비스 준비 완료 ===")


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
"""


def render_page(title: str, active: str, body_html: str) -> str:
    """
    두 페이지(사양서 제작하기 / 업로드하기)가 공유하는 상단 네비게이션과 스타일을 적용해
    완성된 HTML 문서를 만듭니다.
    """
    nav_generate_class = "active" if active == "generate" else ""
    nav_upload_class = "active" if active == "upload" else ""
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
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
