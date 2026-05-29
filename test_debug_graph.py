"""
🔍 DETAILED GRAPH DEBUG SCRIPT
Truy vết chi tiết từng node: đầu vào, đầu ra, dữ liệu biến đổi.

Cách dùng:
    python test_debug_graph.py
"""

from ai.infrastructure import config
# Sử dụng trực tiếp settings thực và ghi đè các tham số cần thiết
config.settings.orchestrator_model = "gemini-2.0-flash"  # Tên model bạn muốn test
config.settings.max_retries = 3

import asyncio
import json
import sys
from datetime import datetime
from typing import Any, Dict
from pprint import pprint

# UTF-8 support trên Windows
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

from dotenv import load_dotenv
load_dotenv()

from ai.agents.graph import build_graph
from ai.agents.state import AgentState

# ═══════════════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def truncate(text: str, max_len: int = 100) -> str:
    """Cắt ngắn text để dễ đọc."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def pretty_value(val: Any, max_len: int = 200) -> str:
    """Format giá trị để dễ đọc."""
    if val is None:
        return "None"
    if isinstance(val, bool):
        return "✅ True" if val else "❌ False"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        return f'"{truncate(val, max_len)}"'
    if isinstance(val, list):
        if not val:
            return "[]"
        if len(val) > 3:
            return f"[{len(val)} items]"
        return f"[{', '.join(pretty_value(v, 50) for v in val)}]"
    if isinstance(val, dict):
        if not val:
            return "{}"
        items = ", ".join(f"{k}: {pretty_value(v, 30)}" for k, v in list(val.items())[:3])
        extra = f", +{len(val) - 3} more" if len(val) > 3 else ""
        return f"{{{items}{extra}}}"
    return str(val)[:max_len]


class StateChangeTracker:
    """Theo dõi thay đổi state giữa các lần gọi."""
    
    def __init__(self):
        self.prev_state: Dict[str, Any] = {}
        self.node_sequence: list = []
    
    def record_change(self, node_name: str, state: Dict[str, Any]) -> Dict[str, str]:
        """
        Ghi lại thay đổi state sau node.
        Trả về dict các field thay đổi.
        """
        changes = {}
        
        for key, new_val in state.items():
            old_val = self.prev_state.get(key)
            
            # So sánh: nếu khác nhau thì ghi lại
            if old_val != new_val:
                # Special handling cho list/dict (so sánh length thay vì nội dung)
                if isinstance(old_val, (list, dict)) and isinstance(new_val, (list, dict)):
                    if len(old_val) != len(new_val):
                        changes[key] = f"{pretty_value(old_val)} → {pretty_value(new_val)}"
                else:
                    changes[key] = f"{pretty_value(old_val)} → {pretty_value(new_val)}"
        
        self.prev_state = dict(state)
        self.node_sequence.append(node_name)
        return changes


def print_header(text: str, char: str = "═"):
    """In tiêu đề với đường kẻ."""
    print(f"\n{char * 80}")
    print(f"  {text}")
    print(f"{char * 80}")


def print_node_trace(node_name: str, state_before: Dict, state_after: Dict, changes: Dict):
    """In chi tiết trước/sau khi node chạy."""
    print(f"\n📍 NODE: {node_name}")
    print(f"   ⏱️  Time: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
    
    # Input
    print(f"\n   📥 INPUT STATE (key fields):")
    input_fields = {
        "user_query": state_before.get("user_query"),
        "primary_intent": state_before.get("primary_intent"),
        "detailed_intent": state_before.get("detailed_intent"),
        "detailed_intents": state_before.get("detailed_intents"),
        "parallel_mode": state_before.get("parallel_mode"),
        "current_intent_idx": state_before.get("current_intent_idx"),
        "sub_queries": state_before.get("sub_queries"),
        "current_query_idx": state_before.get("current_query_idx"),
        "retrieved_docs_count": len(state_before.get("retrieved_docs", [])),
        "retry_count": state_before.get("retry_count"),
    }
    for key, val in input_fields.items():
        print(f"      • {key}: {pretty_value(val)}")
    
    # Output changes
    if changes:
        print(f"\n   📤 OUTPUT (thay đổi):")
        for key, change in sorted(changes.items()):
            print(f"      • {key}: {change}")
    else:
        print(f"\n   📤 OUTPUT: (không có thay đổi)")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN DEBUG FUNCTION
# ═══════════════════════════════════════════════════════════════════════════

async def debug_graph():
    """Chạy graph với debug tracing."""
    
    print_header("🚀 AGENTIC RAG TRAFFIC LAW - GRAPH DEBUG", "═")
    
    # Build graph
    print("\n⏳ Đang xây dựng graph...")
    graph = build_graph()
    print("✅ Graph xây dựng xong.")
    
    # Tạo state input
    state = {
        "user_query": "Thủ tục đăng kí xe máy mới mua là gì?",
        "session_id": "debug_009",
        "conversation_history": [],
    }
    
    print_header("INPUT QUERY", "─")
    print(f"User Query: {state['user_query']}")
    print(f"Session ID: {state['session_id']}")
    
    # Chạy graph step-by-step
    print_header("EXECUTING GRAPH NODES", "─")
    
    tracker = StateChangeTracker()
    step_count = 0
    
    # SỬA ĐỔI CHÍNH TẠI ĐÂY: Sử dụng async for duyệt qua astream generator
    async for output in graph.astream(state, stream_mode="updates"):
        step_count += 1
        
        for node_name, node_output in output.items():
            # Kiểm tra nếu node_output bị None thì log cảnh báo và bỏ qua thay vì crash
            if node_output is None:
                print(f"\n⚠️ WARNING: Node '{node_name}' returned None instead of a dict!")
                continue
                
            # Merge node_output vào state để track changes
            state_before = dict(state)
            state.update(node_output)
            
            changes = tracker.record_change(node_name, state)
            print_node_trace(node_name, state_before, state, changes)
    
    # ─────────────────────────────────────────────────────────────────────────
    # FINAL RESULT
    # ─────────────────────────────────────────────────────────────────────────
    print_header("📊 FINAL RESULT", "═")

    print(f"\n✅ Flow hoàn thành trong {step_count} node(s)")
    if tracker.node_sequence:
        print(f"📍 Chuỗi Node: {' → '.join(tracker.node_sequence)} → END")

    print(f"\n🎯 Final Response:")
    final_response = state.get("final_response", "")
    print(final_response)


    # Các field quan trọng (không bao gồm retrieved docs)
    summary_fields = [
        ("user_query", "Câu hỏi gốc"),
        ("primary_intent", "Intent chính"),
        ("detailed_intent", "Intent chi tiết (cũ)"),
        ("detailed_intents", "Danh sách Intents chi tiết (mới)"),
        ("parallel_mode", "Chế độ Parallel"),
        ("current_intent_idx", "Index Intent tuần tự"),
        ("primary_intent_confidence", "Độ tin cậy intent"),
        ("legal_analysis", "Phân tích pháp luật"),
        ("sanction_details", "Chi tiết phạt"),
        ("admin_procedure_details", "Thủ tục hành chính"),
        ("validation_report", "Báo cáo kiểm định"),
        ("retry_count", "Lượt retry"),
        ("final_response", "Câu trả lời cuối"),
    ]

    for field_name, field_label in summary_fields:
        if field_name in state:
            val = state[field_name]

            # Hiển thị toàn bộ, không cắt ngắn
            if isinstance(val, dict):
                display = json.dumps(val, ensure_ascii=False, indent=2)
            else:
                display = str(val)

            print(f"  • {field_label} ({field_name}):")
            for line in display.split('\n'):
                print(f"    {line}")

    # ── In chi tiết retrieved documents ──────────────────────────────────────
    retrieved_docs = state.get("retrieved_docs", [])
    print(f"\n📄 RETRIEVED DOCUMENTS (Total: {len(retrieved_docs)})")
    if retrieved_docs:
        # Hiển thị tối đa 5 documents, in toàn bộ nội dung
        for idx, doc in enumerate(retrieved_docs[:5]):
            print(f"  --- Doc #{idx+1} ---")
            if isinstance(doc, str):
                print(doc)
            elif isinstance(doc, dict):
                # In full JSON với indent, không giới hạn độ dài
                print(json.dumps(doc, ensure_ascii=False, indent=2))
            else:
                print(str(doc))
            print()  # dòng trống ngăn cách
        if len(retrieved_docs) > 5:
            print(f"  ... và {len(retrieved_docs) - 5} documents khác")
    else:
        print("  (Không có retrieved documents)")


# ═══════════════════════════════════════════════════════════════════════════
# ENTRYPOINT
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        asyncio.run(debug_graph())
    except Exception as e:
        print(f"\n❌ ERROR OCCURRED: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)