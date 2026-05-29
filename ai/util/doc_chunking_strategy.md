# Chiến lược Chunking cho Văn bản Pháp luật Việt Nam

## 1. Tổng quan

Hệ thống sử dụng chiến lược chunking **phân cấp (hierarchical)** được thiết kế riêng cho các văn bản pháp luật tiếng Việt.  
Mục tiêu: bảo toàn cấu trúc pháp lý logic (Điều → Khoản) đồng thời tạo ra các đoạn văn bản đủ nhỏ để phục vụ tìm kiếm ngữ nghĩa (retrieval) trong pipeline **RAG**.

## 2. Tại sao cần Chunking?

- Văn bản pháp luật thường rất dài, vượt xa giới hạn token của các mô hình ngôn ngữ lớn (LLM).
- Chia nhỏ thành các **chunk** và lập chỉ mục (index) giúp:
  - Tìm kiếm các đoạn liên quan nhanh và chính xác hơn.
  - Chỉ đưa vào prompt những phần thực sự cần thiết, tiết kiệm tài nguyên.

## 3. Thách thức với văn bản pháp luật

- Văn bản có cấu trúc cây **phân cấp chặt chẽ**:  
  `Chương → Mục → Điều → Khoản → Điểm`
- Nếu chia **máy móc theo độ dài cố định**, một điều luật (hoặc một khoản) có thể bị cắt đôi, làm **đứt gãy ý nghĩa**, gây sai lệch khi trả lời.
- Do đó cần một chiến lược chunking **“thông minh”** dựa trên chính các mốc cấu trúc của văn bản.

## 4. Chiến lược phân cấp Parent-Child

Thay vì xem văn bản là một khối phẳng, chunker xây dựng mô hình hai tầng:

- **Parent Chunk** (Cha)  
  - Tương ứng với **một Điều** luật.  
  - Chứa **toàn bộ nội dung** của Điều đó: tiêu đề, tất cả các Khoản và Điểm bên trong.  
  - Dùng làm **ngữ cảnh đầy đủ** khi cần giải thích hay trích dẫn trọn vẹn một điều luật.

- **Child Chunk** (Con)  
  - Tương ứng với **một Khoản** (có thể kèm các Điểm a, b, c… nếu có).  
  - Là đơn vị tìm kiếm chính trong hệ thống RAG.  
  - Mỗi Child giữ một trường `parent_id` để liên kết ngược lên Parent chứa nó.

### Lợi ích của mô hình Parent-Child

- **Truy vấn chính xác**: tìm trên Child – đủ nhỏ để embedding phản ánh đúng ý của một khoản cụ thể.  
- **Ngữ cảnh phong phú**: khi đã chọn được Child phù hợp, dễ dàng lấy `full_text` của Parent để cung cấp toàn bộ Điều luật cho LLM, tránh hiểu sai do thiếu vế.  
- **Bảo toàn tính pháp lý**: không cắt xén ngẫu nhiên, giữ nguyên ranh giới Điều/Khoản.

## 5. Fallback cho văn bản không có cấu trúc “Điều …”

- Nếu một văn bản **không chứa dòng nào bắt đầu bằng “Điều …”** (ví dụ: công văn, chỉ thị ngắn), chunker sẽ tự động chuyển sang phương thức **phi cấu trúc**.
- Sử dụng **RecursiveCharacterTextSplitter**:
  - Tạo **một Parent** duy nhất đại diện cho toàn bộ văn bản (đã cắt bớt nếu quá dài).
  - Chia văn bản thành các Child với kích thước ~800 ký tự, chồng lấn (overlap) 150 ký tự.
- Metadata được gán nhãn `"UNKNOWN"` để đánh dấu đây là văn bản phi cấu trúc.

## 6. Luồng hoạt động của ClauseChunker

- Liệt kê tất cả file `.md` trong thư mục nguồn.
- Với mỗi file:
    - Kiểm tra trong nội dung có cụm **“Điều ” + số** hay không.
    - **Có** → Parse bằng **máy trạng thái** (state machine), sinh các cặp Parent-Child dựa trên cấu trúc Điều/Khoản.
    - **Không** → Parse **phi cấu trúc**, tạo 1 Parent + nhiều Child từ text splitter.
- Ghi tuần tự từng chunk (đối tượng JSON) ra file `.jsonl`, mỗi dòng là một chunk.

## Example Chunk
{"chunk_id": "499422c6-30f9-4989-871d-7d9c4da4168c", "type": "parent", "full_text": "Điều 12. Tổ chức thực hiện\n1. Bộ Công an, Bộ Quốc phòng, Bộ Giao thông vận tải căn cứ chức năng, nhiệm vụ của mình có trách nhiệm tổ chức thực hiện Thông tư này.\n2. Trong quá trình thực hiện, nếu phát sinh vướng mắc hoặc cần được hướng dẫn, đề nghị phản ánh kịp thời về Bộ Công an, Bộ Quốc phòng, Bộ Giao thông vận tải để nghiên cứu, hướng dẫn, sửa đổi, bổ sung kịp thời./.\nBỘ TRƯỞNG\nBỘ GIAO THÔNG VẬN TẢI\nTrương Quang Nghĩa\nBỘ TRƯỞNG\nBỘ QUỐC PHÒNG\nĐại tướng Ngô Xuân Lịch\nBỘ TRƯỞNG\nBỘ C\nÔ\nNG AN\nThượng tướng Tô Lâm", "metadata": {"file_id": "122401.md", "file_name": "Thông tư liên tịch số 02/2016/TTLT-BCA-BQP-BGTVT Hướng dẫn thực hiện đào tạo, bồi dưỡng cán bộ làm công tác phòng, chống khủng bố", "chapter": "Chương III: ĐIỀU KHOẢN THI HÀNH", "section": "UNKNOWN", "article": "Điều 12 - Tổ chức thực hiện", "doc_scope": "main"}}
{"chunk_id": "478166a8-b6da-44af-a309-4a2482b13acb", "parent_id": "d34e5388-f170-4e6c-b526-7323d1b9947c", "type": "child", "text": "[Điều 1: Phạm vi điều chỉnh, đối tượng áp dụng] 1. Thông tư này quy định về đào tạo, bồi dưỡng học viên, sinh viên, cán bộ làm công tác phòng, chống khủng bố.", "metadata": {"file_id": "122401.md", "file_name": "Thông tư liên tịch số 02/2016/TTLT-BCA-BQP-BGTVT Hướng dẫn thực hiện đào tạo, bồi dưỡng cán bộ làm công tác phòng, chống khủng bố", "chapter": "Chương I: QUY ĐỊNH CHUNG", "section": "UNKNOWN", "article": "Điều 1 - Phạm vi điều chỉnh, đối tượng áp dụng", "doc_scope": "main"}}
{"chunk_id": "97f42245-46bb-4cc0-827d-7751596097f8", "parent_id": "d34e5388-f170-4e6c-b526-7323d1b9947c", "type": "child", "text": "[Điều 1: Phạm vi điều chỉnh, đối tượng áp dụng] 2. Thông tư này áp dụng đối với các cơ quan, đơn vị, cá nhân liên quan đến công tác đào tạo, bồi dưỡng học viên, sinh viên, cán bộ làm công tác phòng, chống khủng bố.", "metadata": {"file_id": "122401.md", "file_name": "Thông tư liên tịch số 02/2016/TTLT-BCA-BQP-BGTVT Hướng dẫn thực hiện đào tạo, bồi dưỡng cán bộ làm công tác phòng, chống khủng bố", "chapter": "Chương I: QUY ĐỊNH CHUNG", "section": "UNKNOWN", "article": "Điều 1 - Phạm vi điều chỉnh, đối tượng áp dụng", "doc_scope": "main"}}
