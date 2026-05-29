"""
🧪 TEST WEB SEARCH FALLBACK — Kiểm thử toàn diện luồng web search trong Knowledge Node.

Flow test:
  A. Unit test: web_search() trực tiếp → SERP → scrape → rerank
  B. Integration test: knowledge_node với query KHÔNG có trong local KB
     (mô phỏng score < threshold → trigger web fallback)

Cách chạy:
  python test_web_search_fallback.py
"""

import asyncio
import json
import sys
import time
import logging
from pathlib import Path
from typing import Any, Dict

# UTF-8 support trên Windows
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# ── Setup paths ──────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("test_web_search")


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 0: PRECHECK — MCP servers có đang chạy không?
# ═══════════════════════════════════════════════════════════════════════════════

async def precheck_mcp_servers() -> Dict[str, bool]:
    """Kiểm tra kết nối tới cả 2 MCP servers (port 8100, 8200)."""
    import httpx
    
    results = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in [
            ("retrieval (8100)", "http://localhost:8100/mcp/sse"),
            ("rerank (8200)", "http://localhost:8200/mcp/sse"),
        ]:
            try:
                resp = await client.get(url)
                results[name] = resp.status_code == 200
            except Exception:
                results[name] = False
    
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1: UNIT TEST — web_search() trực tiếp
# ═══════════════════════════════════════════════════════════════════════════════

async def test_web_search_direct():
    """Test gọi trực tiếp ai.tools.web_search.web_search()"""
    print("\n" + "=" * 80)
    print("  PHASE 1: UNIT TEST — web_search() trực tiếp")
    print("=" * 80)
    
    from ai.tools.web_search import web_search
    
    # Query pháp lý — không có trong local KB
    query = "quy định mới về đăng ký xe máy 2025"
    
    print(f"\n📝 Query: {query}")
    print(f"⏱️  Bắt đầu...")
    
    t0 = time.monotonic()
    try:
        results = await web_search(query, top_k=3)
        elapsed = time.monotonic() - t0
        
        print(f"\n✅ Thành công trong {elapsed:.1f}s!")
        print(f"📊 Kết quả: {len(results)} documents")
        
        for i, doc in enumerate(results):
            meta = doc.get("metadata", {})
            print(f"\n  ── Doc #{i+1} [score: {doc.get('score', 0):.4f}] ──")
            print(f"  📄 Source: {meta.get('source', 'N/A')}")
            print(f"  📝 Title:  {meta.get('title', 'N/A')}")
            print(f"  📃 Content: {doc.get('page_content', '')[:200]}...")
        
        return {
            "passed": len(results) > 0,
            "count": len(results),
            "elapsed": elapsed,
            "error": None,
        }
        
    except Exception as e:
        elapsed = time.monotonic() - t0
        print(f"\n❌ Thất bại sau {elapsed:.1f}s: {e}")
        import traceback
        traceback.print_exc()
        return {
            "passed": False,
            "count": 0,
            "elapsed": elapsed,
            "error": str(e),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2: INTEGRATION TEST — knowledge_node với web fallback
# ═══════════════════════════════════════════════════════════════════════════════

async def test_knowledge_node_fallback():
    """
    Test knowledge_node với query KHÔNG có trong local KB.
    Mô phỏng: score < threshold → trigger web_search fallback.
    """
    print("\n" + "=" * 80)
    print("  PHASE 2: INTEGRATION TEST — knowledge_node → web fallback")
    print("=" * 80)
    
    from ai.agents.knowledge import knowledge_node
    
    # Query không có trong local KB → local score sẽ = 0.0 < 0.4 threshold
    # → trigger web_search fallback (khi retry_count = 0)
    state: Dict[str, Any] = {
        "user_query": "thủ tục cấp đổi giấy phép lái xe hạng A1 mới nhất năm 2025",
        "session_id": "test_fallback_001",
        "sub_queries": ["thủ tục cấp đổi giấy phép lái xe hạng A1 mới nhất năm 2025"],
        "current_query_idx": 0,
        "retry_count": 0,
        "detailed_intent": "ADMIN_PROCEDURE",
        "knowledge_loop_count": 0,
        "conversation_history": [],
        "retrieved_docs": [],
        "errors": [],
    }
    
    print(f"\n📝 Query: {state['user_query'][:80]}")
    print(f"🎯 Intent: {state['detailed_intent']}")
    print(f"⏱️  Bắt đầu knowledge_node...")
    
    t0 = time.monotonic()
    try:
        result = await knowledge_node(state)
        elapsed = time.monotonic() - t0
        
        docs = result.get("retrieved_docs", [])
        source = result.get("retrieval_source", "unknown")
        score = result.get("confidence_score", 0)
        
        print(f"\n✅ Hoàn thành trong {elapsed:.1f}s!")
        print(f"📊 Retrieval source: {source}")
        print(f"📊 Confidence score: {score:.4f}")
        print(f"📊 Documents: {len(docs)}")
        
        if source in ("web", "hybrid"):
            print(f"🌐 WEB FALLBACK TRIGGERED → source = '{source}'")
        else:
            print(f"📚 Chỉ dùng local KB → {len(docs)} docs (score: {score:.4f})")
        
        for i, doc in enumerate(docs[:5]):
            meta = doc.get("metadata", {})
            origin = meta.get("origin", "local")
            print(f"\n  ── Doc #{i+1} [{origin}] [score: {doc.get('score', 0):.4f}] ──")
            print(f"  📄 {meta.get('source', meta.get('file_name', 'N/A'))}")
            print(f"  📃 {doc.get('page_content', '')[:150]}...")
        
        return {
            "passed": len(docs) > 0,
            "source": source,
            "count": len(docs),
            "elapsed": elapsed,
            "error": None,
        }
        
    except Exception as e:
        elapsed = time.monotonic() - t0
        print(f"\n❌ Thất bại sau {elapsed:.1f}s: {e}")
        import traceback
        traceback.print_exc()
        return {
            "passed": False,
            "source": "error",
            "count": 0,
            "elapsed": elapsed,
            "error": str(e),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3: FULL GRAPH TEST — short-circuit qua Orchestrator → END
# ═══════════════════════════════════════════════════════════════════════════════

async def test_full_graph_web_fallback():
    """
    Test full graph với query không có trong local KB.
    Orchestrator → knowledge (web fallback) → worker → validator → answer.
    """
    print("\n" + "=" * 80)
    print("  PHASE 3: FULL GRAPH TEST — end-to-end web fallback")
    print("=" * 80)
    
    from ai.infrastructure import config
    config.settings.orchestrator_model = "gemini-2.0-flash"
    
    from ai.agents.graph import build_graph
    from ai.agents.state import AgentState
    
    query = "thủ tục cấp đổi giấy phép lái xe hạng A1 mới nhất năm 2025"
    
    print(f"\n📝 Query: {query}")
    print(f"⏱️  Bắt đầu graph...")
    
    graph = build_graph()
    
    state: Dict[str, Any] = {
        "user_query": query,
        "session_id": "test_full_002",
        "conversation_history": [],
        "retry_count": 0,
        "max_retries": 2,
        "errors": [],
    }
    
    t0 = time.monotonic()
    try:
        # Dùng ainvoke (non-stream) cho test
        result = await graph.ainvoke(state)
        elapsed = time.monotonic() - t0
        
        final_response = result.get("final_response", "")
        source = result.get("retrieval_source", "unknown")
        docs = result.get("retrieved_docs", [])
        errors = result.get("errors", [])
        
        print(f"\n✅ Graph hoàn thành trong {elapsed:.1f}s!")
        print(f"📊 Retrieval source: {source}")
        print(f"📊 Documents: {len(docs)}")
        print(f"📊 Errors: {errors if errors else 'None'}")
        print(f"\n🎯 Final Response:")
        print(final_response[:500])
        
        return {
            "passed": bool(final_response) and "không tìm thấy" not in final_response.lower(),
            "source": source,
            "elapsed": elapsed,
            "error": None if not errors else str(errors),
        }
        
    except Exception as e:
        elapsed = time.monotonic() - t0
        print(f"\n❌ Graph thất bại sau {elapsed:.1f}s: {e}")
        import traceback
        traceback.print_exc()
        return {
            "passed": False,
            "source": "error",
            "elapsed": elapsed,
            "error": str(e),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    print("╔" + "═" * 78 + "╗")
    print("║" + "  🧪 TEST WEB SEARCH FALLBACK — Hệ thống tra cứu web khi local KB thiếu".center(76) + "║")
    print("╚" + "═" * 78 + "╝")
    
    # ── Phase 0: Precheck ───────────────────────────────────────────────────
    print("\n📡 [PHASE 0] Kiểm tra MCP servers...")
    servers = await precheck_mcp_servers()
    
    all_ok = all(servers.values())
    for name, status in servers.items():
        icon = "✅" if status else "❌"
        print(f"  {icon} {name}: {'ONLINE' if status else 'OFFLINE'}")
    
    if not all_ok:
        print("\n" + "!" * 60)
        print("⚠️  MỘT HOẶC NHIỀU MCP SERVER CHƯA CHẠY!")
        print("!")
        print("   Khởi động MCP servers trước khi test:")
        print("     Terminal 1: python -m ai.mcp.retrieval --port 8100")
        print("     Terminal 2: python -m ai.mcp.rerank     --port 8200")
        print("!")
        print("   ⚠️  BrightData token & Cohere API key cần có trong .env")
        print("!" * 60)
        
        # Vẫn chạy test để kiểm tra fallback behavior (sẽ fail gracefully)
        print("\n⚠️  Vẫn chạy test để kiểm tra error handling...\n")
    
    results = {}
    
    # ── Phase 1: Unit test web_search ───────────────────────────────────────
    results["phase1_web_search"] = await test_web_search_direct()
    
    # ── Phase 2: Integration test knowledge_node ────────────────────────────
    results["phase2_knowledge_node"] = await test_knowledge_node_fallback()
    
    # ── Phase 3: Full graph test ────────────────────────────────────────────
    results["phase3_full_graph"] = await test_full_graph_web_fallback()
    
    # ── Summary ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("  📊 TỔNG KẾT KẾT QUẢ")
    print("=" * 80)
    
    for phase, result in results.items():
        status = "✅ PASS" if result["passed"] else "❌ FAIL"
        extra = f" | source={result.get('source', 'N/A')}" if "source" in result else ""
        error = f" | error: {result['error'][:60]}" if result.get("error") else ""
        print(f"  {status}  {phase}: {result['elapsed']:.1f}s | {result.get('count', 'N/A')} docs{extra}{error}")
    
    all_passed = all(r["passed"] for r in results.values())
    print(f"\n{'🎉 TẤT CẢ TEST PASS!' if all_passed else '⚠️  CÓ TEST FAIL — xem chi tiết trên.'}")


if __name__ == "__main__":
    asyncio.run(main())
