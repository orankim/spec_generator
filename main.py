import os
import uuid
from typing import Dict, Any
from fastapi import FastAPI, Request, Form, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# 기존에 작성한 백엔드 모듈 불러오기
from generator import SpecGenerator
from pptx_builder import PPTXBuilder

# ==========================================
# 1. 앱 설정 및 디렉터리 생성
# ==========================================
app = FastAPI(title="사내망 설비 사양서 자동 생성 시스템")

# 결과물 저장 폴더 및 템플릿 폴더 설정
OUTPUT_DIR = "./generated_files"
TEMPLATE_PPTX = "template.pptx"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 백엔드 엔진 초기화 (서버 시작 시 1회 로드)
print("=== 사내 AI 엔진 및 RAG DB 로딩 중... ===")
spec_generator = SpecGenerator(db_path="./chroma_db_specs", ollama_base_url="http://localhost:11434")
pptx_builder = PPTXBuilder(template_path=TEMPLATE_PPTX)
print("=== 엔진 준비 완료 ===")

# 작업 상태 저장용 임시 딕셔너리
task_status: Dict[str, Dict[str, Any]] = {}


# ==========================================
# 2. API 요청/응답 스키마
# ==========================================
class SpecRequest(BaseModel):
    user_prompt: str


# ==========================================
# 3. 비동기 사양서 생성 작업 함수
# ==========================================
def process_spec_generation(task_id: str, user_prompt: str):
    try:
        task_status[task_id] = {"status": "processing", "message": "사내 DB 검색 및 AI 사양 생성 중..."}

        # 1) RAG + Ollama(Qwen2.5) 기반 JSON 데이터 생성
        spec_json = spec_generator.generate_spec_json(user_prompt)

        if "error" in spec_json:
            task_status[task_id] = {"status": "failed", "message": "JSON 데이터 생성에 실패했습니다."}
            return

        task_status[task_id]["message"] = "PPTX 사양서 파일 생성 중..."

        # 2) PPTX 파일 합성
        output_filename = f"Spec_{task_id[:8]}.pptx"
        output_filepath = os.path.join(OUTPUT_DIR, output_filename)
        
        pptx_builder.build(spec_json, output_path=output_filepath)

        # 3) 완료 상태 업데이트
        task_status[task_id] = {
            "status": "completed",
            "message": "생성 완료!",
            "file_name": output_filename,
            "file_path": output_filepath,
            "data": spec_json
        }
    except Exception as e:
        print(f"❌ 작업 처리 중 에러 발생 (Task {task_id}): {e}")
        task_status[task_id] = {"status": "failed", "message": str(e)}


# ==========================================
# 4. 웹 라우터 (Endpoints)
# ==========================================

# A. 웹 UI 메인 화면 (HTML)
@app.get("/", response_class=HTMLResponse)
async def get_index():
    # 간단한 내장 HTML/JS UI 반환 (별도 프론트엔드 빌드 필요 없음)
    html_content = """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <title>사내 설비 사양서 자동 생성 시스템</title>
        <style>
            body { font-family: 'Segoe UI', Arial, sans-serif; margin: 40px; background-color: #f4f6f9; }
            .container { max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
            h1 { color: #1e293b; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px; }
            textarea { width: 100%; height: 120px; padding: 10px; border: 1px solid #cbd5e1; border-radius: 6px; box-sizing: border-box; font-size: 14px; margin-bottom: 15px; }
            button { background-color: #2563eb; color: white; border: none; padding: 12px 24px; border-radius: 6px; cursor: pointer; font-size: 16px; font-weight: bold; }
            button:hover { background-color: #1d4ed8; }
            #status-box { margin-top: 20px; padding: 15px; border-radius: 6px; display: none; }
            .processing { background-color: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd; }
            .completed { background-color: #dcfce7; color: #15803d; border: 1px solid #bbf7d0; }
            .failed { background-color: #fee2e2; color: #b91c1c; border: 1px solid #fecaca; }
            .download-btn { display: inline-block; margin-top: 10px; background-color: #16a34a; color: white; padding: 10px 20px; text-decoration: none; border-radius: 6px; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>⚙️ 설비 사양서 자동 생성 시스템</h1>
            <p>원하는 설비 사양 조건(전압, 크기, 진공도, 용량 등)을 자연어로 입력하면 기존 사내 사양서를 참고하여 PPTX 파일로 제작해 드립니다.</p>
            
            <textarea id="userPrompt" placeholder="예: 300mm 웨이퍼 처리용 고진공 챔버 설비 사양서 만들어줘. 전압은 380V 삼상 사용하고, 도달 진공도는 10^-6 Torr 이상이어야 해."></textarea>
            <br>
            <button onclick="generateSpec()">사양서 PPTX 생성 요청</button>

            <div id="status-box"></div>
        </div>

        <script>
            let currentTaskId = null;
            let pollTimer = null;

            async function generateSpec() {
                const prompt = document.getElementById('userPrompt').value.trim();
                if (!prompt) {
                    alert('요구사항을 입력해 주세요.');
                    return;
                }

                const statusBox = document.getElementById('status-box');
                statusBox.style.display = 'block';
                statusBox.className = 'processing';
                statusBox.innerHTML = '🚀 서버로 사양서 생성 요청을 전달하는 중...';

                try {
                    const response = await fetch('/api/generate', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ user_prompt: prompt })
                    });
                    const data = await response.json();
                    currentTaskId = data.task_id;

                    // 상태 폴링 시작
                    pollTimer = setInterval(checkStatus, 2000);
                } catch (error) {
                    statusBox.className = 'failed';
                    statusBox.innerHTML = '❌ 요청 중 에러가 발생했습니다: ' + error;
                }
            }

            async function checkStatus() {
                if (!currentTaskId) return;

                const response = await fetch('/api/status/' + currentTaskId);
                const data = await response.json();

                const statusBox = document.getElementById('status-box');

                if (data.status === 'processing') {
                    statusBox.className = 'processing';
                    statusBox.innerHTML = '⏳ ' + data.message;
                } else if (data.status === 'completed') {
                    clearInterval(pollTimer);
                    statusBox.className = 'completed';
                    statusBox.innerHTML = `
                        🎉 <strong>사양서 생성 완료!</strong><br>
                        파일 명: ${data.file_name}<br><br>
                        <a href="/api/download/${data.file_name}" class="download-btn">📥 PPTX 사양서 다운로드</a>
                    `;
                } else if (data.status === 'failed') {
                    clearInterval(pollTimer);
                    statusBox.className = 'failed';
                    statusBox.innerHTML = '❌ 생성 실패: ' + data.message;
                }
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# B. 사양서 생성 요청 API
@app.post("/api/generate")
async def start_generation(req: SpecRequest, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    task_status[task_id] = {"status": "queued", "message": "작업 대기 중..."}
    
    # 백그라운드 작업으로 추론 수행 (웹 서버 응답이 멈추지 않도록 처리)
    background_tasks.add_task(process_spec_generation, task_id, req.user_prompt)
    
    return {"task_id": task_id, "status": "queued"}


# C. 작업 진척도 확인 API
@app.get("/api/status/{task_id}")
async def get_status(task_id: str):
    status_info = task_status.get(task_id)
    if not status_info:
        raise HTTPException(status_code=404, detail="존재하지 않는 작업 ID입니다.")
    return status_info


# D. 완성된 PPTX 다운로드 API
@app.get("/api/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )


# ==========================================
# 실행부 (개발용 단독 실행)
# ==========================================
if __name__ == "__main__":
    import uvicorn
    # 사내 LAN 전체 접속을 허용하려면 host="0.0.0.0" 지정
    print("🚀 사내 웹 서버 구동 시작: http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
