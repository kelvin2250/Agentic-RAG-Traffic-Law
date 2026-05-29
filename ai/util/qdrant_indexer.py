import os
import json
from tqdm import tqdm
from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams
from langchain_huggingface import HuggingFaceEmbeddings
from dotenv import load_dotenv

# ==========================================
# CẤU HÌNH HỆ THỐNG
# ==========================================
CHUNKS_JSON_PATH = os.path.join("data-ingestion", "chunks", "hierarchical_chunks.jsonl")
QDRANT_DB_PATH = os.path.join("data-ingestion", "qdrant_db")
COLLECTION_NAME = "traffic_law_final"
PARENT_DICT_PATH = os.path.join(QDRANT_DB_PATH, "parent_dict.json")
BATCH_SIZE = 32

load_dotenv()

def detect_gpu_availability() -> str:
    return "cpu"
    # try:
    #     import torch
    #     if torch.cuda.is_available():
    #         device = "cuda"
    #         print(f"GPU CUDA: {torch.cuda.get_device_name(0)}")
    #         return device
    # except ImportError:
    #     pass
    # print("Dùng CPU (chậm hơn)")
    # return "cpu"

def load_chunks_from_jsonl(json_path: str, already_indexed_ids: set = None):
    """
    Đọc file JSONL, tách:
    - child_docs: list[Document] dành cho embedding (type = child/appendix/unstructured)
    - parent_dict: dict {parent_id: full_text} cho parent chunks
    """
    print(f"📂 Đọc dữ liệu từ: {json_path}")
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Không tìm thấy {json_path}")

    child_docs = []
    parent_dict = {}
    skipped_child = 0
    total_parent = 0

    with open(json_path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            chunk_type = item.get("type", "")

            # Xử lý Parent chunk -> lưu vào parent_dict
            if chunk_type == "parent":
                total_parent += 1
                parent_id = item.get("chunk_id")
                full_text = item.get("full_text", "")
                if parent_id and full_text:
                    parent_dict[parent_id] = full_text
                continue

            # Các loại child, appendix, unstructured -> embedding
            if chunk_type in ("child", "appendix", "unstructured"):
                chunk_id = item.get("chunk_id", "")
                if already_indexed_ids and chunk_id in already_indexed_ids:
                    skipped_child += 1
                    continue

                metadata = item.get("metadata", {})
                doc = Document(
                    page_content=item.get("text", ""),
                    metadata={
                        "source_file": metadata.get("file_name", ""),
                        "file_id": metadata.get("file_id", ""),
                        "chapter": metadata.get("chapter", "UNKNOWN"),
                        "section": metadata.get("section", "UNKNOWN"),
                        "article": metadata.get("article", "UNKNOWN"),
                        "doc_scope": metadata.get("doc_scope", "main"),
                        "type": chunk_type,
                        "parent_id": item.get("parent_id", ""),   # quan trọng để truy xuất parent
                        "chunk_id": chunk_id,
                    }
                )
                child_docs.append(doc)
            else:
                # Không nhận diện được type (bỏ qua)
                continue

    print(f"Đã tải {len(child_docs)} child chunks (bỏ qua {skipped_child} đã index).")
    print(f"Đã tải {len(parent_dict)} parent chunks.")
    return child_docs, parent_dict

def setup_qdrant_and_index():
    print("EMBEDDING & INDEXING CHILD/APPENDIX/UNSTRUCTURED CHUNKS")
    print("-" * 60)

    device = detect_gpu_availability()

    # Kết nối Qdrant
    qdrant_url = os.getenv("QDRANT_URL")
    if qdrant_url:
        print(f"\nKết nối Qdrant Server: {qdrant_url}")
        client = QdrantClient(url=qdrant_url, timeout=30.0)
    else:
        print(f"\nQdrant Local Path: {QDRANT_DB_PATH}")
        os.makedirs(QDRANT_DB_PATH, exist_ok=True)
        client = QdrantClient(path=QDRANT_DB_PATH)

    # Lấy danh sách child chunk đã index (delta-sync)
    already_indexed = set()
    collection_exists = client.collection_exists(COLLECTION_NAME)
    if collection_exists:
        print(f"Collection '{COLLECTION_NAME}' đã tồn tại (chế độ upsert)")
        try:
            # Lấy tối đa 100k point (đủ cho hầu hết)
            points = client.scroll(
                collection_name=COLLECTION_NAME,
                limit=100000,
                with_payload=True
            )[0]
            already_indexed = {
                point.payload.get("metadata", {}).get("chunk_id", "")
                for point in points if point.payload
            }
            print(f"📋 Hiện có {len(already_indexed)} child chunks trong DB")
        except Exception as e:
            print(f"Không lấy được danh sách cũ: {e}")

    # Tải dữ liệu
    child_docs, parent_dict = load_chunks_from_jsonl(CHUNKS_JSON_PATH, already_indexed)

    if not child_docs:
        print("Không có child chunk mới cần index.")
        # Vẫn lưu parent_dict (có thể có parent mới dù child không đổi)
        with open(PARENT_DICT_PATH, 'w', encoding='utf-8') as f:
            json.dump(parent_dict, f, ensure_ascii=False, indent=2)
        print(f"Đã cập nhật parent_dict ({len(parent_dict)} mục).")
        return

    # Embedding model
    embed_model_name = "huuydangg/DEk21_hcmute_embedding"
    
    print(f"\nLoad Embedding Model: {embed_model_name}...")
    embeddings = HuggingFaceEmbeddings(
        model_name="huyydangg/DEk21_hcmute_embedding",
        model_kwargs={'device': 'cpu'},
        encode_kwargs={'batch_size': 8, 'normalize_embeddings': True}
    )

    # Lấy dimension
    sample = embeddings.embed_query("test")
    dim = len(sample)
    print(f"📏 Dimension: {dim}")

    # Tạo collection nếu chưa có
    if not collection_exists:
        print(f"🆕 Tạo collection '{COLLECTION_NAME}' ...")
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE)
        )

    # Tạo vector store
    vector_store = QdrantVectorStore(
        client=client,
        collection_name=COLLECTION_NAME,
        embedding=embeddings,
    )

    # Index batch
    print(f"\nĐang embed và insert {len(child_docs)} chunks (batch {BATCH_SIZE})...")
    for i in tqdm(range(0, len(child_docs), BATCH_SIZE), desc="Indexing"):
        batch = child_docs[i:i+BATCH_SIZE]
        vector_store.add_documents(documents=batch)

    # Lưu parent_dict
    with open(PARENT_DICT_PATH, 'w', encoding='utf-8') as f:
        json.dump(parent_dict, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("🎉 HOÀN TẤT INDEXING")
    print(f"📂 Qdrant DB: {QDRANT_DB_PATH}")
    print(f"📚 Parent dict: {PARENT_DICT_PATH} ({len(parent_dict)} parents)")
    print(f"📄 Số child chunks mới: {len(child_docs)}")
    print("=" * 60)

    # Test retrieval
    print("\n🔍 THỬ TRUY VẤN:")
    query = "Vượt đèn đỏ bị phạt bao nhiêu tiền?"
    print(f'➤ "{query}"')
    results = vector_store.similarity_search_with_score(query, k=2)
    for res, score in results:
        parent_id = res.metadata.get("parent_id", "")
        print(f"\n- Score: {score:.4f}")
        print(f"- File: {res.metadata.get('source_file')}")
        print(f"- Điều: {res.metadata.get('article')}")
        if parent_id in parent_dict:
            print(f"- Parent preview: {parent_dict[parent_id][:150]}...")
        print(f"- Trích dẫn child: {res.page_content[:200]}...")

if __name__ == "__main__":
    setup_qdrant_and_index()