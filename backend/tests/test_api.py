import time
import requests
import json

BASE_URL = "http://localhost:8000/api/v1"
TEST_EMAIL = f"test_{int(time.time())}@example.com"
TEST_PASSWORD = "securepassword123"

def run_tests():
    print("🚀 BẮT ĐẦU KIỂM THỬ BACKEND API...")
    print("-" * 50)
    
    # 1. Test Đăng ký
    print("\n1️⃣ Đang đăng ký tài khoản mới...")
    signup_url = f"{BASE_URL}/auth/signup"
    signup_payload = {
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    }
    r = requests.post(signup_url, json=signup_payload)
    print(f"Status: {r.status_code}")
    if r.status_code != 201:
        print(f"❌ Đăng ký thất bại: {r.text}")
        return
    print("✅ Đăng ký thành công!")
    user_data = r.json()
    print(f"User ID: {user_data.get('id')}")

    # 2. Test Đăng nhập
    print("\n2️⃣ Đang đăng nhập...")
    login_url = f"{BASE_URL}/auth/login"
    login_payload = {
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    }
    r = requests.post(login_url, json=login_payload)
    print(f"Status: {r.status_code}")
    if r.status_code != 200:
        print(f"❌ Đăng nhập thất bại: {r.text}")
        return
    tokens = r.json()
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]
    print("✅ Đăng nhập thành công!")
    print(f"Access Token: {access_token[:30]}...")
    print(f"Refresh Token: {refresh_token[:30]}...")

    # 3. Test Refresh Token
    print("\n3️⃣ Đang kiểm tra Refresh Token...")
    refresh_url = f"{BASE_URL}/auth/refresh"
    r = requests.post(refresh_url, json={"refresh_token": refresh_token})
    print(f"Status: {r.status_code}")
    if r.status_code != 200:
        print(f"❌ Refresh token thất bại: {r.text}")
        return
    new_tokens = r.json()
    new_access_token = new_tokens["access_token"]
    print("✅ Refresh token thành công!")
    print(f"New Access Token: {new_access_token[:30]}...")

    # Headers mang token cho các request tiếp theo
    headers = {
        "Authorization": f"Bearer {new_access_token}",
        "Content-Type": "application/json"
    }

    # 4. Test gửi tin nhắn (Non-stream)
    print("\n4️⃣ Đang gửi tin nhắn (REST mode)...")
    chat_url = f"{BASE_URL}/chat/chat"
    chat_payload = {
        "query": "Xe máy chở 3 người phạt bao nhiêu?",
        "stream": False
    }
    r = requests.post(chat_url, json=chat_payload, headers=headers)
    print(f"Status: {r.status_code}")
    if r.status_code != 200:
        print(f"❌ Chat REST thất bại: {r.text}")
        return
    chat_resp = r.json()
    session_id = chat_resp["session_id"]
    print("✅ Nhận phản hồi thành công!")
    print(f"Session ID: {session_id}")
    print(f"Response: {chat_resp.get('content')[:150]}...")

    # 5. Test gửi tin nhắn (Stream SSE mode)
    print("\n5️⃣ Đang gửi tin nhắn (SSE Stream mode)...")
    chat_payload_stream = {
        "query": "Vượt đèn đỏ phạt bao nhiêu?",
        "session_id": session_id,
        "stream": True
    }
    r = requests.post(chat_url, json=chat_payload_stream, headers=headers, stream=True)
    print(f"Status: {r.status_code}")
    if r.status_code != 200:
        print(f"❌ Chat Stream thất bại: {r.text}")
        return
    
    print("✅ Bắt đầu nhận dòng dữ liệu (SSE Chunks):")
    done_payload = None
    for line in r.iter_lines():
        if line:
            decoded_line = line.decode('utf-8')
            if decoded_line.startswith("data: "):
                data_str = decoded_line[6:].strip()
                if "final_response" in data_str:
                    try:
                        done_payload = json.loads(data_str)
                    except:
                        pass
            print(f"  > {decoded_line[:100]}")
    
    print("✅ Kết thúc stream.")
    if done_payload:
        print(f"✨ Phản hồi Stream tích lũy: {done_payload.get('final_response')[:150]}...")

    # 6. Lấy danh sách sessions
    print("\n6️⃣ Đang lấy danh sách các phiên chat...")
    sessions_url = f"{BASE_URL}/chat/sessions"
    r = requests.get(sessions_url, headers=headers)
    print(f"Status: {r.status_code}")
    if r.status_code != 200:
        print(f"❌ Lấy danh sách sessions thất bại: {r.text}")
        return
    sessions = r.json()
    print("✅ Lấy thành công!")
    print(f"Số lượng phiên chat hiện tại: {len(sessions)}")

    # 7. Lấy chi tiết session
    print(f"\n7️⃣ Đang xem chi tiết lịch sử phiên chat: {session_id}...")
    details_url = f"{sessions_url}/{session_id}"
    r = requests.get(details_url, headers=headers)
    print(f"Status: {r.status_code}")
    if r.status_code != 200:
        print(f"❌ Xem chi tiết thất bại: {r.text}")
        return
    details = r.json()
    print("✅ Xem thành công!")
    print(f"Tiêu đề phiên: {details['session']['title']}")
    print(f"Số lượng tin nhắn trong lịch sử: {len(details['messages'])}")

    # 8. Xóa session
    print(f"\n8️⃣ Đang xóa phiên chat: {session_id}...")
    r = requests.delete(details_url, headers=headers)
    print(f"Status: {r.status_code}")
    if r.status_code != 200:
        print(f"❌ Xóa phiên chat thất bại: {r.text}")
        return
    print("✅ Xóa phiên chat thành công!")
    
    print("\n🎉 HOÀN THÀNH TOÀN BỘ CÁC BÀI TEST THÀNH CÔNG!")

if __name__ == "__main__":
    run_tests()
