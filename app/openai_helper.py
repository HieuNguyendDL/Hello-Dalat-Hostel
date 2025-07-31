import openai
import json
import os
import logging
from typing import Dict
from datetime import datetime

def init_openai():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logging.error("OPENAI_API_KEY chưa được thiết lập trong biến môi trường!")
        return
    openai.api_key = api_key

async def parse_booking_text(text: str) -> Dict:
    """
    Phân tích tin nhắn đặt phòng bằng ChatGPT, trả về dict thông tin booking.
    """
    try:
        prompt = f"""
        Phân tích tin nhắn đặt phòng sau thành JSON:
        {{
            \"guest_name\": \"Tên khách (viết hoa chữ cái đầu)\",
            \"phone\": \"Số điện thoại\",
            \"room_id\": \"Mã phòng\",
            \"check_in\": \"YYYY-MM-DD\",
            \"check_out\": \"YYYY-MM-DD\",
            \"price\": \"Giá phòng (số nguyên)\",
            \"deposit\": \"Tiền cọc (số nguyên)\"
        }}

        Ví dụ:
        \"Đặt phòng room_101 cho Nguyễn Văn A từ 25/12 đến 27/12 giá 1.500.000, cọc 500k\"
        → {{
            \"guest_name\": \"Nguyễn Văn A\",
            \"phone\": \"0912345678\",
            \"room_id\": \"room_101\",
            \"check_in\": \"2024-12-25\",
            \"check_out\": \"2024-12-27\",
            \"price\": 1500000,
            \"deposit\": 500000
        }}

        Tin nhắn: \"{text}\"
        """
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        content = response.choices[0].message.content
        try:
            return json.loads(content)
        except Exception:
            logging.error(f"OpenAI trả về không phải JSON: {content}")
            raise ValueError("Phân tích tin nhắn thất bại, định dạng không hợp lệ.")
    except Exception as e:
        logging.error(f"Lỗi phân tích tin nhắn: {str(e)}")
        raise

def parse_availability_request(text: str) -> Dict:
    """
    Phân tích tin nhắn hỏi phòng trống trong khoảng thời gian bất kỳ.
    Trả về dict với các trường: start_date, end_date nếu phát hiện yêu cầu.
    """
    import re
    # Regex tìm ngày dạng dd/mm/yyyy hoặc yyyy-mm-dd
    date_pattern = r"(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})"
    matches = re.findall(date_pattern, text)
    if len(matches) >= 2:
        # Chuyển đổi về yyyy-mm-dd
        def normalize(date_str):
            if "/" in date_str:
                return datetime.strptime(date_str, "%d/%m/%Y").strftime("%Y-%m-%d")
            return date_str
        start_date = normalize(matches[0])
        end_date = normalize(matches[1])
        return {"start_date": start_date, "end_date": end_date}
    return {}

def parse_cancel_request(text: str) -> Dict:
    """
    Nhận diện và phân tích yêu cầu hủy booking.
    Trả về dict với booking_id nếu phát hiện.
    """
    import re
    match = re.search(r"(?:hủy|cancel)\s*(?:booking)?\s*([A-Za-z0-9_-]+)", text, re.IGNORECASE)
    if match:
        return {"booking_id": match.group(1)}
    return {}

def parse_update_request(text: str) -> Dict:
    """
    Nhận diện và phân tích yêu cầu cập nhật booking.
    Trả về dict với booking_id, field, value nếu phát hiện.
    """
    import re
    match = re.search(r"(?:update|cập nhật)\s*([A-Za-z0-9_-]+)\s*([a-zA-Z_]+):([\w\-\.:]+)", text, re.IGNORECASE)
    if match:
        return {
            "booking_id": match.group(1),
            "field": match.group(2),
            "value": match.group(3)
        }
    return {}

def parse_today_checkins_request(text: str) -> bool:
    """
    Nhận diện yêu cầu xem check-in hôm nay.
    Trả về True nếu phát hiện.
    """
    return any(kw in text.lower() for kw in ["check-in hôm nay", "checkin hôm nay", "today checkin", "danh sách check-in hôm nay"])

def parse_room_schedule_request(text: str) -> Dict:
    """
    Nhận diện và phân tích yêu cầu xem lịch phòng.
    Trả về dict với room_id, start_date, end_date nếu phát hiện.
    """
    import re
    room_match = re.search(r"(?:lịch|schedule)\s*(room[_\-A-Za-z0-9]+)", text, re.IGNORECASE)
    date_pattern = r"(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})"
    dates = re.findall(date_pattern, text)
    if room_match and len(dates) >= 2:
        def normalize(date_str):
            if "/" in date_str:
                return datetime.strptime(date_str, "%d/%m/%Y").strftime("%Y-%m-%d")
            return date_str
        return {
            "room_id": room_match.group(1),
            "start_date": normalize(dates[0]),
            "end_date": normalize(dates[1])
        }
    return {}