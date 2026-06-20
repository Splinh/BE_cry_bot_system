"""
Daily Performance Report Scheduler
Tự động tính toán PNL, tỷ lệ thắng trong ngày và gửi báo cáo về Telegram lúc 23:59.
"""
import asyncio
from datetime import datetime
from loguru import logger
from notifiers.telegram_bot import TelegramNotifier
from data.database import db


async def start_report_scheduler():
    """Vòng lặp chạy nền để gửi báo cáo Daily lúc 23:59."""
    notifier = TelegramNotifier()
    logger.info("Khởi động trình lên lịch báo cáo hàng ngày (gửi lúc 23:59)...")
    
    while True:
        try:
            now = datetime.now()
            # Gửi lúc 23:59
            if now.hour == 23 and now.minute == 59:
                logger.info("Đang tạo báo cáo hiệu suất giao dịch hàng ngày...")
                
                # Lấy dữ liệu thống kê chung
                stats = db.get_stats()
                balance = db.get_balance()
                
                # Lấy PNL và số lượng lệnh đóng hôm nay
                conn = db._get_conn()
                today_str = now.strftime("%Y-%m-%d")
                
                open_pos = db.get_open_positions()
                
                # Truy vấn các lệnh đóng hôm nay
                closed_today = conn.execute(
                    "SELECT COUNT(*) as c, SUM(pnl) as pnl, "
                    "SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins "
                    "FROM positions WHERE status!='OPEN' AND close_time LIKE ?",
                    (f"{today_str}%",)
                ).fetchone()
                
                today_count = closed_today["c"] or 0
                today_pnl = closed_today["pnl"] or 0.0
                today_wins = closed_today["wins"] or 0
                today_winrate = (today_wins / today_count * 100) if today_count > 0 else 0.0
                
                emoji = "📈" if today_pnl >= 0 else "📉"
                pnl_color = "🟢" if today_pnl >= 0 else "🔴"
                
                msg = (
                    f"📊 <b>BÁO CÁO HIỆU SUẤT GÀY ({today_str})</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"💰 <b>Số dư hiện tại:</b> ${balance:,.2f}\n"
                    f"💼 <b>Vị thế đang mở:</b> {len(open_pos)}\n\n"
                    f"✨ <b>Kết quả hôm nay:</b>\n"
                    f"  ◽ Số lệnh đã đóng: {today_count}\n"
                    f"  ◽ Tỷ lệ thắng: {today_winrate:.1f}%\n"
                    f"  ◽ Tổng PNL hôm nay: {pnl_color} <b>{today_pnl:+.2f} USD</b> {emoji}\n\n"
                    f"🏆 <b>Thống kê tích lũy:</b>\n"
                    f"  ◽ Tổng lệnh đã đóng: {stats['closed_trades']}\n"
                    f"  ◽ Win Rate tổng: {stats['win_rate']}%\n"
                    f"  ◽ Tổng PNL tích lũy: {stats['total_pnl']:+,.2f} USD\n"
                    f"━━━━━━━━━━━━━━━━━━"
                )
                
                # Lấy danh sách nhận tin (Admins & Whitelist)
                from core.security import SecurityManager
                sec = SecurityManager()
                target_ids = list(set(sec.config.get("admin_ids", []) + sec.config.get("whitelist_ids", [])))
                
                if not target_ids:
                    # Gửi tới chat_id mặc định
                    await notifier.send_message(msg)
                else:
                    for cid in target_ids:
                        try:
                            await notifier.send_message(msg, chat_id=cid)
                        except Exception as e:
                            logger.error(f"Lỗi gửi báo cáo cho Chat ID {cid}: {e}")
                
                # Tránh gửi lặp lại trong phút 59
                await asyncio.sleep(60)
            
            # Kiểm tra mỗi 30 giây
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Lỗi trong bộ lập lịch báo cáo hàng ngày: {e}")
            await asyncio.sleep(30)
