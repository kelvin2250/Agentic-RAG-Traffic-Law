import asyncio
import json
import logging
from pathlib import Path
from typing import List, Optional
from collections import defaultdict

from langchain_core.documents import Document
from langchain_community.retrievers import BM25Retriever
from langchain_cohere import CohereRerank
from qdrant_client import QdrantClient
from langchain_qdrant import QdrantVectorStore
import tiktoken

from ai.infrastructure.config import Settings
from ai.rag.embedding_client import EmbeddingsSync

logger = logging.getLogger(__name__)


# ==========================================
# CONFIGURATION
# ==========================================
def get_project_root() -> Path:
    """Get project root from current file location."""
    return Path(__file__).parent.parent.parent


PROJECT_ROOT = get_project_root()
CHUNKS_PATH = PROJECT_ROOT / "data-ingestion" / "chunks" / "hierarchical_chunks.jsonl"


# ==========================================
# UTILITY FUNCTIONS
# ==========================================
def report_tokens(text: str, model_name: str = "gpt-3.5-turbo") -> int:
    """
    Count and log the number of tokens in the given text for a specific model.
    """
    try:
        encoding = tiktoken.encoding_for_model(model_name)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    num_tokens = len(encoding.encode(text))
    logger.info(f"[Token Report] {num_tokens} tokens (model: {model_name})")
    return num_tokens


def load_child_chunks_from_jsonl(chunks_path: Path) -> List[Document]:
    """
    Load CHILD chunks từ hierarchical_chunks.jsonl.
    
    Args:
        chunks_path: đường dẫn đến file chunks
        
    Returns:
        list[Document]: Child chunks với metadata đầy đủ
    """
    logger.info(f"📂 Loading child chunks from: {chunks_path}")
    
    if not chunks_path.exists():
        raise FileNotFoundError(f"Chunks file not found: {chunks_path}")

    child_docs = []
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            
            chunk = json.loads(line)
            
            # Only load CHILD chunks (for BM25)
            if chunk.get("type") != "child":
                continue
            
            full_text = chunk.get("text", "").strip()
            if not full_text or len(full_text) < 5:
                continue
            
            # Create LangChain Document
            doc = Document(
                page_content=full_text,
                metadata={
                    "chunk_id": chunk.get("chunk_id"),
                    "parent_id": chunk.get("parent_id"),
                    "type": chunk.get("type"),
                    **chunk.get("metadata", {}),
                },
            )
            child_docs.append(doc)

    if not child_docs:
        raise ValueError(
            f"No CHILD chunks found in {chunks_path}. "
            "Check that chunks are properly indexed."
        )
    
    logger.info(f"Loaded {len(child_docs)} CHILD chunks")
    return child_docs


def deduplicate_documents(docs: List[Document], key: str = "chunk_id") -> List[Document]:
    """
    Deduplicate documents by metadata key, keeping order.
    
    Args:
        docs: list of documents
        key: metadata field to deduplicate by
        
    Returns:
        deduplicated list
    """
    seen = set()
    deduped = []
    for doc in docs:
        doc_id = doc.metadata.get(key, "")
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            deduped.append(doc)
    logger.debug(f"Deduplicated {len(docs)} → {len(deduped)} documents")
    return deduped

class HybridRetriever:
    """
    Hybrid Retriever: BM25 (CHILD chunks) + Vector (Qdrant) → Ensemble → Cohere Rerank
"""    
    def __init__(self, settings: Settings, chunks_path: Path = None):
        """
        Initialize HybridRetriever.
        """
        logger.info("🔧 Initializing HybridRetriever")
        
        self.settings = settings
        self.chunks_path = chunks_path or CHUNKS_PATH
        
        # Load child chunks once
        logger.info("[1/4] Loading CHILD chunks...")
        self.child_docs = load_child_chunks_from_jsonl(self.chunks_path)
        self._child_docs_by_id = {
            doc.metadata["chunk_id"]: doc for doc in self.child_docs
        }
        
        # Initialize embeddings (sync for QdrantVectorStore)
        logger.info("[2/4] Initializing sync embeddings for Qdrant...")
        self.embeddings = EmbeddingsSync()
        
        # Initialize Qdrant client
        logger.info("[3/4] Connecting to Qdrant...")
        if settings.qdrant_url:
            logger.info(f"Connecting to Qdrant server at: {settings.qdrant_url}")
            self.qdrant_client = QdrantClient(
                url=settings.qdrant_url, timeout=30.0
            )
        else:
            qdrant_path = Path(settings.qdrant_path)
            logger.info(f"Connecting to local Qdrant db at path: {qdrant_path}")
            self.qdrant_client = QdrantClient(
                path=str(qdrant_path), read_only=True, timeout=30.0
            )
        
        # Initialize vector store
        self.vector_store = QdrantVectorStore(
            client=self.qdrant_client,
            collection_name=settings.qdrant_collection,
            embedding=self.embeddings,
            # validate_collection_config=False,  
        )
        logger.info("Vector store initialized")
        
        # Verify Cohere API key
        logger.info("[4/4] Verifying Cohere API key...")
        if not settings.cohere_api_key:
            raise ValueError("COHERE_API_KEY not found in settings")
        logger.info("Cohere API key verified")
        
        # Initialize BM25 retriever (lazy load)
        self._bm25_retriever = None
        
        logger.info("HybridRetriever initialized successfully")

    def _get_bm25_retriever(self) -> BM25Retriever:
        """
        Lazy initialize BM25 retriever from child chunks.
        """
        if self._bm25_retriever is None:
            logger.info("Initializing BM25Retriever (lazy)...")
            self._bm25_retriever = BM25Retriever.from_documents(
                self.child_docs, k=50
            )
            logger.info("BM25Retriever ready")
        return self._bm25_retriever

    async def _search_bm25_async(self, query: str, top_k: int = 50) -> List[Document]:
        """
        BM25 search via asyncio.to_thread (tránh block event loop).
        
        Args:
            query: search query
            top_k: số kết quả trả về
            
        Returns:
            list of relevant documents
        """
        logger.debug(f"📚 BM25 searching: '{query}' (top_{top_k})")
        retriever = self._get_bm25_retriever()
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None, retriever.invoke, query
        )
        logger.debug(f"BM25 returned {len(results)} results")
        return results

    async def _search_vector_async(
        self, query: str, top_k: int = 50
    ) -> List[Document]:
        """
        Vector search via Qdrant (async).
        
        Args:
            query: search query
            top_k: số kết quả trả về
            
        Returns:
            list of relevant documents
        """
        logger.debug(f"Vector searching: '{query}' (top_{top_k})")
        retriever = self.vector_store.as_retriever(search_kwargs={"k": top_k})
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None, retriever.invoke, query
        )
        logger.debug(f"Vector search returned {len(results)} results")
        return results

    async def search(
        self, query: str, top_k: int = 5, pool_size_multiplier: float = 2.0
    ) -> List[Document]:
        logger.info(f"\nHybrid Search: '{query}' (top_k={top_k})")
        logger.info("-" * 70)
        
        # 1. Parallel BM25 + Vector search
        logger.info("[1/3] Parallel search (BM25 + Vector)...")
        pool_k = int(top_k * pool_size_multiplier)
        
        bm25_results, vector_results = await asyncio.gather(
            self._search_bm25_async(query, top_k=pool_k),
            self._search_vector_async(query, top_k=pool_k),
            return_exceptions=True,
        )
        
        if isinstance(bm25_results, Exception):
            logger.warning(f"BM25 search failed: {bm25_results}")
            bm25_results = []
        if isinstance(vector_results, Exception):
            logger.warning(f"Vector search failed: {vector_results}")
            vector_results = []
        
        logger.info(f"   BM25: {len(bm25_results)} results")
        logger.info(f"   Vector: {len(vector_results)} results")
        
        # 2. Merge & Deduplicate
        logger.info("[2/3] Merging & deduplicating...")
        merged = bm25_results + vector_results
        merged = deduplicate_documents(merged, key="chunk_id")
        logger.info(f"   Merged pool: {len(merged)} unique documents")
        
        if not merged:
            logger.warning("No results found")
            return []
        
        # 3. Cohere Rerank
        logger.info(f"[3/3] Cohere Rerank (top_{top_k})...")
        reranker = CohereRerank(
            model="rerank-multilingual-v3.0",
            top_n=top_k,
            cohere_api_key=self.settings.cohere_api_key,
        )
        
        # Tiến hành rerank pool đã merge
        reranked_raw = reranker.compress_documents(merged, query)
        
        # 4. Khôi phục Metadata chuẩn từ Document gốc trước khi Rerank
        final_results = []
        for raw_doc in reranked_raw:
            # Lấy score do Cohere chấm
            score = raw_doc.metadata.get("relevance_score", "N/A")
            
            # Tìm chunk_id từ doc sau khi rerank (thường cohere vẫn giữ lại chunk_id trong metadata)
            chunk_id = raw_doc.metadata.get("chunk_id")
            
            # Fallback: Nếu langchain-cohere ném phăng chunk_id ra ngoài, ta tìm trong `merged` pool bằng text
            original_doc = None
            if chunk_id:
                original_doc = self._child_docs_by_id.get(chunk_id)
            
            if not original_doc:
                # Tìm kiếm fallback bằng text matching nếu mất sạch id
                original_doc = next((d for d in merged if d.page_content == raw_doc.page_content), None)
            
            if original_doc:
                # Tạo bản sao Document với đầy đủ metadata gốc + gắn thêm score của Reranker vào
                enriched_metadata = original_doc.metadata.copy()
                enriched_metadata["score"] = score
                
                new_doc = Document(
                    page_content=original_doc.page_content,
                    metadata=enriched_metadata
                )
                final_results.append(new_doc)
            else:
                # Nếu chịu chết không map ngược được (hy hữu), giữ nguyên doc của cohere và gắn score
                raw_doc.metadata["score"] = score
                final_results.append(raw_doc)
                
        logger.info(f"   Reranked & Restored: {len(final_results)} documents")
        logger.info("-" * 70)
        
        return final_results

    def print_results(self, results: List[Document], verbose: bool = True):
        """
        Print search results in readable format.
        
        Args:
            results: list of documents
            verbose: include full text or summary only
        """
        if not results:
            logger.info("\nNo results found")
            return
        
        logger.info(f"\nTop {len(results)} Results:")
        logger.info("")
        
        for i, doc in enumerate(results, 1):
            article = doc.metadata.get("article", "Unknown")
            file_name = doc.metadata.get("file_name", "")
            chunk_id = doc.metadata.get("chunk_id", "")
            doc_type = doc.metadata.get("type", "")
            score = doc.metadata.get("score", "N/A")
            
            logger.info(f"[{i}] {article}")
            logger.info(f"     File: {file_name}")
            logger.info(f"     Chunk ID: {chunk_id}")
            logger.info(f"     Type: {doc_type}")
            logger.info(f"     Score: {score}")
            
            if verbose:
                logger.info(f"     Text: {doc.page_content[:200]}...")
            
            logger.info("     " + "-" * 60)
            logger.info("")
        # print(doc.metadata)
        # Report total tokens
        full_context = "\n\n".join([doc.page_content for doc in results])
        report_tokens(full_context)

async def interactive_search():
    """Interactive search loop for testing."""
    logger.info("\n" + "=" * 70)
    logger.info("Hybrid Retriever - Interactive Mode (Async)")
    logger.info("   Commands: 'exit' to quit")
    logger.info("=" * 70)
    
    from ai.infrastructure.config import settings
    
    retriever = HybridRetriever(settings=settings)
    
    while True:
        try:
            query = input("\n💬 Enter query: ").strip()
            if query.lower() in ("exit", "quit", "thoát"):
                logger.info("Goodbye!")
                break
            if not query:
                continue
            
            results = await retriever.search(query, top_k=5)
            retriever.print_results(results)
        
        except KeyboardInterrupt:
            logger.info("\nInterrupted")
            break
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)


if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    # Run interactive search
    asyncio.run(interactive_search())
