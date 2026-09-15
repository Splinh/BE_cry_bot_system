"""
Trade Outcome Analyzer — Post-mortem tự động cho mỗi trade đã đóng.

Chức năng:
1. Phân loại trade theo pattern (breakout, reversal, continuation, false signal)
2. So sánh SL/TP thực tế vs. "lý tưởng"
3. Phân tích thời gian (giờ nào, ngày nào thắng nhiều nhất)
4. Weekly report tổng hợp
"""
import json
import os
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger


class TradeAnalyzer:
    """
    Phan tich tu dong sau moi trade + tao bao cao tuan.
    """

    REPORT_FILE = "data/trade_analysis.json"

    def __init__(self):
        self.analyses: list = []
        self._load()

    def _load(self):
        if os.path.exists(self.REPORT_FILE):
            try:
                with open(self.REPORT_FILE, "r") as f:
                    self.analyses = json.load(f)
            except Exception:
                self.analyses = []

    def _save(self):
        os.makedirs(os.path.dirname(self.REPORT_FILE), exist_ok=True)
        try:
            with open(self.REPORT_FILE, "w") as f:
                json.dump(self.analyses[-500:], f, indent=2)  # Giu 500 analyses moi nhat
        except Exception as e:
            logger.error(f"[TradeAnalyzer] Save error: {e}")

    def analyze_trade(self, trade: dict) -> dict:
        """
        Phan tich 1 trade da dong.

        Args:
            trade: position data tu TradeEngine (entry, close, pnl, timestamps, etc.)

        Returns:
            {
                "trade_key": "...",
                "outcome": "WIN" | "LOSS",
                "pnl": float,
                "pnl_pct": float,
                "duration_hours": float,
                "pattern": "BREAKOUT" | "REVERSAL" | "CONTINUATION" | "FALSE_SIGNAL" | "UNKNOWN",
                "close_reason": "TP1" | "TP2" | "TP3" | "SL" | "MANUAL" | ...,
                "time_analysis": {...},
                "sl_tp_analysis": {...},
                "suggestions": [...],
            }
        """
        entry = trade.get("entry_price", 0)
        close = trade.get("close_price", 0)
        direction = trade.get("direction", "LONG")
        leverage = trade.get("leverage", 1)
        pnl = trade.get("pnl", 0)
        sl = trade.get("sl", 0)
        tp1 = trade.get("tp1", 0)
        tp3 = trade.get("tp3", 0)
        close_reason = trade.get("close_reason", trade.get("reason", "UNKNOWN"))
        open_time_str = trade.get("open_time", "")
        close_time_str = trade.get("close_time", "")

        outcome = "WIN" if pnl > 0 else "LOSS"

        # PnL %
        margin = trade.get("margin", 0)
        pnl_pct = (pnl / margin * 100) if margin > 0 else 0

        # Duration
        duration_hours = 0
        open_hour = 0
        open_dow = 0
        try:
            if open_time_str and close_time_str:
                open_dt = datetime.fromisoformat(open_time_str)
                close_dt = datetime.fromisoformat(close_time_str)
                duration_hours = (close_dt - open_dt).total_seconds() / 3600
                open_hour = open_dt.hour
                open_dow = open_dt.weekday()
        except Exception:
            pass

        # Pattern classification
        pattern = self._classify_pattern(trade, close_reason)

        # SL/TP analysis
        sl_tp_analysis = self._analyze_sl_tp(trade)

        # Suggestions
        suggestions = self._generate_suggestions(trade, outcome, pattern, sl_tp_analysis, duration_hours)

        analysis = {
            "trade_key": trade.get("key", ""),
            "coin": trade.get("coin", ""),
            "direction": direction,
            "leverage": leverage,
            "outcome": outcome,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "duration_hours": round(duration_hours, 1),
            "pattern": pattern,
            "close_reason": close_reason,
            "time_analysis": {
                "open_hour": open_hour,
                "open_dow": open_dow,
                "open_dow_name": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][open_dow],
            },
            "sl_tp_analysis": sl_tp_analysis,
            "suggestions": suggestions,
            "analyzed_at": datetime.now().isoformat(),
        }

        self.analyses.append(analysis)
        self._save()

        logger.info(
            f"[TradeAnalyzer] {trade.get('coin', '?')} {direction}: "
            f"{outcome} {pnl:+.2f}$ ({pnl_pct:+.1f}%) | "
            f"Pattern: {pattern} | Reason: {close_reason}"
        )

        return analysis

    def _classify_pattern(self, trade: dict, close_reason: str) -> str:
        """Phan loai pattern cua trade."""
        if close_reason in ("SL_HIT", "LIQUIDATED"):
            return "FALSE_SIGNAL"
        if close_reason == "REVERSAL_SIGNAL":
            return "REVERSAL"
        if "TP3" in str(close_reason):
            return "BREAKOUT"  # Dat TP3 = xu huong manh
        if "TP1" in str(close_reason) or "TP2" in str(close_reason):
            return "CONTINUATION"
        return "UNKNOWN"

    def _analyze_sl_tp(self, trade: dict) -> dict:
        """Phan tich hieu qua SL/TP."""
        entry = trade.get("entry_price", 0)
        close = trade.get("close_price", 0)
        sl = trade.get("sl", 0)
        tp1 = trade.get("tp1", 0)
        tp3 = trade.get("tp3", 0)
        direction = trade.get("direction", "LONG")

        if entry <= 0:
            return {}

        sl_distance_pct = abs(entry - sl) / entry * 100 if sl > 0 else 0

        # Actual move
        if direction == "LONG":
            actual_move_pct = (close - entry) / entry * 100
            max_possible = (tp3 - entry) / entry * 100 if tp3 > 0 else 0
        else:
            actual_move_pct = (entry - close) / entry * 100
            max_possible = (entry - tp3) / entry * 100 if tp3 > 0 else 0

        # Efficiency: bao nhieu % cua TP3 da capture duoc
        efficiency = actual_move_pct / max_possible * 100 if max_possible > 0 else 0

        return {
            "sl_distance_pct": round(sl_distance_pct, 2),
            "actual_move_pct": round(actual_move_pct, 2),
            "max_possible_pct": round(max_possible, 2),
            "efficiency": round(min(100, max(-100, efficiency)), 1),
            "sl_was_too_tight": sl_distance_pct < 1.5 and trade.get("close_reason") == "SL_HIT",
        }

    def _generate_suggestions(self, trade: dict, outcome: str, pattern: str, sl_tp: dict, duration_hours: float = 0) -> list:
        """Tao goi y cai thien."""
        suggestions = []

        if pattern == "FALSE_SIGNAL":
            if sl_tp.get("sl_was_too_tight"):
                suggestions.append("SL qua chat, can mo rong SL hoac giam leverage")
            else:
                suggestions.append("Tin hieu sai, xem xet tang min_score cho timeframe nay")

        if outcome == "WIN" and sl_tp.get("efficiency", 0) < 30:
            suggestions.append("Chot som qua, TP1 gap -> chi capture duoc it loi nhuan. Xem xet giu lau hon")

        if duration_hours > 48 and outcome == "LOSS":
            suggestions.append("Giu lenh qua lau roi thua. Xem xet time-based exit (dong lenh sau 24-48h)")

        if trade.get("leverage", 1) > 20 and outcome == "LOSS":
            suggestions.append("Leverage qua cao, rui ro lon. Giam ve 5-10x de an toan hon")

        return suggestions

    # ==========================================
    #  WEEKLY REPORT
    # ==========================================

    def generate_weekly_report(self, days: int = 7) -> dict:
        """
        Tao bao cao tuan.

        Returns:
            {
                "period": "2026-09-08 → 2026-09-15",
                "total_trades": 15,
                "win_rate": 60.0,
                "total_pnl": +125.50,
                "avg_pnl": +8.37,
                "best_trade": {...},
                "worst_trade": {...},
                "by_hour": {...},
                "by_day": {...},
                "by_coin": {...},
                "patterns": {...},
                "suggestions": [...],
            }
        """
        cutoff = datetime.now() - timedelta(days=days)
        recent = []
        for a in self.analyses:
            try:
                analyzed_at = datetime.fromisoformat(a.get("analyzed_at", ""))
                if analyzed_at >= cutoff:
                    recent.append(a)
            except Exception:
                continue

        if not recent:
            return {"total_trades": 0, "message": "Khong co trade nao trong tuan qua"}

        total = len(recent)
        wins = [t for t in recent if t["outcome"] == "WIN"]
        losses = [t for t in recent if t["outcome"] == "LOSS"]
        win_rate = len(wins) / total * 100

        total_pnl = sum(t.get("pnl", 0) for t in recent)
        avg_pnl = total_pnl / total

        # Best/worst
        best = max(recent, key=lambda t: t.get("pnl", 0))
        worst = min(recent, key=lambda t: t.get("pnl", 0))

        # By hour
        by_hour = {}
        for t in recent:
            h = t.get("time_analysis", {}).get("open_hour", 0)
            if h not in by_hour:
                by_hour[h] = {"count": 0, "wins": 0, "pnl": 0}
            by_hour[h]["count"] += 1
            if t["outcome"] == "WIN":
                by_hour[h]["wins"] += 1
            by_hour[h]["pnl"] += t.get("pnl", 0)

        # By day of week
        by_day = {}
        for t in recent:
            d = t.get("time_analysis", {}).get("open_dow_name", "Unknown")
            if d not in by_day:
                by_day[d] = {"count": 0, "wins": 0, "pnl": 0}
            by_day[d]["count"] += 1
            if t["outcome"] == "WIN":
                by_day[d]["wins"] += 1
            by_day[d]["pnl"] += t.get("pnl", 0)

        # By coin
        by_coin = {}
        for t in recent:
            c = t.get("coin", "?")
            if c not in by_coin:
                by_coin[c] = {"count": 0, "wins": 0, "pnl": 0}
            by_coin[c]["count"] += 1
            if t["outcome"] == "WIN":
                by_coin[c]["wins"] += 1
            by_coin[c]["pnl"] += t.get("pnl", 0)

        # Patterns
        patterns = {}
        for t in recent:
            p = t.get("pattern", "UNKNOWN")
            if p not in patterns:
                patterns[p] = {"count": 0, "wins": 0}
            patterns[p]["count"] += 1
            if t["outcome"] == "WIN":
                patterns[p]["wins"] += 1

        # Suggestions
        suggestions = []
        if win_rate < 40:
            suggestions.append("Win rate thap, can tang min_score hoac chi trade khi co du chi bao dong thuan")
        if avg_pnl < 0:
            suggestions.append("PnL trung binh am, xem xet giam leverage hoac toi uu SL/TP")

        # Best hour
        best_hour = max(by_hour.items(), key=lambda x: x[1]["pnl"])[0] if by_hour else None
        if best_hour is not None:
            suggestions.append(f"Gio trade tot nhat: {best_hour}:00 UTC")

        # Best day
        best_day = max(by_day.items(), key=lambda x: x[1]["pnl"])[0] if by_day else None
        if best_day:
            suggestions.append(f"Ngay trade tot nhat: {best_day}")

        now = datetime.now()
        start = now - timedelta(days=days)

        return {
            "period": f"{start.strftime('%Y-%m-%d')} → {now.strftime('%Y-%m-%d')}",
            "total_trades": total,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(avg_pnl, 2),
            "best_trade": {
                "coin": best.get("coin"), "pnl": best.get("pnl"),
                "direction": best.get("direction"), "pattern": best.get("pattern"),
            },
            "worst_trade": {
                "coin": worst.get("coin"), "pnl": worst.get("pnl"),
                "direction": worst.get("direction"), "pattern": worst.get("pattern"),
            },
            "by_hour": by_hour,
            "by_day": by_day,
            "by_coin": by_coin,
            "patterns": patterns,
            "suggestions": suggestions,
        }

    def format_weekly_telegram(self, report: dict) -> str:
        """Format weekly report cho Telegram."""
        if report.get("total_trades", 0) == 0:
            return "📊 <b>BÁO CÁO TUẦN</b>\n\nKhông có trade nào trong tuần qua."

        lines = [
            f"📊 <b>BÁO CÁO TUẦN</b>",
            f"📅 {report['period']}",
            f"━━━━━━━━━━━━━━━━━━",
            f"📈 Tổng: <b>{report['total_trades']}</b> trades",
            f"✅ Win: {report['wins']} | ❌ Loss: {report['losses']}",
            f"🎯 Win Rate: <b>{report['win_rate']:.1f}%</b>",
            f"💰 PnL: <b>${report['total_pnl']:+,.2f}</b>",
            f"📊 Avg PnL: ${report['avg_pnl']:+,.2f}/trade",
            f"",
            f"🏆 Best: {report['best_trade']['coin']} {report['best_trade']['direction']} → ${report['best_trade']['pnl']:+,.2f}",
            f"💀 Worst: {report['worst_trade']['coin']} {report['worst_trade']['direction']} → ${report['worst_trade']['pnl']:+,.2f}",
        ]

        if report.get("suggestions"):
            lines.append("")
            lines.append("💡 <b>Gợi ý cải thiện:</b>")
            for s in report["suggestions"][:3]:
                lines.append(f"• {s}")

        lines.append("━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)
