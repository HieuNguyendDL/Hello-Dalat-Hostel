from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)
from datetime import datetime
import logging
from typing import Dict, Optional, List
from app.firestore import check_availability, get_available_rooms, create_booking, cancel_booking, update_booking, get_room_availability
from app.openai_helper import parse_booking_text

# Khởi tạo logger
logger = logging.getLogger(__name__)

# Trạng thái conversation
GET_BOOKING_DATES, GET_GUEST_INFO = range(2)

# ========== CORE FUNCTIONS ==========
def setup_handlers(app: Application) -> None:
    """Thiết lập tất cả handlers cho bot"""
    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("check", check_availability))
    app.add_handler(CommandHandler("cancel", cancel_booking_command))
    app.add_handler(CommandHandler("update", update_booking_command))
    app.add_handler(CommandHandler("today", today_checkins))
    app.add_handler(CommandHandler("schedule", check_room_schedule))
    
    # Booking conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("book", start_booking),
            CallbackQueryHandler(start_booking, pattern="^book$")
        ],
        states={
            GET_BOOKING_DATES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_booking_dates)
            ],
            GET_GUEST_INFO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_guest_info)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_booking_conv)]
    )
    app.add_handler(conv_handler)
    
    # Callback handlers
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Message handler (xử lý tin nhắn tự nhiên)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_natural_message))

# ========== COMMAND HANDLERS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý lệnh /start - Hiển thị menu chính"""
    keyboard = [
        [InlineKeyboardButton("🛎️ Đặt phòng", callback_data="book")],
        [InlineKeyboardButton("📅 Kiểm tra phòng", callback_data="check")],
        [InlineKeyboardButton("❌ Hủy đặt phòng", callback_data="cancel")],
        [InlineKeyboardButton("📋 Check-in hôm nay", callback_data="today")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🏨 **Hello Dalat Hostel Booking System**\n"
        "Vui lòng chọn chức năng:",
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý lệnh /help - Hiển thị hướng dẫn"""
    help_text = """
    📝 **Hướng dẫn sử dụng**:
    
    • /start - Hiển thị menu chính
    • /book - Đặt phòng mới
    • /check <ngày đến> <ngày đi> - Kiểm tra phòng trống
    • /cancel <mã booking> - Hủy đặt phòng
    • /update <mã booking> <field>:<giá trị> - Cập nhật thông tin
    • /today - Xem danh sách check-in hôm nay
    
    💡 Bạn cũng có thể chat trực tiếp:
    "Đặt phòng Deluxe cho Nguyễn Văn A từ 25/12 đến 27/12"
    """
    await update.message.reply_text(help_text)

# ========== BOOKING CONVERSATION ==========
async def start_booking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Bắt đầu quy trình đặt phòng"""
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Xin chào {user.first_name}!\n"
        "Vui lòng nhập ngày nhận phòng và ngày trả phòng (dd/mm/yyyy):\n"
        "Ví dụ: 25/12/2023 27/12/2023",
        reply_markup=ReplyKeyboardRemove()
    )
    return GET_BOOKING_DATES

async def get_booking_dates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Xử lý ngày đặt phòng"""
    try:
        dates = update.message.text.split()
        if len(dates) != 2:
            raise ValueError("Vui lòng nhập cả ngày đến và ngày đi")
        
        # Chuyển đổi định dạng ngày
        check_in = datetime.strptime(dates[0], "%d/%m/%Y").strftime("%Y-%m-%d")
        check_out = datetime.strptime(dates[1], "%d/%m/%Y").strftime("%Y-%m-%d")
        
        # Lưu vào context
        context.user_data["check_in"] = check_in
        context.user_data["check_out"] = check_out
        
        # Lấy danh sách phòng trống
        rooms = get_available_rooms(check_in, check_out)
        
        if not rooms:
            await update.message.reply_text("⛔ Không có phòng trống trong khoảng thời gian này!")
            return ConversationHandler.END
            
        # Tạo keyboard chọn phòng
        keyboard = [
            [InlineKeyboardButton(
                f"{room['name']} - {room['type']} ({room['capacity']} người)", 
                callback_data=f"room_{room['id']}")
            ] for room in rooms
        ]
        keyboard.append([InlineKeyboardButton("❌ Hủy", callback_data="cancel")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🔍 Chọn phòng bạn muốn đặt:",
            reply_markup=reply_markup
        )
        
        return GET_GUEST_INFO
        
    except ValueError as e:
        await update.message.reply_text(f"❌ Lỗi: {str(e)}\nVui lòng nhập lại ngày (dd/mm/yyyy dd/mm/yyyy)")
        return GET_BOOKING_DATES
    except Exception as e:
        logger.error(f"Lỗi khi xử lý ngày đặt phòng: {str(e)}")
        await update.message.reply_text("⚠️ Có lỗi xảy ra, vui lòng thử lại sau!")
        return ConversationHandler.END

async def get_guest_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Xử lý thông tin khách hàng"""
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data == "cancel":
            await query.edit_message_text("Đã hủy quy trình đặt phòng")
            return ConversationHandler.END
            
        # Lưu room_id
        room_id = query.data.replace("room_", "")
        context.user_data["room_id"] = room_id
        
        # Yêu cầu thông tin khách
        await query.edit_message_text(
            "📝 Vui lòng nhập thông tin khách hàng:\n"
            "• Tên khách\n"
            "• Số điện thoại\n"
            "• Giá phòng (VND)\n"
            "• Tiền cọc (VND)\n\n"
            "Ví dụ:\n"
            "Nguyễn Văn A\n"
            "0912345678\n"
            "1500000\n"
            "500000"
        )
        
        return GET_GUEST_INFO
        
    except Exception as e:
        logger.error(f"Lỗi khi lấy thông tin khách: {str(e)}")
        await update.message.reply_text("⚠️ Có lỗi xảy ra, vui lòng thử lại sau!")
        return ConversationHandler.END

# ... (Các hàm khác như cancel_booking_command, update_booking_command, v.v.)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý tất cả callback từ inline keyboard"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "book":
        await start_booking(update, context)
    elif query.data == "check":
        await check_availability(update, context)
    elif query.data == "cancel":
        await cancel_booking_command(update, context)
    elif query.data == "today":
        await today_checkins(update, context)
    elif query.data.startswith("room_"):
        await get_guest_info(update, context)

async def handle_natural_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý tin nhắn tự nhiên bằng ChatGPT hoặc kiểm tra phòng trống"""
    try:
        # Ưu tiên kiểm tra yêu cầu phòng trống
        handled = await handle_availability_request(update, context)
        if handled:
            return
        message = update.message.text
        # Kiểm tra nếu là yêu cầu đặt phòng
        if any(keyword in message.lower() for keyword in ["đặt phòng", "book", "đặt"]):
            booking_data = await parse_booking_text(message)
            booking_id = create_booking(booking_data)
            await update.message.reply_text(
                f"✅ Đặt phòng thành công!\n"
                f"▪ Mã: {booking_id}\n"
                f"▪ Phòng: {booking_data['room_id']}\n"
                f"▪ Khách: {booking_data['guest_name']}\n"
                f"▪ Cọc: {booking_data['deposit']:,} VND"
            )
        else:
            await update.message.reply_text(
                "Tôi không hiểu yêu cầu của bạn. Vui lòng dùng lệnh /help để xem hướng dẫn"
            )
    except Exception as e:
        logger.error(f"Lỗi xử lý tin nhắn tự nhiên: {str(e)}")
        await update.message.reply_text(
            "❌ Có lỗi khi xử lý yêu cầu. Vui lòng thử lại hoặc dùng lệnh /book để đặt phòng"
        )

async def check_room_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler lệnh /schedule - Kiểm tra lịch phòng bất kỳ"""
    try:
        args = context.args
        if len(args) != 3:
            await update.message.reply_text(
                "⚠️ Vui lòng nhập đúng định dạng:\n"
                "/schedule <mã_phòng> <ngày_bắt đầu> <ngày_kết_thúc>\n"
                "Ví dụ: /schedule room_101 2024-12-20 2024-12-31"
            )
            return

        room_id, start_date, end_date = args
        availability = get_room_availability(room_id, start_date, end_date)

        if availability["available"]:
            message = f"✅ Phòng {room_id} TRỐNG từ {start_date} đến {end_date}"
        else:
            message = f"⛔ Phòng {room_id} ĐÃ ĐẶT trong khoảng thời gian:\n"
            for booking in availability["bookings"]:
                message += (
                    f"\n▪ {booking['check_in']} → {booking['check_out']} "
                    f"({booking['status']})"
                )

        await update.message.reply_text(message)

    except ValueError as e:
        await update.message.reply_text(f"❌ Lỗi: {str(e)}")
    except Exception as e:
        logger.error(f"Lỗi khi kiểm tra lịch phòng: {str(e)}")
        await update.message.reply_text("⚠️ Có lỗi xảy ra, vui lòng thử lại sau!")

async def handle_availability_request(update, context):
    """
    Handler cho tin nhắn hỏi phòng trống trong khoảng thời gian bất kỳ.
    """
    from app.firestore import get_all_available_rooms
    from app.openai_helper import parse_availability_request
    message = update.message.text
    req = parse_availability_request(message)
    if req.get("start_date") and req.get("end_date"):
        rooms = get_all_available_rooms(req["start_date"], req["end_date"])
        if not rooms:
            await update.message.reply_text(
                f"⛔ Không có phòng nào trống từ {req['start_date']} đến {req['end_date']}!"
            )
        else:
            msg = f"🏠 Danh sách phòng trống từ {req['start_date']} đến {req['end_date']}:\n"
            for room in rooms:
                msg += f"\n- {room['name']} (Loại: {room['type']}, Sức chứa: {room['capacity']})"
            await update.message.reply_text(msg)
        return True
    return False