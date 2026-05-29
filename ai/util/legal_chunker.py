import re
import json
import uuid
import os
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict, field
from enum import Enum
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class ChunkMetadata:
    file_id: str
    file_name: str
    chapter: str
    section: str
    article: str
    doc_scope: str  # "main" or "appendix"


@dataclass
class ParentChunk:
    chunk_id: str
    type: str           # always "parent"
    full_text: str      # Tiêu đề Điều + toàn bộ nội dung Khoản/Điểm bên trong
    metadata: ChunkMetadata


@dataclass
class ChildChunk:
    chunk_id: str
    parent_id: str      # ID của ParentChunk (Điều) chứa Khoản này
    type: str           # always "child"
    text: str           # Nội dung của Khoản (gồm cả Điểm a, b, c… bên trong)
    metadata: ChunkMetadata

class WaitingFor(Enum):
    NONE    = "none"
    CHAPTER = "chapter"
    SECTION = "section"
    ARTICLE = "article"

class ClauseChunker:
    """
    Hierarchical State-Machine Chunker for Vietnamese Legal Documents.

    Strategy
    --------
    * If the document contains "Điều …" markers → hierarchical chunking:
        - Parent  = Điều  (id: dieu_{num})
        - Child   = Khoản (id: dieu_{num}_khoan_{num})
      Retrieval is done at the child level; parent full_text is fetched for context.
    * Otherwise → recursive character splitting (unstructured fallback).
    """

    # ── Regex patterns ──────────────────────────────────────────────────────
    # CHƯƠNG: "CHƯƠNG I", "CHƯƠNG II KẾT CẤU…"  (number on same line OR next)
    RE_CHAPTER = re.compile(
        r'^CHƯƠNG\s+([IXVLCDM]+)[\s.]*(.*)$',
        re.IGNORECASE
    )
    # MỤC: "Mục 1", "Mục 1 PHÂN LOẠI…"
    RE_SECTION = re.compile(
        r'^Mục\s+(\d+)[\s.]*(.*)$',
        re.IGNORECASE
    )
    # ĐIỀU: "Điều 9. Quy tắc chung"   (must have "." after number)
    RE_ARTICLE = re.compile(
        r'^Điều\s+(\d+[a-zđA-ZĐ]?)[\.\:]\s*(.*)$',
        re.IGNORECASE
    )
    # KHOẢN: line starting with "1. ", "2. " … (digit + period + space)
    RE_CLAUSE = re.compile(r'^(\d+)\.\s+(.+)$')

    # PHỤ LỤC detector (for doc_scope)
    RE_PHULUC = re.compile(
        r'^(Phụ lục|PHỤ LỤC)(?:\s+([IVXLCDM]+))?\s*$',
        re.MULTILINE
    )

    def __init__(
        self,
        input_dir: str,
        output_file: str,
        title_json_path: Optional[str] = None,
        chunk_size: int = 800,
        max_parent_text_len: int = 4000,
    ): 
        self.input_dir = Path(input_dir)
        self.output_file = Path(output_file)
        self.max_parent_text_len = max_parent_text_len
        self.title_json_path = title_json_path

        # ── Load doc titles ────────────────────────────────────────────────
        self.doc_titles: Dict[str, str] = {}
        if self.title_json_path and os.path.exists(self.title_json_path):
            with open(self.title_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if 'documents' in data:
                    for item in data['documents']:
                        if 'id' in item and 'title' in item:
                            self.doc_titles[str(item['id'])] = item['title']

        # ── Fallback text splitter (unstructured docs) ─────────────────────
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=150,
            separators=["\n\n", "\n- ", "\n+ ", "\n", ". ", "; ", ", ", " "]
        )

        # ── Telemetry ──────────────────────────────────────────────────────
        self.stats = {"total_files": 0, "chunks": 0, "errors": 0}
        self.quality_stats = {
            "total": 0,
            "article_unknown": 0,
            "clause_unknown": 0,
            "doc_type": {}
        }
        self.article_splitter = RecursiveCharacterTextSplitter(
            chunk_size    = chunk_size,
            chunk_overlap = 150,
            separators    = ["\n\n", "\n", ". ", "; ", ", ", " "]
        )

    def run(self) -> None:
        print(f"ClauseChunker — Hierarchical State Machine (Điều/Khoản)")
        print(f"Nguồn: {self.input_dir} | Đích: {self.output_file}")
        print("-" * 60)

        md_files = list(self.input_dir.glob("*.md"))
        self.stats["total_files"] = len(md_files)

        self.output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(self.output_file, 'w', encoding='utf-8') as out_f:
            for i, filepath in enumerate(md_files):
                if (i + 1) % 50 == 0:
                    print(f"Processing {i + 1}/{len(md_files)}…")

                try:
                    records = self._process_file(filepath)
                    for record in records:
                        out_f.write(json.dumps(asdict(record), ensure_ascii=False) + '\n')
                        self.stats["chunks"] += 1
                except Exception as e:
                    print(f"Error {filepath.name}: {e}")
                    self.stats["errors"] += 1

        print(
            f"\n🎉 HOÀN TẤT! "
            f"Files: {self.stats['total_files']} | "
            f"Chunks: {self.stats['chunks']} | "
            f"Lỗi: {self.stats['errors']}"
        )
        self._save_quality_report()

    # ── File-level processing ──────────────────────────────────────────────

    def _process_file(self, filepath: Path) -> List:
        file_id   = filepath.name
        content   = filepath.read_text(encoding='utf-8')
        name_file = self._extract_doc_name(content, file_id)

        if re.search(r'^Điều\s+\d', content, re.MULTILINE):
            return self._parse_hierarchical(file_id, content, name_file)
        return self._parse_unstructured(file_id, content, name_file)

    # ── Core: Hierarchical state-machine parser ────────────────────────────

    def _parse_hierarchical(
        self, file_id: str, content: str, name_file: str
    ) -> List:
        """
        Line-by-line state machine that emits (ParentChunk, ChildChunk*) pairs.

        State variables
        ---------------
        current_chapter   : label of the current Chương
        current_section   : label of the current Mục
        current_article_id: e.g. "dieu_9"
        current_article_no: e.g. "9"
        article_title     : e.g. "Quy tắc chung"
        waiting_for       : WaitingFor enum — handles multi-line headers
        current_parent    : the ParentChunk being accumulated
        current_child     : the ChildChunk being accumulated
        """
        lines = content.split('\n')

        current_chapter    = ""
        current_section    = ""
        current_article_id = ""
        article_title      = ""
        waiting_for        = WaitingFor.NONE

        current_parent: Optional[dict] = None   # mutable dict while building
        current_child:  Optional[dict] = None

        parent_chunks: List[dict] = []
        child_chunks:  List[dict] = []

        # Track appendix boundary (position-based, line index)
        in_appendix = False

        for line_idx, raw_line in enumerate(lines):
            line = raw_line.strip()

            # ── 0. Handle deferred title (waiting for next line) ──────────
            if waiting_for != WaitingFor.NONE and line:
                if waiting_for == WaitingFor.CHAPTER:
                    current_chapter = f"Chương {current_chapter}: {line}"
                elif waiting_for == WaitingFor.SECTION:
                    current_section = f"Mục {current_section}: {line}"
                elif waiting_for == WaitingFor.ARTICLE:
                    article_title = line
                    if current_parent is not None:
                        current_parent["metadata"]["title"] = article_title
                        current_parent["full_text"] += " " + article_title
                waiting_for = WaitingFor.NONE
                continue

            if not line:
                # Blank lines are kept in child text for readability
                if current_child is not None:
                    current_child["text"] += "\n"
                if current_parent is not None:
                    current_parent["full_text"] += "\n"
                continue

            # ── 1. Phụ lục marker → tách riêng, parse appendix ───────────
            if self.RE_PHULUC.match(line):
                in_appendix = True

                self._finalise_article(current_parent, current_child,
                                    parent_chunks, child_chunks)
                current_parent     = None
                current_child      = None
                current_article_id = ""

                appendix_text    = '\n'.join(lines[line_idx:])

                appendix_records = self._parse_appendix(file_id, appendix_text, name_file)

                return self._build_records(parent_chunks, child_chunks) + appendix_records

            # ── 2. Nhận diện CHƯƠNG ───────────────────────────────────────
            m = self.RE_CHAPTER.match(line)
            if m:
                current_section = ""        # reset Mục when Chương changes
                roman = m.group(1)
                title_part = m.group(2).strip()
                if title_part:
                    current_chapter = f"Chương {roman}: {title_part}"
                else:
                    current_chapter = roman  # title on next line
                    waiting_for = WaitingFor.CHAPTER
                continue

            # ── 3. Nhận diện MỤC ──────────────────────────────────────────
            m = self.RE_SECTION.match(line)
            if m:
                num = m.group(1)
                title_part = m.group(2).strip()
                if title_part:
                    current_section = f"Mục {num}: {title_part}"
                else:
                    current_section = num
                    waiting_for = WaitingFor.SECTION
                continue

            # ── 4. Nhận diện ĐIỀU (= new Parent) ─────────────────────────
            m = self.RE_ARTICLE.match(line)
            if m:
                # Finalise any previous article
                self._finalise_article(current_parent, current_child,
                                       parent_chunks, child_chunks)

                art_num   = m.group(1)
                art_title = m.group(2).strip()
                current_article_id = f"dieu_{art_num}"

                doc_scope = "appendix" if in_appendix else "main"
                meta = {
                    "file_id":   file_id,
                    "file_name": name_file,
                    "chapter":   current_chapter or "UNKNOWN",
                    "section":   current_section or "UNKNOWN",
                    "article":   f"Điều {art_num}" + (f" - {art_title}" if art_title else ""),
                    "doc_scope": doc_scope,
                    "title":     art_title,  # kept for internal use
                }

                current_parent = {
                    "chunk_id":  str(uuid.uuid4()),
                    "type":      "parent",
                    "full_text": line,          # starts with "Điều X. …"
                    "metadata":  meta,
                }
                current_child = None

                if not art_title:
                    waiting_for = WaitingFor.ARTICLE
                continue

            # ── 5. Nhận diện KHOẢN (= new Child) ─────────────────────────
            m = self.RE_CLAUSE.match(line)
            if m and current_article_id:
                khoan_num = m.group(1)
                child_id  = f"{current_article_id}_khoan_{khoan_num}"

                parent_meta = current_parent["metadata"] if current_parent else {}
                child_meta = {
                    "file_id":   file_id,
                    "file_name": name_file,
                    "chapter":   parent_meta.get("chapter", "UNKNOWN"),
                    "section":   parent_meta.get("section", "UNKNOWN"),
                    "article":   parent_meta.get("article", "UNKNOWN"),
                    "doc_scope": parent_meta.get("doc_scope", "main"),
                }

                current_child = {
                    "chunk_id":  str(uuid.uuid4()),
                    "parent_id": current_parent["chunk_id"] if current_parent else "",
                    "type":      "child",
                    "text":      line,
                    "metadata":  child_meta,
                    "_clause_label": f"Khoản {khoan_num}",
                }
                child_chunks.append(current_child)

                if current_parent is not None:
                    current_parent["full_text"] += "\n" + line
                continue

            # ── 6. Continuation text (Điểm a/b/c or wrapped clause text) ──
            if current_article_id:
                if current_child is not None:
                    current_child["text"] += "\n" + line
                if current_parent is not None:
                    current_parent["full_text"] += "\n" + line
        if self.RE_PHULUC.match(line):
            print(">>> PHAT HIEN PHU LUC <<<")
            self._finalise_article(...)
            appendix_text = '\n'.join(lines[line_idx:])
            print(f">>> Chieu dai appendix_text: {len(appendix_text)}")
            appendix_records = self._parse_appendix(file_id, appendix_text, name_file)
            print(f">>> So records appendix: {len(appendix_records)}")
            return self._build_records(parent_chunks, child_chunks) + appendix_records

        # Finalise last article
        self._finalise_article(current_parent, current_child,
                               parent_chunks, child_chunks)

        # ── Convert to dataclass records ───────────────────────────────────
        return self._build_records(parent_chunks, child_chunks)

    # ── Helper: close out current article accumulation ────────────────────

    def _finalise_article(
        self,
        current_parent: Optional[dict],
        current_child:  Optional[dict],
        parent_chunks:  List[dict],
        child_chunks:   List[dict],
    ) -> None:
        if current_parent is None:
            return

        parent_chunks.append(current_parent)

        # Đếm child thuộc parent này
        parent_id      = current_parent["chunk_id"]
        existing_child = [c for c in child_chunks if c["parent_id"] == parent_id]

        if existing_child:
            return  # có Khoản rồi → không cần làm gì thêm

        # Không có Khoản → tự chia full_text thành child chunks
        full_text = current_parent["full_text"].strip()
        sub_chunks = self.article_splitter.split_text(full_text)

        # Nếu văn bản ngắn, split_text trả về 1 chunk = chính nó
        # → vẫn tạo 1 ChildChunk để retrieval pipeline hoạt động đồng nhất
        for i, sub in enumerate(sub_chunks):
            if not sub.strip():
                continue

            meta = current_parent["metadata"]
            child_chunks.append({
                "chunk_id":  str(uuid.uuid4()),
                "parent_id": parent_id,
                "type":      "child",
                "text":      sub.strip(),
                "metadata": {
                    "file_id":   meta["file_id"],
                    "file_name": meta["file_name"],
                    "chapter":   meta.get("chapter", "UNKNOWN"),
                    "section":   meta.get("section", "UNKNOWN"),
                    "article":   meta.get("article", "UNKNOWN"),
                    "doc_scope": meta.get("doc_scope", "main"),
                },
                "_clause_label": f"sub_{i+1}",  # internal tracking
            })

    # ── Convert raw dicts → dataclass objects with quality tracking ────────

    def _build_records(
            self, parent_chunks: List[dict], child_chunks: List[dict]
        ) -> List:
            records = []

            for p in parent_chunks:
                meta = p["metadata"]
                self.quality_stats["total"] += 1
                self.quality_stats["doc_type"]["parent"] = (
                    self.quality_stats["doc_type"].get("parent", 0) + 1
                )

                full_text = p["full_text"].strip()
                # Truncate very long parent texts (rare, very long Điều)
                full_text = self._truncate(full_text)

                records.append(
                    ParentChunk(
                        chunk_id  = p["chunk_id"],
                        type      = "parent",
                        full_text = full_text,
                        metadata  = ChunkMetadata(
                            file_id   = meta["file_id"],
                            file_name = meta["file_name"],
                            chapter   = meta.get("chapter", "UNKNOWN"),
                            section   = meta.get("section", "UNKNOWN"),
                            article   = meta.get("article", "UNKNOWN"),
                            doc_scope = meta.get("doc_scope", "main"),
                        )
                    )
                )

            for c in child_chunks:
                meta = c["metadata"]
                self.quality_stats["total"] += 1
                self.quality_stats["doc_type"]["child"] = (
                    self.quality_stats["doc_type"].get("child", 0) + 1
                )

                text = c["text"].strip()
                if not text:
                    continue

                # --- CONTEXTUALIZED CHUNKING ---
                # Lấy tên Điều từ metadata và bơm vào đầu text
                article_name = meta.get("article", "UNKNOWN")
                
                if article_name and article_name != "UNKNOWN":
                    # Tùy chọn: Thay dấu " - " thành ": " để giống ví dụ của bạn 
                    # (vì lúc lưu meta["article"] bạn dùng "Điều {art_num} - {art_title}")
                    formatted_article = article_name.replace(" - ", ": ")
                    
                    # Bơm ngữ cảnh vào text
                    text = f"[{formatted_article}] {text}"
                # -------------------------------

                records.append(
                    ChildChunk(
                        chunk_id  = c["chunk_id"],
                        parent_id = c["parent_id"],
                        type      = "child",
                        text      = text,
                        metadata  = ChunkMetadata(
                            file_id   = meta["file_id"],
                            file_name = meta["file_name"],
                            chapter   = meta.get("chapter", "UNKNOWN"),
                            section   = meta.get("section", "UNKNOWN"),
                            article   = meta.get("article", "UNKNOWN"),
                            doc_scope = meta.get("doc_scope", "main"),
                        )
                    )
                )

            return records

    # ── Unstructured fallback ──────────────────────────────────────────────

    def _parse_unstructured(
        self, file_id: str, content: str, name_file: str
    ) -> List:
        records = []

        # Tạo ParentChunk thật đại diện cho toàn bộ file
        parent_id   = str(uuid.uuid4())
        parent_text = self._truncate(content.strip())

        parent_meta = ChunkMetadata(
            file_id   = file_id,
            file_name = name_file,
            chapter   = "UNKNOWN",
            section   = "UNKNOWN",
            article   = "UNKNOWN",
            doc_scope = "main",
        )
        records.append(
            ParentChunk(
                chunk_id  = parent_id,
                type      = "parent",
                full_text = parent_text,
                metadata  = parent_meta,
            )
        )

        # Các child chunk trỏ về parent thật ở trên
        for chunk in self.text_splitter.split_text(content):
            if not chunk.strip():
                continue

            self.quality_stats["total"] += 1
            self.quality_stats["article_unknown"] += 1
            self.quality_stats["clause_unknown"]  += 1
            self.quality_stats["doc_type"]["unstructured"] = (
                self.quality_stats["doc_type"].get("unstructured", 0) + 1
            )

            records.append(
                ChildChunk(
                    chunk_id  = str(uuid.uuid4()),
                    parent_id = parent_id,          # ← trỏ về ParentChunk thật
                    type      = "unstructured",
                    text      = chunk.strip(),
                    metadata  = parent_meta,
                )
            )

        return records
    def _parse_appendix(
        self, file_id: str, content: str, name_file: str
    ) -> List:
        """
        Phụ lục bảng biểu → 1 ParentChunk đại diện + N ChildChunk
        từ RecursiveCharacterTextSplitter.
        Không parse Khoản vì số 1/2/3 là số thứ tự bảng, không phải Khoản pháp lý.
        """
        parent_id   = str(uuid.uuid4())
        parent_text = self._truncate(content.strip())

        appendix_meta = ChunkMetadata(
            file_id   = file_id,
            file_name = name_file,
            chapter   = "PHỤ LỤC",
            section   = "UNKNOWN",
            article   = "UNKNOWN",
            doc_scope = "appendix",
        )

        records = [
            ParentChunk(
                chunk_id  = parent_id,
                type      = "parent",
                full_text = parent_text,
                metadata  = appendix_meta,
            )
        ]

        for chunk in self.text_splitter.split_text(content):
            if not chunk.strip():
                continue
            self.quality_stats["total"] += 1
            self.quality_stats["doc_type"]["appendix"] = (
                self.quality_stats["doc_type"].get("appendix", 0) + 1
            )
            records.append(
                ChildChunk(
                    chunk_id  = str(uuid.uuid4()),
                    parent_id = parent_id,
                    type      = "appendix",
                    text      = chunk.strip(),
                    metadata  = appendix_meta,
                )
            )

        return records
    # ── Utilities ──────────────────────────────────────────────────────────

    def _extract_doc_name(self, content: str, file_id: str) -> str:
        doc_id = file_id.replace('.md', '')
        if doc_id in self.doc_titles:
            return self.doc_titles[doc_id]

        first_lines = content.split('\n')[:10]
        for line in first_lines:
            clean = re.sub(r'^#+\s+', '', line).strip()
            if re.match(
                r'^(QUYẾT ĐỊNH|THÔNG TƯ|LUẬT|NGHỊ ĐỊNH|CHỈ THỊ|PHÁP LỆNH|HIẾN PHÁP)',
                clean, re.IGNORECASE
            ):
                if not re.search(r'(này|có hiệu lực|thi hành)', clean, re.IGNORECASE):
                    return clean
        return file_id

    def _truncate(self, text: str) -> str:
        if len(text) <= self.max_parent_text_len:
            return text
        return text[:self.max_parent_text_len] + "...\n[Cắt bớt do quá dài]"

    def _save_quality_report(self) -> None:
        report_path = self.output_file.parent / "quality_report.json"

        total = self.quality_stats["total"]
        unknown_article_ratio = (
            (self.quality_stats["article_unknown"] / total) * 100
            if total > 0 else 0
        )
        unknown_clause_ratio = (
            (self.quality_stats["clause_unknown"] / total) * 100
            if total > 0 else 0
        )

        quality_report = {
            "total_chunks":                  total,
            "article_level_UNKNOWN_ratio":   f"{unknown_article_ratio:.2f}%",
            "clause_level_UNKNOWN_ratio":    f"{unknown_clause_ratio:.2f}%",
            "doc_types":                     self.quality_stats["doc_type"],
        }

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(quality_report, f, ensure_ascii=False, indent=2)

        print("\nBÁO CÁO CHẤT LƯỢNG:")
        print(json.dumps(quality_report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.dirname(os.path.dirname(BASE_DIR))
    INPUT_FOLDER = os.path.join(PROJECT_ROOT, "data", "processed")
    OUTPUT_JSONL = os.path.join(PROJECT_ROOT, "data-ingestion", "chunks", "hierarchical_chunks.jsonl")
    TITLE_JSON   = os.path.join(PROJECT_ROOT, "data", "metadata" ,"traffic_law_filtered_by_title.json")

    chunker = ClauseChunker(
        input_dir=INPUT_FOLDER,
        output_file=OUTPUT_JSONL,
        title_json_path=TITLE_JSON
    )
    chunker.run()
