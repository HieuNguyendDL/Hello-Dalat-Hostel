import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from datetime import datetime
import json
import os
import logging
from typing import Dict, List, Optional, Union

# Khởi tạo logger
logger = logging.getLogger(__name__)

# Biến global cho Firestore client
db = None

def init_firestore():
    """Khởi tạo kết nối Firestore"""
    global db
    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(json.loads(os.getenv("FIREBASE_CREDS")))
            firebase_admin.initialize_app(cred)
        db = firestore.client()
        logger.info("Firestore initialized successfully")
    except Exception as e:
        logger.error(f"Lỗi khởi tạo Firestore: {str(e)}")
        raise

# ========== ROOM OPERATIONS ==========
def get_room(room_id: str) -> Optional[Dict]:
    """Lấy thông tin phòng theo ID"""
    try:
        doc = db.collection("rooms").document(room_id).get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        logger.error(f"Lỗi khi lấy thông tin phòng {room_id}: {str(e)}")
        return None

def get_available_rooms(check_in: str, check_out: str) -> List[Dict]:
    """Lấy danh sách phòng trống trong khoảng thời gian"""
    try:
        # Validate ngày
        datetime.strptime(check_in, "%Y-%m-%d")
        datetime.strptime(check_out, "%Y-%m-%d")

        available_rooms = []
        rooms_ref = db.collection("rooms").where(filter=FieldFilter("status", "==", "available"))
        
        for room in rooms_ref.stream():
            # Kiểm tra lịch đặt phòng trùng
            conflicting_bookings = db.collection("bookings").where(
                filter=FieldFilter("roomId", "==", room.id)
            ).where(
                filter=FieldFilter("status", "in", ["confirmed", "pending"])
            ).where(
                filter=FieldFilter("checkOut", ">=", check_in)
            ).where(
                filter=FieldFilter("checkIn", "<=", check_out)
            ).limit(1).stream()

            if not list(conflicting_bookings):
                room_data = room.to_dict()
                room_data["id"] = room.id
                available_rooms.append(room_data)

        return available_rooms

    except Exception as e:
        logger.error(f"Lỗi khi lấy phòng trống: {str(e)}")
        raise

def get_all_available_rooms(start_date: str, end_date: str) -> List[Dict]:
    """
    Lấy tất cả các phòng còn trống trong khoảng thời gian bất kỳ.
    Trả về danh sách phòng trống.
    """
    try:
        datetime.strptime(start_date, "%Y-%m-%d")
        datetime.strptime(end_date, "%Y-%m-%d")
        available_rooms = []
        rooms_ref = db.collection("rooms").stream()
        for room in rooms_ref:
            room_id = room.id
            # Kiểm tra có booking trùng không
            bookings_ref = db.collection("bookings").where(
                filter=FieldFilter("roomId", "==", room_id)
            ).where(
                filter=FieldFilter("status", "in", ["confirmed", "pending"])
            ).where(
                filter=FieldFilter("checkOut", ">=", start_date)
            ).where(
                filter=FieldFilter("checkIn", "<=", end_date)
            ).limit(1).stream()
            if not list(bookings_ref):
                room_data = room.to_dict()
                room_data["id"] = room_id
                available_rooms.append(room_data)
        return available_rooms
    except Exception as e:
        logger.error(f"Lỗi khi kiểm tra phòng trống toàn bộ: {str(e)}")
        raise

# ========== BOOKING OPERATIONS ==========
def create_booking(booking_data: Dict) -> str:
    """
    Tạo booking mới
    Args:
        booking_data: {
            "room_id": str,
            "guest_name": str,
            "phone": str,
            "check_in": str (YYYY-MM-DD),
            "check_out": str (YYYY-MM-DD),
            "price": int,
            "deposit": int,
            "notes": str (optional)
        }
    Returns:
        ID của booking vừa tạo
    """
    @firestore.transactional
    def _create_in_transaction(transaction, booking_ref, room_ref):
        # Kiểm tra phòng còn trống
        room = transaction.get(room_ref)
        if room.get("status") != "available":
            raise ValueError(f"Phòng {booking_data['room_id']} đã được đặt!")

        # Tạo booking
        transaction.set(booking_ref, {
            "roomId": booking_data["room_id"],
            "guestName": booking_data["guest_name"],
            "phone": booking_data["phone"],
            "checkIn": booking_data["check_in"],
            "checkOut": booking_data["check_out"],
            "price": booking_data["price"],
            "deposit": booking_data["deposit"],
            "status": "confirmed",
            "createdAt": firestore.SERVER_TIMESTAMP,
            "notes": booking_data.get("notes", "")
        })

        # Cập nhật trạng thái phòng
        transaction.update(room_ref, {"status": "booked"})

    try:
        # Validate dữ liệu
        if not all(k in booking_data for k in ["room_id", "guest_name", "phone", 
                                            "check_in", "check_out", "price", "deposit"]):
            raise ValueError("Thiếu thông tin bắt buộc")

        # Chuyển đổi ngày
        datetime.strptime(booking_data["check_in"], "%Y-%m-%d")
        datetime.strptime(booking_data["check_out"], "%Y-%m-%d")

        booking_ref = db.collection("bookings").document()
        room_ref = db.collection("rooms").document(booking_data["room_id"])

        transaction = db.transaction()
        _create_in_transaction(transaction, booking_ref, room_ref)

        logger.info(f"Tạo booking thành công: {booking_ref.id}")
        return booking_ref.id

    except Exception as e:
        logger.error(f"Lỗi khi tạo booking: {str(e)}")
        raise

def cancel_booking(booking_id: str) -> bool:
    """Hủy booking và cập nhật trạng thái phòng"""
    @firestore.transactional
    def _cancel_in_transaction(transaction, booking_ref, room_ref):
        booking = transaction.get(booking_ref)
        if not booking.exists:
            raise ValueError("Booking không tồn tại")
        
        if booking.get("status") == "cancelled":
            return False  # Đã hủy rồi

        # Cập nhật booking
        transaction.update(booking_ref, {
            "status": "cancelled",
            "cancelledAt": firestore.SERVER_TIMESTAMP
        })

        # Cập nhật phòng về available
        transaction.update(room_ref, {"status": "available"})
        return True

    try:
        booking_ref = db.collection("bookings").document(booking_id)
        booking = booking_ref.get()
        
        if not booking.exists:
            raise ValueError(f"Booking {booking_id} không tồn tại")

        room_ref = db.collection("rooms").document(booking.get("roomId"))

        transaction = db.transaction()
        success = _cancel_in_transaction(transaction, booking_ref, room_ref)

        if success:
            logger.info(f"Đã hủy booking {booking_id}")
        return success

    except Exception as e:
        logger.error(f"Lỗi khi hủy booking: {str(e)}")
        raise

def update_booking(booking_id: str, updates: Dict) -> bool:
    """
    Cập nhật thông tin booking
    Args:
        updates: Dict các field cần cập nhật
                (chỉ cho phép: guestName, phone, checkIn, checkOut, price, deposit, notes)
    """
    allowed_fields = {
        "guestName", "phone", "checkIn", "checkOut", 
        "price", "deposit", "notes"
    }

    try:
        # Validate updates
        if not any(field in allowed_fields for field in updates.keys()):
            raise ValueError("Chỉ được cập nhật các field: " + ", ".join(allowed_fields))

        # Validate ngày nếu có
        if "checkIn" in updates:
            datetime.strptime(updates["checkIn"], "%Y-%m-%d")
        if "checkOut" in updates:
            datetime.strptime(updates["checkOut"], "%Y-%m-%d")

        booking_ref = db.collection("bookings").document(booking_id)
        booking_ref.update(updates)
        
        logger.info(f"Cập nhật booking {booking_id} thành công")
        return True

    except Exception as e:
        logger.error(f"Lỗi khi cập nhật booking: {str(e)}")
        raise

def get_booking(booking_id: str) -> Optional[Dict]:
    """Lấy thông tin booking theo ID"""
    try:
        doc = db.collection("bookings").document(booking_id).get()
        if doc.exists:
            data = doc.to_dict()
            data["id"] = doc.id
            return data
        return None
    except Exception as e:
        logger.error(f"Lỗi khi lấy booking {booking_id}: {str(e)}")
        return None

def get_today_checkins() -> List[Dict]:
    """Lấy danh sách check-in hôm nay"""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        bookings = db.collection("bookings").where(
            filter=FieldFilter("checkIn", "==", today)
        ).where(
            filter=FieldFilter("status", "in", ["confirmed", "pending"])
        ).stream()

        return [{"id": b.id, **b.to_dict()} for b in bookings]
    except Exception as e:
        logger.error(f"Lỗi khi lấy danh sách check-in: {str(e)}")
        return []
def get_room_availability(room_id: str, start_date: str, end_date: str) -> Dict:
    """
    Kiểm tra lịch phòng trống trong khoảng thời gian bất kỳ
    Trả về:
    {
        "room_id": "room_101",
        "available": True/False,
        "bookings": [{
            "check_in": "2024-12-25",
            "check_out": "2024-12-27",
            "status": "confirmed"
        }]
    }
    """
    try:
        # Validate ngày
        datetime.strptime(start_date, "%Y-%m-%d")
        datetime.strptime(end_date, "%Y-%m-%d")

        room_ref = db.collection("rooms").document(room_id)
        room = room_ref.get()
        
        if not room.exists:
            raise ValueError("Phòng không tồn tại")

        # Lấy tất cả booking trong khoảng thời gian
        bookings_ref = db.collection("bookings").where(
            filter=FieldFilter("roomId", "==", room_id)
        ).where(
            filter=FieldFilter("checkOut", ">=", start_date)
        ).where(
            filter=FieldFilter("checkIn", "<=", end_date)
        ).where(
            filter=FieldFilter("status", "in", ["confirmed", "pending"])
        ).stream()

        bookings_data = []
        for booking in bookings_ref:
            booking_data = booking.to_dict()
            bookings_data.append({
                "check_in": booking_data["checkIn"],
                "check_out": booking_data["checkOut"],
                "status": booking_data["status"]
            })

        return {
            "room_id": room_id,
            "available": len(bookings_data) == 0,
            "bookings": bookings_data
        }

    except Exception as e:
        logger.error(f"Lỗi khi kiểm tra lịch phòng: {str(e)}")
        raise