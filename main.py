import os
import uuid
from pathlib import Path
from fastapi import FastAPI, HTTPException, BackgroundTask
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 앞서 작성한 파이프라인 모듈 임포트
from generator import SpecGenerator
from pptx_builder import PPTXBuilder

app = FastAPI(title="사내망 설비 사양서 자동 생성 시스템")

# 생성된 PPTX 파일이 임시 저장될 폴더
OUTPUT_DIR = Path("./generated_files")
OUTPUT_DIR.mkdir(exist_ok=True)

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
# 1. 메인 웹 페이지 (HTML UI)
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def read_root():
    """
    사내 사용자가 접속할 웹 화면 (HTML/JS)
    """
    html_content = """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>설비 사양서 자동 생성 시스템</title>
        <style>
            body { font-family: '맑은 고딕', sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; background-color: #f5f6f8; }
            .container { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
            h2 { color: #1a2530; margin-bottom: 20px; }
            textarea { width: 100%; height: 120px; padding: 12px; border: 1px solid #ccc; border-radius: 6px; font-size: 14px; box-sizing: border-box; resize: vertical; }
            button { background-color: #2b6cb0; color: white; border: none; padding: 12px 24px; border-radius: 6px; font-size: 16px; cursor: pointer; margin-top: 15px; width: 100%; }
            button:hover { background-color: #2c5282; }
            button:disabled { background-color: #a0aec0; cursor: not-allowed; }
            #loading { display: none; margin-top: 20px; color: #2b6cb0; font-weight: bold; text-align: center; }
            #result { display: none; margin-top: 20px; padding: 15px; background: #e6fffa; border: 1px solid #319795; border-radius: 6px; text-align: center; }
            a.download-btn { display: inline-block; margin-top: 10px; padding: 10px 20px; background: #319795; color: white; text-decoration: none; border-radius: 6px; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>⚙️ 사내망 설비 사양서 자동 생성기</h2>
            <p>원하는 설비 사양 조건(전압, 크기, 성능 등)을 자연어로 자유롭게 입력하세요.</p>
            
            <textarea id="promptInput" placeholder="예시: 300mm 웨이퍼 처리용 고진공 챔버 설비 사양서 만들어줘. 전압은 380V 삼상 사용하고, 도달 진공도는 10^-6 Torr 이상이어야 해."></textarea>
            <button id="generateBtn" onclick="generateSpec()">사양서 PPTX 생성하기</button>

            <div id="loading">⏳ 기존 사양 DB 참조 및 PPTX 사양서를 생성 중입니다... (약 10~20초 소요)</div>
            
            <div id="result">
                <h3>🎉 사양서가 성공적으로 생성되었습니다!</h3>
                <a id="downloadLink" class="download-btn" href="#" download>PPTX 사양서 다운로드</a>
            </div>
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

                    if (!response.ok) {
                        throw new Error('생성 실패');
                    }

                    const data = await response.json();
                    document.getElementById('downloadLink').href = data.download_url;
                    result.style.display = 'block';
                } catch (err) {
                    alert('사양서 생성 중 오류가 발생했습니다. 로그를 확인하세요.');
                } finally {
                    btn.disabled = false;
                    loading.style.display = 'none';
                }
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# ==========================================
# 2. 사양서 생성 API 엔드포인트
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
            raise HTTPException(status_code=500, detail="JSON 생성 실패")

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
# 3. PPTX 파일 다운로드 API
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
# 실행부 (서버 개방)
# ==========================================
if __name__ == "__main__":
    import uvicorn
    # host="0.0.0.0" 으로 지정해야 사내망 다른 PC에서 IP로 접속 가능
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
