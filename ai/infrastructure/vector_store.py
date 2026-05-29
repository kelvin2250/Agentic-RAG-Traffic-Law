from qdrant_client import QdrantClient
from langchain_qdrant import QdrantVectorStore
from langchain_huggingface import HuggingFaceEmbeddings
from .config import settings

# Biến private giữ trạng thái Singleton
_qdrant_client = None
_vector_store = None

def get_qdrant_client() -> QdrantClient:
    """Singleton wrapper cho QdrantClient"""
    global _qdrant_client
    if _qdrant_client is None:
        # Hỗ trợ cả kết nối local qua URL hoặc qua Path nếu cần thiết
        if settings.qdrant_url and settings.qdrant_url.startswith("http"):
            _qdrant_client = QdrantClient(url=settings.qdrant_url, timeout=30.0)
        else:
            path_to_use = settings.qdrant_url or settings.qdrant_path
            _qdrant_client = QdrantClient(path=str(path_to_use), read_only=True)
    return _qdrant_client

def get_vector_store() -> QdrantVectorStore:
    """Singleton wrapper cho QdrantVectorStore kết hợp Embedding Model"""
    global _vector_store
    if _vector_store is None:
        client = get_qdrant_client()
        
        # Đồng bộ Model Embedding đã cấu hình ở Phase trước của bạn
        embedding_model = "huyydangg/DEk21_hcmute_embedding"
        embeddings = HuggingFaceEmbeddings(
            model_name=embedding_model,
            model_kwargs={'device': 'cpu'},
            encode_kwargs={'normalize_embeddings': True}
        )
        
        _vector_store = QdrantVectorStore(
            client=client,
            collection_name=settings.qdrant_collection,
            embedding=embeddings
        )
    return _vector_store