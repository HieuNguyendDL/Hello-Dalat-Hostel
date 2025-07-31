import os
import logging
from telegram.ext import Application
from app.telegram_bot import setup_handlers
from app.firestore import init_firestore
from app.openai_helper import init_openai

# Cấu hình logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def seed_rooms_data():
    """
    Khởi tạo dữ liệu mẫu cho collection 'rooms' trong Firestore.
    """
    rooms_data = [
        {"id": "101", "name": "Room 101", "type": "Family", "status": "available", "capacity": 4},
        {"id": "102", "name": "Room 102", "type": "Single", "status": "available", "capacity": 1},
        {"id": "202", "name": "Room 202", "type": "Single", "status": "available", "capacity": 1},
        {"id": "103", "name": "Room 103", "type": "Deluxe Double", "status": "available", "capacity": 2},
        {"id": "203", "name": "Room 203", "type": "Deluxe Double", "status": "available", "capacity": 2},
        {"id": "301", "name": "Room 301", "type": "Standard Double", "status": "available", "capacity": 2},
        {"id": "302", "name": "Room 302", "type": "Standard Double", "status": "available", "capacity": 2},
        {"id": "201", "name": "Room 201", "type": "Deluxe Queen", "status": "available", "capacity": 2}
    ]
    from app.firestore import init_firestore
    init_firestore()
    from app.firestore import db
    for room in rooms_data:
        db.collection("rooms").document(room["id"]).set({
            "name": room["name"],
            "type": room["type"],
            "status": room["status"],
            "capacity": room["capacity"]
        })
    print("Đã khởi tạo dữ liệu mẫu cho rooms!")

def main():
    try:
        # Khởi tạo các service
        init_firestore()
        init_openai()

        # Lấy token từ biến môi trường
        telegram_token = os.getenv("TELEGRAM_TOKEN")
        if not telegram_token:
            logging.error("TELEGRAM_TOKEN chưa được thiết lập trong biến môi trường!")
            return

        # Tạo Telegram Application
        app = Application.builder().token(telegram_token).build()
        
        # Thiết lập handlers
        setup_handlers(app)

        # Khởi chạy bot
        logging.info("Bot đang khởi động...")
        app.run_polling()
    except Exception as e:
        logging.error(f"Lỗi khởi động bot: {str(e)}")

if __name__ == "__main__":
    main()