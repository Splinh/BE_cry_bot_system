"""
Daily Report Service — Báo cáo hiệu suất hàng ngày đa chiều.

Tính năng:
- Thu thập PnL 24h, Win Rate, Open Positions summary
- Top signals đang active (từ trade_engine)
- Macro events hôm nay/sắp tới (từ MacroCalendar)
- Fear & Greed Index
- Lưu report history vào data/reports/
- Gửi tự động qua Telegram lúc 08:00 và 23:59 UTC+7
- API: GET /api/reports/latest, GET /api/reports/history
"""
import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger

from data.database import db
from notifiers.telegram_bot import TelegramNotifier


# ============================================
#  DAILY REPORT BUILDER
# ============================================

class DailyReportService:
    """Service xây dựng và gửi báo cáo hiệu suất trading."""

    REPORTS_DIR = "data/reports"

    def __init__(self, trade_engine=None, macro_calendar=None):
        self.trade_engine = trade_engine
        self.macro_calendar = macro_calendar
        self.notifier = TelegramNotifier()
        self._auto_morning = True    # Bật/tắt report buổi sáng (08:00)
        self._auto_nightly = True    # Bật/tắt report cuối ngày (23:59)
        self._running = False

        os.makedirs(self.REPORTS_DIR, exist_ok=True)

    # ============================================
    #  DATA COLLECTION
    # ============================================

    def _collect_trading_data(self) -> dict:
        """Thu thập dữ liệu trading từ DB + TradeEngine."""
        stats = db.get_stats()
        balance = db.get_balance()
        open_positions = db.get_open_positions()
        today_str = datetime.now().strftime("%Y-%m-%d")

        # Lệnh đóng hôm nay
        conn = db._get_conn()
        closed_today = conn.execute(
            "SELECT COUNT(*) as c, COALESCE(SUM(pnl), 0) as pnl, "
            "SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins "
            "FROM positions WHERE status!='OPEN' AND close_time LIKE ?",
            (f"{today_str}%",)
        ).fetchone()

        today_count = closed_today["c"] or 0
        today_pnl = closed_today["pnl"] or 0.0
        today_wins = closed_today["wins"] or 0
        today_winrate = (today_wins / today_count * 100) if today_count > 0 else 0.0

        # Top performers (best/worst trades hôm nay)
        top_trades = conn.execute(
            "SELECT coin, direction, pnl, entry_price, close_price "
            "FROM positions WHERE status!='OPEN' AND close_time LIKE ? "
            "ORDER BY pnl DESC LIMIT 3",
            (f"{today_str}%",)
        ).fetchall()

        worst_trades = conn.execute(
            "SELECT coin, direction, pnl, entry_price, close_price "
            "FROM positions WHERE status!='OPEN' AND close_time LIKE ? "
            "ORDER BY pnl ASC LIMIT 3",
            (f"{today_str}%",)
        ).fetchall()

        # Daily PnL từ TradeEngine (nếu có)
        daily_pnl_engine = 0.0
        auto_trade = False
        if self.trade_engine:
            daily_pnl_engine = getattr(self.trade_engine, 'daily_realized_pnl', 0.0)
            auto_trade = getattr(self.trade_engine, 'auto_trade_enabled', False)

        return {
            "balance": balance,
            "open_positions": len(open_positions),
            "open_positions_detail": [
                {
                    "coin": p.get("coin", "?"),
                    "direction": p.get("direction", "?"),
                    "entry": p.get("entry_price", 0),
                    "pnl": p.get("pnl", 0),
                }
                for p in open_positions[:10]
            ],
            "today_closed": today_count,
            "today_pnl": round(today_pnl, 2),
            "today_wins": today_wins,
            "today_winrate": round(today_winrate, 1),
            "total_closed": stats.get("closed_trades", 0),
            "total_pnl": stats.get("total_pnl", 0),
            "total_winrate": stats.get("win_rate", 0),
            "auto_trade_enabled": auto_trade,
            "daily_pnl_engine": round(daily_pnl_engine, 2),
            "top_trades": [dict(t) for t in top_trades] if top_trades else [],
            "worst_trades": [dict(t) for t in worst_trades] if worst_trades else [],
        }

    async def _collect_market_data(self) -> dict:
        """Thu thập dữ liệu thị trường (Fear & Greed, BTC price)."""
        fng = {"value": 50, "sentiment": "Neutral"}
        btc_price = 0.0

        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Fear & Greed
                try:
                    res = await client.get("https://api.alternative.me/fng/")
                    if res.status_code == 200:
                        data = res.json()
                        if "data" in data and len(data["data"]) > 0:
                            item = data["data"][0]
                            fng = {
                                "value": int(item.get("value", 50)),
                                "sentiment": item.get("value_classification", "Neutral"),
                            }
                except Exception as e:
                    logger.warning(f"[Report] F&G fetch error: {e}")

                # BTC price
                try:
                    res = await client.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
                    if res.status_code == 200:
                        btc_price = float(res.json().get("price", 0))
                except Exception as e:
                    logger.warning(f"[Report] BTC price fetch error: {e}")

        except ImportError:
            logger.warning("[Report] httpx not available for market data")

        return {
            "fear_greed": fng,
            "btc_price": round(btc_price, 2),
        }

    async def _collect_macro_data(self) -> dict:
        """Thu thập sự kiện macro."""
        events_today = []
        events_upcoming = []
        risk_level = "NORMAL"

        if self.macro_calendar:
            try:
                risk = await self.macro_calendar.assess_risk()
                risk_level = risk.get("risk_level", "NORMAL")

                all_events = await self.macro_calendar.get_all_events(7)
                for ev in all_events:
                    if ev.get("is_today"):
                        events_today.append({
                            "title": ev.get("title", ""),
                            "type": ev.get("type", ""),
                            "impact": ev.get("impact", ""),
                            "time": ev.get("time", ""),
                        })
                    elif not ev.get("is_past") and ev.get("hours_until", 999) <= 72:
                        events_upcoming.append({
                            "title": ev.get("title", ""),
                            "type": ev.get("type", ""),
                            "impact": ev.get("impact", ""),
                            "hours_until": ev.get("hours_until", 0),
                            "date": ev.get("date", ""),
                        })
            except Exception as e:
                logger.warning(f"[Report] Macro data error: {e}")

        return {
            "risk_level": risk_level,
            "events_today": events_today[:5],
            "events_upcoming": events_upcoming[:5],
        }

    # ============================================
    #  REPORT BUILDING
    # ============================================

    async def build_report(self, report_type: str = "daily") -> dict:
        """
        Xây dựng báo cáo đầy đủ.
        report_type: 'morning' | 'daily' | 'custom'
        """
        now = datetime.now()
        trading = self._collect_trading_data()
        market, macro = await asyncio.gather(
            self._collect_market_data(),
            self._collect_macro_data(),
        )

        report = {
            "id": now.strftime("%Y%m%d_%H%M%S"),
            "type": report_type,
            "timestamp": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M"),
            "trading": trading,
            "market": market,
            "macro": macro,
        }

        # Lưu report
        self._save_report(report)

        return report

    def _save_report(self, report: dict):
        """Lưu report vào file JSON."""
        try:
            filename = f"report_{report['id']}.json"
            filepath = os.path.join(self.REPORTS_DIR, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            logger.info(f"[Report] Saved: {filepath}")
        except Exception as e:
            logger.error(f"[Report] Save error: {e}")

    # ============================================
    #  TELEGRAM FORMAT
    # ============================================

    def format_morning_report(self, report: dict) -> str:
        """Format báo cáo buổi sáng (focus: market overview + upcoming events)."""
        t = report["trading"]
        m = report["market"]
        mc = report["macro"]

        fng_emoji = self._fng_emoji(m["fear_greed"]["value"])
        risk_emoji = {"NORMAL": "🟢", "HIGH": "🟡", "CRITICAL": "🔴"}.get(mc["risk_level"], "⚪")

        lines = [
            f"☀️ <b>BÁO CÁO BUỔI SÁNG</b> — {report['date']}",
            f"━━━━━━━━━━━━━━━━━━",
            f"",
            f"💰 <b>Trạng thái tài khoản:</b>",
            f"  ◽ Số dư: <b>${t['balance']:,.2f}</b>",
            f"  ◽ Vị thế đang mở: <b>{t['open_positions']}</b>",
            f"  ◽ Auto-Trade: {'🟢 ON' if t['auto_trade_enabled'] else '🔴 OFF'}",
            f"",
            f"📊 <b>Tổng quan thị trường:</b>",
            f"  ◽ BTC: <b>${m['btc_price']:,.2f}</b>",
            f"  ◽ Fear & Greed: {fng_emoji} <b>{m['fear_greed']['value']}</b> ({m['fear_greed']['sentiment']})",
            f"  ◽ Macro Risk: {risk_emoji} <b>{mc['risk_level']}</b>",
        ]

        # Sự kiện hôm nay
        if mc["events_today"]:
            lines.append(f"")
            lines.append(f"📅 <b>Sự kiện hôm nay:</b>")
            for ev in mc["events_today"]:
                impact_emoji = {"CRITICAL": "🔴", "HIGH": "🟡", "MEDIUM": "🔵"}.get(ev["impact"], "⚪")
                time_str = f" ({ev['time']})" if ev.get("time") else ""
                lines.append(f"  {impact_emoji} {ev['title']}{time_str}")

        # Sự kiện sắp tới
        if mc["events_upcoming"]:
            lines.append(f"")
            lines.append(f"⏰ <b>Sắp tới (72h):</b>")
            for ev in mc["events_upcoming"][:3]:
                impact_emoji = {"CRITICAL": "🔴", "HIGH": "🟡", "MEDIUM": "🔵"}.get(ev["impact"], "⚪")
                lines.append(f"  {impact_emoji} {ev['title']} ({ev['date']})")

        # Open positions summary
        if t["open_positions_detail"]:
            lines.append(f"")
            lines.append(f"📋 <b>Vị thế đang mở:</b>")
            for pos in t["open_positions_detail"][:5]:
                dir_emoji = "🟢" if pos["direction"] == "LONG" else "🔴"
                pnl_str = f"+${pos['pnl']:.2f}" if pos["pnl"] >= 0 else f"-${abs(pos['pnl']):.2f}"
                lines.append(f"  {dir_emoji} {pos['coin']} {pos['direction']} | Entry: ${pos['entry']:,.2f} | PnL: {pnl_str}")

        lines.append(f"━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)

    def format_daily_report(self, report: dict) -> str:
        """Format báo cáo cuối ngày (focus: performance + PnL breakdown)."""
        t = report["trading"]
        m = report["market"]
        mc = report["macro"]

        pnl_emoji = "📈" if t["today_pnl"] >= 0 else "📉"
        pnl_color = "🟢" if t["today_pnl"] >= 0 else "🔴"
        fng_emoji = self._fng_emoji(m["fear_greed"]["value"])

        lines = [
            f"📊 <b>BÁO CÁO HIỆU SUẤT NGÀY</b> — {report['date']}",
            f"━━━━━━━━━━━━━━━━━━",
            f"",
            f"💰 <b>Tài khoản:</b>",
            f"  ◽ Số dư: <b>${t['balance']:,.2f}</b>",
            f"  ◽ Vị thế đang mở: <b>{t['open_positions']}</b>",
            f"",
            f"✨ <b>Kết quả hôm nay:</b>",
            f"  ◽ Lệnh đã đóng: <b>{t['today_closed']}</b>",
            f"  ◽ Tỷ lệ thắng: <b>{t['today_winrate']:.1f}%</b> ({t['today_wins']}/{t['today_closed']})",
            f"  ◽ PnL hôm nay: {pnl_color} <b>{t['today_pnl']:+.2f} USD</b> {pnl_emoji}",
        ]

        # Top trades
        if t["top_trades"]:
            lines.append(f"")
            lines.append(f"🏆 <b>Best Trades:</b>")
            for trade in t["top_trades"][:3]:
                if trade.get("pnl", 0) > 0:
                    lines.append(f"  🟢 {trade['coin']} {trade.get('direction', '')} → +${trade['pnl']:.2f}")

        if t["worst_trades"]:
            worst_shown = [tr for tr in t["worst_trades"] if tr.get("pnl", 0) < 0]
            if worst_shown:
                lines.append(f"")
                lines.append(f"💀 <b>Worst Trades:</b>")
                for trade in worst_shown[:3]:
                    lines.append(f"  🔴 {trade['coin']} {trade.get('direction', '')} → ${trade['pnl']:.2f}")

        # Tổng kết tích lũy
        lines.extend([
            f"",
            f"🏆 <b>Thống kê tích lũy:</b>",
            f"  ◽ Tổng lệnh đóng: <b>{t['total_closed']}</b>",
            f"  ◽ Win Rate tổng: <b>{t['total_winrate']}%</b>",
            f"  ◽ PnL tích lũy: <b>{t['total_pnl']:+,.2f} USD</b>",
            f"",
            f"📊 <b>Thị trường:</b>",
            f"  ◽ BTC: <b>${m['btc_price']:,.2f}</b>",
            f"  ◽ Fear & Greed: {fng_emoji} <b>{m['fear_greed']['value']}</b> ({m['fear_greed']['sentiment']})",
        ])

        # Macro events sắp tới
        if mc["events_upcoming"]:
            lines.append(f"")
            lines.append(f"⏰ <b>Sự kiện sắp tới:</b>")
            for ev in mc["events_upcoming"][:3]:
                impact_emoji = {"CRITICAL": "🔴", "HIGH": "🟡"}.get(ev["impact"], "🔵")
                lines.append(f"  {impact_emoji} {ev['title']} ({ev['date']})")

        lines.append(f"━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)

    @staticmethod
    def _fng_emoji(value: int) -> str:
        """Emoji cho Fear & Greed index."""
        if value <= 25:
            return "😱"  # Extreme Fear
        elif value <= 45:
            return "😰"  # Fear
        elif value <= 55:
            return "😐"  # Neutral
        elif value <= 75:
            return "😀"  # Greed
        else:
            return "🤑"  # Extreme Greed

    # ============================================
    #  SEND & SCHEDULE
    # ============================================

    async def send_report(self, report_type: str = "daily") -> dict:
        """Build + format + gửi report về Telegram."""
        report = await self.build_report(report_type)

        if report_type == "morning":
            text = self.format_morning_report(report)
        else:
            text = self.format_daily_report(report)

        # Gửi tới tất cả admin + whitelisted users
        from core.security import SecurityManager
        sec = SecurityManager()
        target_ids = list(set(
            sec.config.get("admin_ids", []) +
            sec.config.get("whitelist_ids", [])
        ))

        if not target_ids:
            await self.notifier.send_message(text)
        else:
            for cid in target_ids:
                try:
                    await self.notifier.send_message(text, chat_id=cid)
                except Exception as e:
                    logger.error(f"[Report] Send error to {cid}: {e}")

        logger.success(f"[Report] Sent {report_type} report to {len(target_ids) or 1} recipients")
        return report

    async def generate_on_demand(self) -> dict:
        """Generate report theo yêu cầu (lệnh /report)."""
        return await self.send_report("daily")

    def toggle_morning(self, enable: bool) -> bool:
        self._auto_morning = enable
        return self._auto_morning

    def toggle_nightly(self, enable: bool) -> bool:
        self._auto_nightly = enable
        return self._auto_nightly

    # ============================================
    #  REPORT HISTORY
    # ============================================

    def get_latest_report(self) -> Optional[dict]:
        """Lấy report mới nhất."""
        try:
            files = sorted(
                [f for f in os.listdir(self.REPORTS_DIR) if f.startswith("report_") and f.endswith(".json")],
                reverse=True
            )
            if files:
                with open(os.path.join(self.REPORTS_DIR, files[0]), "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"[Report] Get latest error: {e}")
        return None

    def get_report_history(self, limit: int = 30, offset: int = 0) -> list[dict]:
        """Lấy danh sách reports (metadata only, không full data)."""
        try:
            files = sorted(
                [f for f in os.listdir(self.REPORTS_DIR) if f.startswith("report_") and f.endswith(".json")],
                reverse=True
            )

            result = []
            for fname in files[offset:offset + limit]:
                try:
                    with open(os.path.join(self.REPORTS_DIR, fname), "r", encoding="utf-8") as f:
                        report = json.load(f)
                        result.append({
                            "id": report.get("id", ""),
                            "type": report.get("type", ""),
                            "date": report.get("date", ""),
                            "time": report.get("time", ""),
                            "timestamp": report.get("timestamp", ""),
                            "pnl": report.get("trading", {}).get("today_pnl", 0),
                            "balance": report.get("trading", {}).get("balance", 0),
                            "winrate": report.get("trading", {}).get("today_winrate", 0),
                            "trades_closed": report.get("trading", {}).get("today_closed", 0),
                            "btc_price": report.get("market", {}).get("btc_price", 0),
                            "fear_greed": report.get("market", {}).get("fear_greed", {}).get("value", 50),
                        })
                except Exception:
                    continue

            return result
        except Exception as e:
            logger.error(f"[Report] Get history error: {e}")
            return []

    def get_report_by_id(self, report_id: str) -> Optional[dict]:
        """Lấy report chi tiết theo ID."""
        try:
            filepath = os.path.join(self.REPORTS_DIR, f"report_{report_id}.json")
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"[Report] Get by ID error: {e}")
        return None


# ============================================
#  SCHEDULER (chạy nền)
# ============================================
#  SCHEDULER LOOP (UTC+7 Aware & Drift-Resistant)
# ============================================

_report_service: Optional[DailyReportService] = None
VN_TZ = timezone(timedelta(hours=7))


def get_report_service() -> DailyReportService:
    """Singleton accessor."""
    global _report_service
    if _report_service is None:
        _report_service = DailyReportService()
    return _report_service


def init_report_service(trade_engine=None, macro_calendar=None) -> DailyReportService:
    """Khởi tạo service với dependencies."""
    global _report_service
    _report_service = DailyReportService(
        trade_engine=trade_engine,
        macro_calendar=macro_calendar,
    )
    return _report_service


async def run_report_scheduler():
    """
    Vòng lặp chạy nền gửi báo cáo định kỳ:
    - Morning Report: 08:00 - 08:30 UTC+7 (market overview)
    - Nightly Report: 23:55 - 23:59 UTC+7 (trading performance)
    
    Cơ chế chống trễ/bỏ lỡ (Drift-Resistant):
    - Dùng múi giờ chuẩn UTC+7 (không phụ thuộc timezone của VPS OS).
    - Dùng cờ ngày `last_morning` và `last_nightly` kết hợp khung giờ rộng để
      tránh việc event loop bị lag làm trôi mất phút 00 hoặc phút 59.
    """
    service = get_report_service()
    service._running = True
    logger.info("🚀 [Report] Scheduler started — Morning (08:00 UTC+7), Nightly (23:59 UTC+7)")

    last_morning = ""
    last_nightly = ""

    while service._running:
        try:
            # Luôn dùng giờ Việt Nam UTC+7
            now = datetime.now(VN_TZ)
            today_str = now.strftime("%Y-%m-%d")

            # Morning report: trong khoảng 08:00 -> 08:30
            if (now.hour == 8 and now.minute <= 30
                    and service._auto_morning
                    and last_morning != today_str):
                logger.info(f"☀️ [Report] Đang tạo và gửi Morning Report ({today_str})...")
                last_morning = today_str
                await service.send_report("morning")

            # Nightly report: trong khoảng 23:55 -> 23:59 (hoặc 00:00 - 00:05 bù cho ngày trước)
            is_night_window = (now.hour == 23 and now.minute >= 55)
            if (is_night_window
                    and service._auto_nightly
                    and last_nightly != today_str):
                logger.info(f"📊 [Report] Đang tạo và gửi Nightly Report ({today_str})...")
                last_nightly = today_str
                await service.send_report("daily")

            await asyncio.sleep(20)
        except Exception as e:
            logger.error(f"❌ [Report] Lỗi trong scheduler: {e}")
            await asyncio.sleep(30)

