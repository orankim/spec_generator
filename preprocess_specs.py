import os

# 폐쇄망 보안 정책: 외부(HuggingFace Hub 등) 네트워크 통신 원천 차단
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import argparse
from glob import glob

from build_rag_ollama import parse_pptx_file
from generator import SpecGenerator
from pptx_builder import PPTXBuilder


def normalize_pptx_file(pptx_path: str, generator: SpecGenerator, builder: PPTXBuilder, output_dir: str) -> bool:
    """
    임의 형식의 PPTX 사양서 1개를 표준 template.pptx 형식으로 변환합니다.
    성공하면 True, 실패(파싱 실패/LLM 추출 실패)하면 False를 반환합니다.
    """
    file_name = os.path.basename(pptx_path)

    slide_docs = parse_pptx_file(pptx_path)
    if not slide_docs:
        print(f"⚠️  [{file_name}] 건너뜀: 추출된 텍스트가 없습니다 (빈 슬라이드이거나 이미지 전용 문서).")
        return False

    document_text = "\n\n".join(doc.page_content for doc in slide_docs)

    print(f"   → LLM으로 표준 스키마 추출 중... ({len(document_text)}자)")
    spec_json = generator.extract_spec_from_document(document_text)

    if "error" in spec_json:
        print(f"⚠️  [{file_name}] 건너뜀: LLM이 표준 형식으로 추출하지 못했습니다. ({spec_json.get('reason')})")
        return False

    output_path = os.path.join(output_dir, file_name)
    builder.build(spec_json, output_path=output_path)
    print(f"✅ [{file_name}] 표준 템플릿으로 정규화 완료 → {output_path}")
    return True


def preprocess_all(input_dir: str, output_dir: str, template_path: str, db_path: str, ollama_base_url: str):
    os.makedirs(output_dir, exist_ok=True)

    pptx_files = sorted(glob(os.path.join(input_dir, "*.pptx")))
    if not pptx_files:
        print(f"경고: '{input_dir}' 경로에 .pptx 파일이 없습니다.")
        return

    print(f"=== 템플릿 전처리 시작: {len(pptx_files)}개 파일 ({input_dir} → {output_dir}) ===\n")

    generator = SpecGenerator(db_path=db_path, ollama_base_url=ollama_base_url)
    builder = PPTXBuilder(template_path=template_path)

    succeeded, failed = [], []
    for pptx_path in pptx_files:
        print(f"[{os.path.basename(pptx_path)}] 처리 중...")
        try:
            ok = normalize_pptx_file(pptx_path, generator, builder, output_dir)
        except Exception as e:
            print(f"⚠️  [{os.path.basename(pptx_path)}] 건너뜀: 예외 발생 ({e})")
            ok = False
        (succeeded if ok else failed).append(os.path.basename(pptx_path))
        print()

    print("=== 전처리 완료 ===")
    print(f"성공: {len(succeeded)}개, 실패: {len(failed)}개")
    if failed:
        print("실패 목록 (원본 그대로 남아있으니 필요시 수동 확인/수정 후 재실행하세요):")
        for name in failed:
            print(f"  - {name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="형식이 제각각인 기존 PPTX 사양서를 표준 template.pptx 형식으로 일괄 정규화합니다."
    )
    parser.add_argument("--input", default="./sample_specs", help="원본(비표준) PPTX 사양서 폴더")
    parser.add_argument("--output", default="./sample_specs_normalized", help="정규화된 PPTX를 저장할 폴더")
    parser.add_argument("--template", default="./template.pptx", help="표준 마스터 템플릿 경로")
    parser.add_argument("--db-path", default="./chroma_db_specs", help="SpecGenerator 초기화용 Vector DB 경로")
    parser.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama 서버 주소")
    args = parser.parse_args()

    preprocess_all(
        input_dir=args.input,
        output_dir=args.output,
        template_path=args.template,
        db_path=args.db_path,
        ollama_base_url=args.ollama_url,
    )
