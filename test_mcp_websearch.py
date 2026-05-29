import asyncio
import json
import logging

# Import 2 client SSE sạch từ module của bạn
from ai.mcp.client import get_retrieval_client, get_rerank_client

# Cấu hình log để nhìn rõ luồng đi của request HTTP Stream
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

async def main():
    # 1. Khởi tạo 2 client kết nối thẳng tới 2 cổng độc lập qua SSE
    retrieval_mcp = get_retrieval_client()
    rerank_mcp = get_rerank_client()
    
    query = "chạy xe máy chở 3 người phạt bao nhiêu năm 2026"
    
    print(f"\n💬 [AGENT FALLBACK] Kích hoạt luồng tra cứu cho query: '{query}'")
    print("=" * 80)
    
    try:
        # BƯỚC 3.1: Gọi tìm kiếm sang Server 8100 (Bright Data Bridge)
        print("\n🔍 [BƯỚC 1] Đang quét Google Search qua Bright Data Server (Port 8100)...")
        search_res = await retrieval_mcp.call_tool("trusted_web_search", {"query": query})
        search_data = json.loads(search_res.content[0].text)
        
        if not search_data:
            print("❌ Không tìm thấy kết quả tìm kiếm tin cậy nào.")
            return
            
        target_url = search_data[0]["link"]
        print(f"👉 Link uy tín nhất tìm được: {target_url}")
        
        # BƯỚC 3.2: Gọi cào nội dung Markdown sang Server 8100
        print("\n📥 [BƯỚC 2] Đang tiến hành cào cấu trúc nội dung văn bản pháp luật...")
        scrape_res = await retrieval_mcp.call_tool("scrape_legal_page", {"url": target_url})
        markdown_text = scrape_res.content[0].text
        print(f"👉 Cào thành công. Độ dài văn bản luật thô: {len(markdown_text)} ký tự.")
        
        # BƯỚC 3.3: Gọi cắt nhỏ văn bản văn bản sang Server 8100
        print("\n✂️ [BƯỚC 3] Đang phân rã văn bản và nhúng vector bằng mô hình local...")
        chunk_res = await retrieval_mcp.call_tool("retrieval_chunking", {"text": markdown_text})
        chunk_data = json.loads(chunk_res.content[0].text)
        
        # Trích xuất danh sách text chunks
        raw_documents = [c["content"] for c in chunk_data]
        print(f"👉 Đã chia nhỏ bài viết thành {len(raw_documents)} phân đoạn văn bản luật.")
        
        # BƯỚC 3.4: Gửi dữ liệu thô sang Server 8200 để lọc qua Cohere Cloud Rerank
        print("\n🧬 [BƯỚC 4] Gửi các chunks sang Server Rerank (Port 8200) để chấm điểm đối sánh...")
        rerank_res = await rerank_mcp.call_tool(
            "reranking_documents", 
            {"query": query, "documents": raw_documents, "top_n": 2}
        )
        final_ranked_results = json.loads(rerank_res.content[0].text)
        
        # ----------------------------------------------------------------------
        # IN KẾT QUẢ ĐẦU RA TINH KHIẾT CUỐI CÙNG
        # ----------------------------------------------------------------------
        print("\n🎯 [XỬ LÝ THÀNH CÔNG] DỮ LIỆU ĐÃ ĐƯỢC LỌC SẠCH SẴN SÀNG CHO VÀO LLM PROMPT:")
        print("=" * 80)
        for idx, item in enumerate(final_ranked_results, 1):
            print(f"Top {idx} [Điểm tương đồng Cohere: {item['score']:.4f}]:")
            print(f"Nội dung: {item['document'].strip()}")
            print("-" * 60)
            
    except Exception as e:
        print(f"❌ Quá trình kiểm thử hệ thống thất bại do lỗi: {e}")

if __name__ == "__main__":
    asyncio.run(main())