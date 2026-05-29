import asyncio
from dotenv import load_dotenv
from ai.mcp.brightdata import BrightDataClient

load_dotenv()

async def main():
    client = BrightDataClient(pro=True)

    query_str = "chạy xe máy chở 3 được phép khi nào"
    target_domains = ["thuvienphapluat.vn", "bocongan.gov.vn"]

    print(f"Tim kiem tu khoa: '{query_str}'...")
    search_results = await client.search_web(query=query_str, domains=target_domains)

    if not search_results:
        print("Khong tim thay ket qua nao.")
        return

    print(f"\nDa tim thay {len(search_results)} ket qua:")
    for idx, item in enumerate(search_results, 1):
        print(f"  [{idx}] {item['title']}\n      Link: {item['link']}")

    first_link = search_results[0]['link']
    print(f"\nTien hanh cao Markdown cho link dau tien: {first_link}")

    markdown_content = await client.scrape_url(target_url=first_link)


    # Ghi nội dung markdown vào file
    output_file = "test_md.md"
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        print(f"\nĐã lưu toàn bộ nội dung Markdown vào file: {output_file}")
    except Exception as e:
        print(f"\nLỗi khi ghi file: {e}")

    print(f"\n[KET QUA CAO] (Trich doan 300 ky tu dau):")
    print("-" * 60)
    print(markdown_content[:300] + "\n...[Xem tiep]...")
    print("-" * 60)

if __name__ == "__main__":
    asyncio.run(main())