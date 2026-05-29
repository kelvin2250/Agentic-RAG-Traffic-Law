from __future__ import annotations

# PHẢI SETUP LOGGING TRƯỜC KHI IMPORT PACKAGE KHÁC
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

import os
import re
import tempfile
import time
import sys
from pathlib import Path

import fitz  # PyMuPDF
from google import genai
import pdfplumber
from dotenv import load_dotenv
from llama_parse import LlamaParse
from unstructured.partition.docx import partition_docx
import pytesseract
from pdf2image import convert_from_path

load_dotenv()

# ---------------------- CẤU HÌNH TESSERACT & POPPLER ----------------------
POPPLER_PATH = None
conda_prefix = os.path.dirname(os.path.dirname(sys.executable))
possible_poppler = os.path.join(conda_prefix, "Library", "bin")

TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(TESSERACT_PATH):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
    logging.info(f"Tesseract OK: {TESSERACT_PATH}")
else:
    logging.error("Không tìm thấy Tesseract. Hãy cài từ: https://github.com/UB-Mannheim/tesseract/wiki")

LANG = 'vie' if 'vie' in pytesseract.get_languages(config='') else 'eng'
logging.info(f"📖 Ngôn ngữ OCR: {LANG}")

DRY_RUN = False
LLAMA_API_KEY = os.getenv("LLAMA_CLOUD_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

SCRIPT_DIR = Path(__file__).resolve().parent
# PROJECT_ROOT should be the repository root (two levels up from this file)
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DEFAULT_INPUT_DIR = PROJECT_ROOT / "data" / "raw_filter_domain"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "processed_filter_domain"
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}

cost_stats = {
    "total_pdf_pages_scanned": 0,
    "llamaparse_calls": 0,
    "gemini_calls": 0,
    "docx_processed": 0,
    "ocr_calls": 0, 
}

TEXT_SYSTEM_INSTRUCTION = """Bạn là chuyên gia xử lý dữ liệu thô.
Nhiệm vụ: Khôi phục cấu trúc bảng biểu từ văn bản thô bị vỡ.

QUY TẮC:
1. Giữ nguyên nội dung văn bản, chỉ dựng lại bảng bằng định dạng Markdown Table (| --- |).
2. Nếu các dòng bị rớt xuống, hãy nối lại cho đúng hàng/cột của bảng.
3. Trả về văn bản thuần túy, không có lời dẫn, không có code block (```).
"""

GENAI_MODEL: genai.GenerativeModel | None = None
LLAMA_PARSER: LlamaParse | None = None


def ensure_gemini_model() -> genai.GenerativeModel | None:
    global GENAI_MODEL

    if GENAI_MODEL is not None:
        return GENAI_MODEL
    if not GEMINI_API_KEY:
        return None

    genai.configure(api_key=GEMINI_API_KEY)
    GENAI_MODEL = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=TEXT_SYSTEM_INSTRUCTION,
        generation_config={
            "temperature": 0.0,
            "top_p": 0.95,
            "max_output_tokens": 8192,
        },
    )
    return GENAI_MODEL


def ensure_llama_parser() -> LlamaParse | None:
    global LLAMA_PARSER

    if LLAMA_PARSER is not None:
        return LLAMA_PARSER
    if not LLAMA_API_KEY:
        return None

    LLAMA_PARSER = LlamaParse(
        api_key=LLAMA_API_KEY,
        result_type="markdown",
        use_vendor_multimodal_model=True,
        language="vi",
    )
    return LLAMA_PARSER


def check_has_dieu(text: str) -> bool:
    return bool(re.search(r"^\s*Điều\s+\d+", text, re.MULTILINE))


def get_chunk_pattern(has_dieu: bool) -> str:
    if has_dieu:
        return r"(?=(?:^\s*Điều\s+\d+|^\s*Chương\s+[IVXLCDM]+|^\s*Phụ lục))"
    return r"(?m)(?=(?:^\s*\d+\.\s+[A-ZĐÁÀẢÃẠÂẤẦẨẪẬĂẮẰẲẴẶEÉÈẺẼẸÊẾỀỂỄỆIÍÌỈĨỊOÓÒỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢUÚÙỦŨỤƯỨỪỬỮỰYÝỲỶỸỴ]))"


def contains_table(text_chunk: str) -> bool:
    if re.search(r"bảng\s+\d+", text_chunk, re.IGNORECASE):
        return True

    return False


def strip_code_fences(text: str) -> str:
    text = re.sub(r"^```markdown\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text, flags=re.IGNORECASE)
    return text.strip()


def standardize_legal_txt_to_md(raw_text: str, has_dieu: bool) -> str:
    text = raw_text
    # Removed bullet list standardization to preserve original list symbols
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def rescue_txt_tables_with_llm(text_chunk: str, filename: str) -> str:
    cost_stats["gemini_calls"] += 1

    if DRY_RUN:
        logging.info("[DRY RUN] Gemini LLM rescue cho: %s", filename)
        return f"<!-- DRY RUN: LLM xử lý bảng cho {filename} -->\n\n{text_chunk}"

    model = ensure_gemini_model()
    if model is None:
        logging.info("Không có GEMINI_API_KEY, dùng regex fallback cho: %s", filename)
        return standardize_legal_txt_to_md(text_chunk, check_has_dieu(text_chunk))

    user_prompt = (
        f"HÃY KHÔI PHỤC BẢNG VÀ CHUẨN HÓA MARKDOWN CHO ĐOẠN VĂN BẢN SAU (FILE: {filename}):\n\n"
        f"{text_chunk}"
    )

    try:
        response = model.generate_content(user_prompt)
        return strip_code_fences(response.text)
    except Exception as exc:
        logging.error("Lỗi Gemini API tại file %s: %s", filename, exc)
        return standardize_legal_txt_to_md(text_chunk, check_has_dieu(text_chunk))

def ocr_page_with_tesseract(pdf_path: str, page_num: int, dpi: int = 200) -> str:
    """
    Chuyển một trang PDF thành ảnh và OCR bằng Tesseract.
    pdf_path: đường dẫn file PDF gốc
    page_num: số trang (bắt đầu từ 0)
    dpi: 200 là cân bằng tốc độ/chất lượng
    """
    images = convert_from_path(
        pdf_path, dpi=dpi, first_page=page_num+1, last_page=page_num+1,
        poppler_path=POPPLER_PATH
    )
    if not images:
        return ""
    text = pytesseract.image_to_string(images[0], lang=LANG)
    # Làm sạch: xóa dòng chỉ toàn số (số trang), chuẩn hóa xuống dòng
    lines = text.split('\n')
    filtered_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not re.fullmatch(r'[\d\s\.]+', stripped):
            filtered_lines.append(line)
    text = '\n'.join(filtered_lines)
    text = re.sub(r'\n\s*\n', '\n\n', text.strip())
    return text

def process_single_txt(file_path: str) -> tuple[str, int]:
    filename = os.path.basename(file_path)
    with open(file_path, "r", encoding="utf-8") as file_handle:
        raw_text = file_handle.read()

    has_dieu = check_has_dieu(raw_text)
    chunks = re.split(get_chunk_pattern(has_dieu), raw_text)
    final_markdown: list[str] = []
    llm_call_count = 0

    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        if contains_table(chunk):
            cleaned_chunk = rescue_txt_tables_with_llm(chunk, filename)
            md_chunk = standardize_legal_txt_to_md(cleaned_chunk, has_dieu)
            llm_call_count += 1
        else:
            md_chunk = standardize_legal_txt_to_md(chunk, has_dieu)

        final_markdown.append(md_chunk)

    return "\n\n".join(final_markdown), llm_call_count


def process_txt_router(file_path: str) -> str:
    markdown_text, _ = process_single_txt(file_path)
    return markdown_text


def process_docx(file_path: str) -> str:
    try:
        elements = partition_docx(filename=file_path)
    except Exception as exc:
        logging.warning("Không thể phân tích DOCX %s: %s", file_path, exc)
        return ""

    blocks: list[str] = []
    for element in elements:
        element_type = type(element).__name__
        content = str(element).strip()
        if not content:
            continue

        if element_type in {"Title", "Heading1"}:
            blocks.append(f"# {content}")
        elif element_type == "Heading2":
            blocks.append(f"## {content}")
        elif element_type == "ListItem":
            blocks.append(f"- {content}")
        else:
            blocks.append(content)

    raw_clean_text = "\n\n".join(blocks)
    cost_stats["docx_processed"] += 1
    return standardize_legal_txt_to_md(raw_clean_text, check_has_dieu(raw_clean_text))


def check_real_table(page_detector) -> bool:
    tables = page_detector.find_tables()
    if not tables:
        return False

    for table in tables:
        extracted = table.extract()
        if extracted and len(extracted) >= 2 and len(extracted[0]) >= 2:
            return True
    return False


def process_pdf_smart_router(file_path: str) -> str:
    filename = os.path.basename(file_path)
    final_markdown: list[str] = []
    file_llamaparse_calls = 0
    pages_with_text = 0
    pages_ocr = 0
    pages_with_table = 0

    try:
        with pdfplumber.open(file_path) as pdf_detector, fitz.open(file_path) as doc_reader:
            total_pages = len(pdf_detector.pages)
            cost_stats["total_pdf_pages_scanned"] += total_pages
            logging.info(f"📄 Xử lý {filename}: {total_pages} trang")

            for page_num, page_detector in enumerate(pdf_detector.pages):
                has_table = check_real_table(page_detector)

                # ---------- TRƯỜNG HỢP CÓ BẢNG: DÙNG LLAMAPARSE ----------
                if has_table:
                    pages_with_table += 1
                    cost_stats["llamaparse_calls"] += 1
                    file_llamaparse_calls += 1

                    if DRY_RUN:
                        logging.info(
                            "[DRY RUN] File %s trang %s cần gọi LlamaParse (tổng dự kiến của file: %s)",
                            filename, page_num + 1, file_llamaparse_calls,
                        )
                        final_markdown.append(f"<!-- [DRY RUN: LlamaParse trang {page_num + 1} của {filename}] -->")
                        continue

                    parser = ensure_llama_parser()
                    if parser is None:
                        # fallback: thử text layer, nếu không thì OCR
                        page_text = doc_reader[page_num].get_text("text")
                        if page_text.strip():
                            pages_with_text += 1
                            final_markdown.append(standardize_legal_txt_to_md(page_text, check_has_dieu(page_text)))
                        else:
                            pages_ocr += 1
                            cost_stats["ocr_calls"] += 1
                            logging.info(f"   OCR trang {page_num + 1}/{total_pages}")
                            ocr_text = ocr_page_with_tesseract(file_path, page_num)
                            final_markdown.append(ocr_text)
                        continue

                    logging.info("Phát hiện bảng thậ ở trang %s của %s. Đang gọi LlamaParse...", page_num + 1, filename)
                    doc_single = fitz.open()
                    doc_single.insert_pdf(doc_reader, from_page=page_num, to_page=page_num)
                    temp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
                    temp_pdf_path = temp_pdf.name
                    temp_pdf.close()

                    try:
                        doc_single.save(temp_pdf_path)
                        parsed_page = parser.load_data(temp_pdf_path)
                        if parsed_page:
                            final_markdown.append(parsed_page[0].text.strip())
                    except Exception as exc:
                        logging.error("LlamaParse lỗi ở trang %s của %s: %s", page_num + 1, filename, exc)
                    finally:
                        doc_single.close()
                        for _ in range(3):
                            try:
                                if os.path.exists(temp_pdf_path):
                                    os.remove(temp_pdf_path)
                                break
                            except PermissionError:
                                time.sleep(0.5)
                            except Exception:
                                break
                    continue   # đã xử lý xong trang có bảng

                # ---------- TRƯỜNG HỢP KHÔNG CÓ BẢNG ----------
                # Thử lấy text layer từ PDF (nếu có)
                page_text = doc_reader[page_num].get_text("text")
                if page_text.strip():
                    # Có text layer -> dùng trực tiếp (không OCR)
                    pages_with_text += 1
                    final_markdown.append(standardize_legal_txt_to_md(page_text, check_has_dieu(page_text)))
                else:
                    # Không có text layer -> PDF scan -> OCR
                    pages_ocr += 1
                    cost_stats["ocr_calls"] += 1
                    logging.warning(f"   OCR trang {page_num + 1}/{total_pages} (có thể mất 5-30s/trang)")
                    ocr_text = ocr_page_with_tesseract(file_path, page_num)
                    final_markdown.append(ocr_text)

    except Exception as exc:
        logging.error("Lỗi đọc file PDF %s: %s", file_path, exc)

    logging.info(f"{filename}: {pages_with_text} text + {pages_ocr} OCR + {pages_with_table} LlamaParse")
    if DRY_RUN and file_llamaparse_calls:
        logging.info(
            "[DRY RUN] File %s có %s trang cần gọi LlamaParse.",
            filename, file_llamaparse_calls,
        )

    return "\n\n".join(part for part in final_markdown if part.strip())


def print_cost_report() -> None:
    print("\n" + "=" * 50)
    print("BÁO CÁO ƯỜC TÍNH CHI PHÍ")
    print("=" * 50)
    print(f"- Tổng số trang PDF đã quét: {cost_stats['total_pdf_pages_scanned']} trang")
    print(f"- Số trang PDF được OCR (Tesseract): {cost_stats['ocr_calls']} trang")
    print(f"- Số file DOCX xử lý: {cost_stats['docx_processed']} file")
    print(f"- Số lượt gọi LlamaParse: {cost_stats['llamaparse_calls']} lượt")
    print(f"- Số lượt gọi Gemini LLM: {cost_stats['gemini_calls']} lượt")
    print("-" * 50)
    print("💡 THÔNG TIN GÓI CƯỚC:")
    print("   * LlamaParse: Miễn phí 1000 trang/ngày. Nếu vượt mức, giá ~ $0.003/trang.")
    print("   * Gemini Flash: Gần như miễn phí trong mức sử dụng thấp.")
    print("   * Tesseract OCR: Hoàn toàn miễn phí (local).")

    if cost_stats["llamaparse_calls"] <= 1000:
        print("\nSố trang LlamaParse nằm trong gói miễn phí.")
    else:
        over = cost_stats["llamaparse_calls"] - 1000
        est_cost = over * 0.003
        print(f"\nVượt {over} trang so với gói free. Ước tính chi phí: ~ ${est_cost:.2f}")
    print("=" * 50 + "\n")


def iter_supported_files(input_dir: Path) -> list[Path]:
    return [
        path
        for path in sorted(input_dir.iterdir())
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]


def process_file(file_path: Path, output_dir: Path) -> bool:
    if not file_path.exists():
        logging.error("File không tồn tại: %s", file_path)
        return False

    output_path = output_dir / f"{file_path.stem}.md"
    if not DRY_RUN and output_path.exists():
        logging.info("Bỏ qua %s (đã có output).", file_path.name)
        return True

    start_time = time.time()
    try:
        ext = file_path.suffix.lower()
        if ext == ".docx":
            markdown_text = process_docx(str(file_path))
        elif ext == ".pdf":
            markdown_text = process_pdf_smart_router(str(file_path))
        elif ext == ".txt":
            markdown_text = process_txt_router(str(file_path))
        else:
            logging.warning("Bỏ qua file không hỗ trợ: %s", file_path.name)
            return False

        if not DRY_RUN and markdown_text.strip():
            output_path.write_text(markdown_text, encoding="utf-8")

        elapsed = round(time.time() - start_time, 2)
        logging.info("Đã xử lý xong %s -> %s (%.2fs)", file_path.name, output_path, elapsed)
        return True
    except Exception as exc:
        logging.error("Lỗi ở %s: %s", file_path.name, exc)
        return False


def process_batch(input_dir: str | Path, output_dir: str | Path) -> None:
    # Resolve input directory (allow relative names under PROJECT_ROOT/data)
    input_path = Path(input_dir)
    if not input_path.is_absolute():
        input_path = PROJECT_ROOT / "data" / input_path
    if not input_path.exists():
        logging.error("Thư mục đầu vào không tồn tại: %s", input_path)
        return

    # Resolve output directory (allow relative names under PROJECT_ROOT/data)
    output_path = Path(output_dir)
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / "data" / output_path
    output_path.mkdir(parents=True, exist_ok=True)
    files_to_process = iter_supported_files(input_path)

    if not files_to_process:
        logging.info("Không tìm thấy file hỗ trợ nào trong %s", input_path)
        return

    mode_text = "DRY RUN" if DRY_RUN else "PRODUCTION"
    logging.info("Bắt đầu xử lý %s file. Chế độ: %s", len(files_to_process), mode_text)

    success_count = 0
    for file_path in files_to_process:
        if process_file(file_path, output_path):
            success_count += 1

    logging.info("Hoàn tất: %s/%s file.", success_count, len(files_to_process))
    if any(cost_stats.values()):
        print_cost_report()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Process raw legal documents.")
    parser.add_argument("--input", "-i", type=str, default=str(DEFAULT_INPUT_DIR), help="Input directory")
    parser.add_argument("--output", "-o", type=str, default=str(DEFAULT_OUTPUT_DIR), help="Output directory")
    parser.add_argument("--run", action="store_true", help="Run without DRY_RUN mode (set DRY_RUN=False)")
    parser.add_argument("--dry", action="store_true", help="Run with DRY_RUN mode (set DRY_RUN=True)")
    args = parser.parse_args()

    if args.run:
        DRY_RUN = False
    elif args.dry:
        DRY_RUN = True
    process_batch(args.input, args.output)
