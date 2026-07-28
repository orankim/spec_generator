import os
from glob import glob
from pptx import Presentation

# LangChain & ChromaDB (Ollama 전용 모듈 사용)
from langchain_core.documents import Document
from langchain_chroma import Chroma
from langchain_community.embeddings import OllamaEmbeddings


# ==========================================
# 1. PPTX 파일 파싱 함수 (텍스트 + 표 추출)
# ==========================================
def parse_pptx_file(file_path: str) -> list[Document]:
    prs = Presentation(file_path)
    file_name = os.path.basename(file_path)
    documents = []

    for slide_idx, slide in enumerate(prs.slides, start=1):
        slide_text_blocks = []
        table_blocks = []

        for shape in slide.shapes:
            # 텍스트 상자 추출
            if shape.has_text_frame:
                text = shape.text_frame.text.strip()
                if text:
                    slide_text_blocks.append(text)

            # 표(Table) 추출 -> 마크다운 형식 변환
            elif shape.has_table:
                table = shape.table
                table_str_rows = []
                for row_idx, row in enumerate(table.rows):
                    row_cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                    row_formatted = " | ".join(row_cells)
                    table_str_rows.append(f"| {row_formatted} |")
                    
                    if row_idx == 0:
                        table_str_rows.append("|" + "|".join(["---"] * len(row.cells)) + "|")

                if table_str_rows:
                    table_md = "\n".join(table_str_rows)
                    table_blocks.append(f"[표/규격 데이터]:\n{table_md}")

        full_slide_content = []
        if slide_text_blocks:
            full_slide_content.append("--- 슬라이드 텍스트 ---")
            full_slide_content.extend(slide_text_blocks)
        if table_blocks:
            full_slide_content.append("\n--- 사양/규격 표 데이터 ---")
            full_slide_content.extend(table_blocks)

        page_text = "\n".join(full_slide_content).strip()

        if not page_text:
            continue

        metadata = {
            "source": file_name,
            "file_path": file_path,
            "slide_number": slide_idx
        }

        doc = Document(
            page_content=f"문서명: {file_name} (슬라이드 {slide_idx})\n\n{page_text}",
            metadata=metadata
        )
        documents.append(doc)

    print(f"  └─ [{file_name}] 완료: 총 {len(documents)}개 슬라이드 파싱됨")
    return documents


# ==========================================
# 2. Ollama 기반 Vector DB 구축 함수
# ==========================================
def build_vector_db_with_ollama(pptx_folder_path: str, db_save_path: str):
    print("=== 1단계: PPTX 파일 파싱 시작 ===")
    pptx_files = glob(os.path.join(pptx_folder_path, "*.pptx"))
    
    if not pptx_files:
        print(f"경고: '{pptx_folder_path}' 경로에 .pptx 파일이 없습니다.")
        return None

    all_documents = []
    for pptx_file in pptx_files:
        docs = parse_pptx_file(pptx_file)
        all_documents.extend(docs)

    print(f"\n총 {len(all_documents)}개의 슬라이드 문서가 준비되었습니다.")

    print("\n=== 2단계: 사내 Ollama 임베딩 엔진 연결 ===")
    # 사내 로컬 Ollama 백엔드 서비스 활용 (인터넷 통신 없음)
    embeddings = OllamaEmbeddings(
        model="bge-m3",                      # Ollama에 들어있는 임베딩 모델명
        base_url="http://localhost:11434"    # 백그라운드 구동 중인 Ollama 주소
    )

    print("\n=== 3단계: Chroma Vector DB 생성 및 저장 ===")
    vector_store = Chroma.from_documents(
        documents=all_documents,
        embedding=embeddings,
        persist_directory=db_save_path
    )
    print(f"성공! Vector DB가 '{db_save_path}' 경로에 저장되었습니다.\n")
    return vector_store


# ==========================================
# 3. 검색 테스트 함수
# ==========================================
def test_search(query: str, db_save_path: str):
    print(f"\n=== 검색 테스트: '{query}' ===")
    
    embeddings = OllamaEmbeddings(
        model="bge-m3",
        base_url="http://localhost:11434"
    )
    
    vector_store = Chroma(
        persist_directory=db_save_path,
        embedding_function=embeddings
    )

    # 유사도 기준 상위 2개 결과 검색
    results = vector_store.similarity_search(query, k=2)

    for i, doc in enumerate(results, start=1):
        print(f"\n[검색 결과 {i}] (출처: {doc.metadata['source']} - {doc.metadata['slide_number']}페이지)")
        print("-" * 50)
        print(doc.page_content)
        print("-" * 50)


# ==========================================
# 실행부
# ==========================================
if __name__ == "__main__":
    PPTX_FOLDER = "./sample_specs"   # 파싱할 사양서 PPTX 폴더
    DB_PATH = "./chroma_db_specs"    # 저장할 DB 폴더

    os.makedirs(PPTX_FOLDER, exist_ok=True)

    # 1. DB 구축 실행
    build_vector_db_with_ollama(PPTX_FOLDER, DB_PATH)

    # 2. 검색 테스트 (원하는 사양 단어로 검색해보세요)
    # test_search("전력 및 전압 사양", DB_PATH)
