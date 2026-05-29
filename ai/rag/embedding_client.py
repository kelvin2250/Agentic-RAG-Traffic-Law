import asyncio
import logging
from typing import List
from abc import ABC, abstractmethod
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.embeddings import Embeddings

logger = logging.getLogger(__name__)


# ==========================================
# SYNC EMBEDDINGS WRAPPER (for QdrantVectorStore)
# ==========================================
class EmbeddingsSync(Embeddings):
    """
    Sync wrapper for HuggingFaceEmbeddings.
    Dùng cho khởi tạo QdrantVectorStore (yêu cầu sync Embeddings object).
    """

    def __init__(
        self,
        model_name: str = "huyydangg/DEk21_hcmute_embedding",
        device: str = "cpu",
        batch_size: int = 8,
        normalize_embeddings: bool = True,
    ):
        logger.info(f"Loading EmbeddingsSync: {model_name} on {device}")
        
        self.embeddings = HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"device": device},
            encode_kwargs={
                "batch_size": batch_size,
                "normalize_embeddings": normalize_embeddings,
            },
        )
        self.model_name = model_name
        logger.info("EmbeddingsSync initialized")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed list of documents (sync)."""
        logger.debug(f"Embedding {len(texts)} documents")
        return self.embeddings.embed_documents(texts)

    def embed_query(self, text: str) -> List[float]:
        """Embed single query (sync)."""
        logger.debug(f"Embedding query: {text[:50]}...")
        return self.embeddings.embed_query(text)

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        """Async wrapper: embed documents via thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.embed_documents, texts
        )

    async def aembed_query(self, text: str) -> List[float]:
        """Async wrapper: embed query via thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.embed_query, text)


# ==========================================
# ASYNC EMBEDDING CLIENT
# ==========================================
class EmbeddingClient(ABC):
    """
    Abstract base class cho Embedding Client.
    Hỗ trợ cả async embedding qua HTTP/gRPC (future) và fallback local.
    """

    @abstractmethod
    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed list of documents asynchronously."""
        pass

    @abstractmethod
    async def embed_query(self, text: str) -> List[float]:
        """Embed single query asynchronously."""
        pass


class LocalEmbeddingClient(EmbeddingClient):
    """
    Local Embedding Client: fallback sử dụng HuggingFaceEmbeddings chạy trong executor.
    Hiện tại dùng cho test nhanh. Sau có thể thay bằng HTTP/gRPC call tới model-service.
    """

    def __init__(
        self,
        model_name: str = "huyydangg/DEk21_hcmute_embedding",
        device: str = "cpu",
        batch_size: int = 8,
    ):
        """
        Args:
            model_name: HuggingFace model identifier
            device: 'cpu' hoặc 'cuda'
            batch_size: embedding batch size
        """
        logger.info(f"Initializing LocalEmbeddingClient: {model_name}")
        
        self.embeddings = HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"device": device},
            encode_kwargs={"batch_size": batch_size, "normalize_embeddings": True},
        )
        self.model_name = model_name
        logger.info("LocalEmbeddingClient ready")

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Embed documents asynchronously via thread pool.
        Tránh block event loop.
        """
        logger.debug(f"Async embedding {len(texts)} documents")
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.embeddings.embed_documents, texts
        )

    async def embed_query(self, text: str) -> List[float]:
        """
        Embed query asynchronously via thread pool.
        Tránh block event loop.
        """
        logger.debug(f"Async embedding query: {text[:50]}...")
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.embeddings.embed_query, text
        )


class RemoteEmbeddingClient(EmbeddingClient):
    """
    Remote Embedding Client: gọi embedding service qua HTTP/gRPC.
    (STUB - triển khai sau khi có model-service)
    """

    def __init__(self, service_url: str):
        """
        Args:
            service_url: URL của embedding service (e.g., "http://localhost:8001")
        """
        logger.info(f"Initializing RemoteEmbeddingClient: {service_url}")
        self.service_url = service_url
        # TODO: Implement HTTP/gRPC client
        logger.warning("RemoteEmbeddingClient is a STUB — not yet implemented")

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed documents via remote service."""
        # TODO: gọi HTTP POST /embed-documents
        raise NotImplementedError("RemoteEmbeddingClient not yet implemented")

    async def embed_query(self, text: str) -> List[float]:
        """Embed query via remote service."""
        # TODO: gọi HTTP POST /embed-query
        raise NotImplementedError("RemoteEmbeddingClient not yet implemented")


# ==========================================
# FACTORY FUNCTION
# ==========================================
def create_embedding_client(
    client_type: str = "local",
    model_name: str = "huyydangg/DEk21_hcmute_embedding",
    device: str = "cpu",
    service_url: str = None,
) -> EmbeddingClient:
    """
    Factory để tạo embedding client phù hợp.

    Args:
        client_type: "local" hoặc "remote"
        model_name: HuggingFace model name (cho local client)
        device: "cpu" hoặc "cuda" (cho local client)
        service_url: URL của remote service (cho remote client)

    Returns:
        EmbeddingClient instance
    """
    if client_type == "local":
        logger.info("Using LocalEmbeddingClient")
        return LocalEmbeddingClient(model_name=model_name, device=device)
    elif client_type == "remote":
        if not service_url:
            raise ValueError("service_url required for remote client")
        logger.info("Using RemoteEmbeddingClient")
        return RemoteEmbeddingClient(service_url=service_url)
    else:
        raise ValueError(f"Unknown client_type: {client_type}")
