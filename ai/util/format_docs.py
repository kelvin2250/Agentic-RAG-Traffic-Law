# ai/util/format_docs.py
"""
Utility: Format LangChain Document list sang context string cho LLM prompt.
"""
from typing import List
from langchain_core.documents import Document


def format_docs_as_context(docs: List[Document]) -> str:
    """
    Format danh sách Document thành context string có cấu trúc.
    Mỗi đoạn được đánh số và phân tách rõ ràng.

    Args:
        docs: Danh sách LangChain Document từ HybridRetriever.

    Returns:
        str — context sẵn sàng đưa vào LLM prompt.
    """
    if not docs:
        return ""

    parts = []
    for i, doc in enumerate(docs, 1):
        meta = doc.metadata or {}
        article = meta.get("article", "")
        file_name = meta.get("file_name", "")
        score = meta.get("score") or meta.get("relevance_score", "N/A")

        header_parts = [f"[Đoạn {i}]"]
        if article:
            header_parts.append(f"Điều: {article}")
        if file_name:
            header_parts.append(f"Văn bản: {file_name}")
        if score != "N/A":
            header_parts.append(f"Score: {float(score):.4f}")

        parts.append(" | ".join(header_parts))
        parts.append(doc.page_content.strip())
        parts.append("")  # blank line separator

    return "\n".join(parts).strip()