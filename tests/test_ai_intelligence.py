"""
Test AI Intelligence modules:
- Market Regime / Whale Tracker / News Intelligence / ML Signal Booster / Trade Analyzer
- Regression guard cho cac loi da fix: P0 NameError 'sym', ML deadlock, event impact DB rong,
  whale liquidation endpoint hong, ai_details khong duoc luu vao position.

Usage: python backend/tests/test_ai_intelligence.py

ASCII-only to prevent Windows encoding console crashes.
"""
import asyncio
import builtins
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from analytics import ml_signal_booster as ml_mod
from analytics import news_intelligence as news_mod
from analytics.ml_signal_booster import AdaptiveSignalBooster, get_booster, reset_booster
from analytics.news_intelligence import NewsIntelligence
from analytics.whale_tracker import WhaleTracker


BACKEND_DIR = Path(__file__).resolve().parent.parent


def _make_df(n: int = 25) -> pd.DataFrame:
    """DataFrame gia lap: du 25 dong + day du chi bao (giong output calculate_indicators)."""
    return pd.DataFrame({
        "close": np.linspace(100.0, 110.0, n),
        "volume": np.ones(n) * 50.0,
        "rsi": [55.0] * n,
        "macd_hist": [0.2] * n,
        "ema20": [102.0] * n,
        "ema50": [101.0] * n,
        "bb_upper": [112.0] * n,
        "bb_lower": [95.0] * n,
        "vwap": [103.0] * n,
        "adx": [28.0] * n,
        "atr": [2.0] * n,
        "fib_618": [100.5] * n,
    })


def _patch_ml_files(tmp_dir: str):
    """Chuyen file ML sang thu muc tam de test khong ghi vao data/ that."""
    originals = (ml_mod.ML_TRAINING_FILE, ml_mod.ML_MODEL_FILE)
    ml_mod.ML_TRAINING_FILE = os.path.join(tmp_dir, "ml_training_data.json")
    ml_mod.ML_MODEL_FILE = os.path.join(tmp_dir, "ml_signal_model.pkl")
    return originals


def _restore_ml_files(originals):
    ml_mod.ML_TRAINING_FILE, ml_mod.ML_MODEL_FILE = originals
    reset_booster()


# ==========================================
#  [1] SCANNER - REGRESSION GUARD LOI P0
# ==========================================

def test_scanner_no_undefined_global_names():
    """
    Loi P0: signal_scanner.py goi _apply_ai_adjustments(..., symbol=sym) trong khi 'sym'
    chi la bien local cua _refresh_ai_intelligence -> NameError luc runtime, bi
    'except Exception as inner_e' nuot -> KHONG gui duoc tin hieu nao.
    Check tinh: moi ten duoc dung o global scope trong module phai ton tai that.
    """
    print("=== [1] SCANNER: khong con ten global khong xac dinh (P0 regression) ===")
    import symtable

    src_path = BACKEND_DIR / "analytics" / "signal_scanner.py"
    src = src_path.read_text(encoding="utf-8")
    st = symtable.symtable(src, str(src_path), "exec")

    module_names = {s.get_name() for s in st.get_symbols()}
    undefined = []

    def walk(table, cls_name=""):
        for child in table.get_children():
            name = child.get_name()
            if child.get_type() == "class":
                walk(child, cls_name=name)
            elif child.get_type() == "function":
                for sym in child.get_symbols():
                    if sym.is_global() and not sym.is_assigned():
                        n = sym.get_name()
                        if n not in module_names and not hasattr(builtins, n):
                            undefined.append(f"{cls_name}.{name} -> {n}")
                walk(child, cls_name)

    walk(st)
    if undefined:
        print(f"  FAIL: ten khong xac dinh: {undefined}")
    assert not undefined, f"Co ten global khong ton tai (se gay NameError): {undefined}"

    # Guard truc tiep cho call-site da tung loi: arg 'symbol' phai la bien 'symbol'
    # (khong phai 'sym' - bien chi ton tai trong _refresh_ai_intelligence).
    import ast

    symbol_args = []
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_apply_ai_adjustments"):
            for kw in node.keywords:
                if kw.arg == "symbol":
                    symbol_args.append(kw.value)
    assert symbol_args, "Khong tim thay call _apply_ai_adjustments nao"
    for val in symbol_args:
        assert isinstance(val, ast.Name), "Tham so 'symbol' phai la 1 bien"
        assert val.id == "symbol", (
            f"Call-site dung bien '{val.id}' - bien nay khong ton tai trong _scan_loop "
            f"(se gay NameError)"
        )
    print(f"  OK: {len(symbol_args)} call-site _apply_ai_adjustments dung bien 'symbol'")
    print("  OK: khong co global name khong xac dinh")


# ==========================================
#  [2] NEWS INTELLIGENCE - CONTRACT
# ==========================================

async def test_news_bias_contract():
    """
    C1/C2: get_news_bias() la async va PHAI duoc await tai call-site.
    Kiem tra contract tra ve du cac key ma _apply_ai_adjustments su dung.
    """
    print("=== [2] NEWS INTELLIGENCE: get_news_bias la async + du contract ===")
    intel = NewsIntelligence()
    assert asyncio.iscoroutinefunction(intel.get_news_bias), "get_news_bias phai la async"

    coro = intel.get_news_bias(recent_news=[], upcoming_events=[])
    assert asyncio.iscoroutine(coro), "get_news_bias() phai tra ve coroutine (phai await)"
    coro.close()  # khong await -> dong coroutine de tranh warning

    bias = await intel.get_news_bias(recent_news=[], upcoming_events=[])
    assert isinstance(bias, dict), "get_news_bias phai tra ve dict"
    for key in ("news_bias", "news_confidence", "rating_adjust", "leverage_mult",
                "sl_mult", "should_pause_auto_trade", "warnings"):
        assert key in bias, f"Thieu key '{key}' trong ket qua get_news_bias"
    print(f"  OK: news_bias={bias['news_bias']} | rating_adjust={bias['rating_adjust']} "
          f"| pause={bias['should_pause_auto_trade']}")


# ==========================================
#  [3] NEWS INTELLIGENCE - EVENT IMPACT DB (C4)
# ==========================================

async def test_event_impact_db_records_outcome():
    """
    C4: record_event_outcome() truoc day khong co caller nao -> DB luon rong
    -> get_historical_reaction() luon total_events=0 -> event_bias luon NEUTRAL.
    auto_record_past_events() phai ghi nhan duoc su kien da qua va khong ghi trung.
    """
    print("=== [3] NEWS INTELLIGENCE: auto_record_past_events ghi Event Impact DB (C4) ===")
    tmp_dir = tempfile.mkdtemp(prefix="cbs_news_")
    old_file = news_mod.EVENT_HISTORY_FILE
    news_mod.EVENT_HISTORY_FILE = os.path.join(tmp_dir, "event_impact_history.json")
    try:
        intel = NewsIntelligence()
        assert intel.get_historical_reaction("CPI")["total_events"] == 0

        # Patch lay gia de test deterministic (khong phu thuoc mang)
        async def fake_prices(event_dt):
            return (100000.0, 103000.0, 98000.0)  # +3% sau 1h -> BULLISH

        intel._fetch_btc_prices_around = fake_prices

        events = [{
            "date": "2026-09-13",
            "type": "CPI",
            "title": "CPI (Aug 2026)",
            "impact": "HIGH",
            "is_past": True,
            "datetime": (datetime.now() - timedelta(days=2)).isoformat(),
        }]

        recorded = await intel.auto_record_past_events(events)
        assert recorded == 1, f"Phai ghi nhan 1 su kien, nhan duoc {recorded}"

        hist = intel.get_historical_reaction("CPI")
        assert hist["total_events"] == 1, "Event Impact DB phai co 1 su kien"
        assert hist["bias"] == "BULLISH", f"Ky vong BULLISH, nhan duoc {hist['bias']}"
        print(f"  OK: ghi nhan {recorded} su kien | bias={hist['bias']} | "
              f"avg_1h={hist['avg_1h_change']}% | conf={hist['confidence']}")

        # Goi lai -> khong ghi trung
        assert await intel.auto_record_past_events(events) == 0, "Khong duoc ghi trung su kien"
        print("  OK: khong ghi trung su kien da co trong DB")

        # Su kien chua du 24h -> bo qua (chua co du gia +24h de danh gia)
        recent = dict(events[0])
        recent["datetime"] = (datetime.now() - timedelta(hours=3)).isoformat()
        recent["type"] = "FOMC"
        assert await intel.auto_record_past_events([recent]) == 0, "Su kien < 24h phai bi bo qua"
        print("  OK: bo qua su kien chua du 24h")
    finally:
        news_mod.EVENT_HISTORY_FILE = old_file
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_llm_client_wiring():
    """
    NewsIntelligence._get_llm() truoc day import `get_provider` tu ai.llm_client
    (khong ton tai) -> luon fallback keyword, NEWS_LLM_FOR_HIGH_IMPACT vo dung.
    Guard: phai lay duoc singleton llm_client that va co API dung (is_ready/complete).
    """
    print("=== [9] NEWS INTELLIGENCE: wiring LLM client ===")
    from ai.llm_client import LLMClient, llm_client

    intel = NewsIntelligence()
    llm = intel._get_llm()
    assert llm is not None, "Phai lay duoc LLM client (khong duoc raise ImportError)"
    assert isinstance(llm, LLMClient), "Phai la LLMClient cua ai/llm_client.py"
    assert llm is llm_client, "Phai dung singleton cua he thong"
    assert hasattr(llm, "is_ready") and hasattr(llm, "complete"), "API LLM client phai dung"
    assert isinstance(llm.is_ready(), bool)
    print(f"  OK: LLM client = {type(llm).__name__} | provider={llm.provider_name} "
          f"| ready={llm.is_ready()}")


def test_parse_event_dt():
    """Ho tro ca ISO co timezone (live events) va 'date' tran (built-in events)."""
    print("=== [4] NEWS INTELLIGENCE: parse thoi diem su kien ===")
    parse = NewsIntelligence._parse_event_dt

    dt_iso = parse({"datetime": "2026-09-13T12:00:00+00:00"})
    assert dt_iso is not None and dt_iso.tzinfo is None, "Phai ve naive local time"
    assert dt_iso.year == 2026 and dt_iso.month == 9

    dt_date = parse({"date": "2026-09-13"})
    assert dt_date is not None and (dt_date.year, dt_date.month, dt_date.day) == (2026, 9, 13)

    assert parse({"datetime": "khong-phai-ngay", "date": "abc"}) is None
    print("  OK: ISO co tz / chi co date / gia tri loi deu xu ly dung")


# ==========================================
#  [5] ML BOOSTER - FIX DEADLOCK
# ==========================================

def test_ml_features_collected_before_training():
    """
    Loi deadlock: predict() return som khi chua train -> khong co '_features'
    -> trade_engine khong thu thap duoc sample -> khong bao gio du 30 -> khong bao gio train.
    Sau fix: '_features' phai co NGAY CA KHI chua train.
    """
    print("=== [5] ML BOOSTER: thu thap feature truoc khi train (fix deadlock) ===")
    tmp_dir = tempfile.mkdtemp(prefix="cbs_ml_")
    originals = _patch_ml_files(tmp_dir)
    try:
        reset_booster()
        booster = AdaptiveSignalBooster()
        booster.is_trained = False
        booster.model = None
        booster.training_data = []

        result = booster.predict(_make_df(), {"direction": "LONG", "bull_score": 7, "bear_score": 2})
        assert result["is_trained"] is False, "Chua train thi is_trained phai la False"
        assert result.get("_features") is not None, \
            "Phai co '_features' khi chua train (neu khong se deadlock feedback loop)"
        assert len(result["_features"]) == len(ml_mod.FEATURE_NAMES), \
            f"Feature phai co {len(ml_mod.FEATURE_NAMES)} chieu"
        print(f"  OK: _features co {len(result['_features'])} chieu ngay ca khi chua train")

        # df khong du du lieu -> _features = None (khong thu thap sample rac)
        short_df = _make_df(5)
        assert booster.predict(short_df, {"direction": "LONG"}).get("_features") is None
        print("  OK: df khong du 20 dong -> _features=None (khong thu thap sample loi)")
    finally:
        _restore_ml_files(originals)
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_ml_feedback_loop_trains_automatically():
    """
    Sau fix: add_training_sample() duoc goi lai (trade_engine) va tu dong train()
    khi du MIN_SAMPLES + RETRAIN_THRESHOLD -> model tu hoc.
    """
    print("=== [6] ML BOOSTER: feedback loop tu dong train khi du sample ===")
    tmp_dir = tempfile.mkdtemp(prefix="cbs_ml_")
    originals = _patch_ml_files(tmp_dir)
    try:
        reset_booster()
        booster = AdaptiveSignalBooster()
        # Ha nguong de test nhanh
        booster.MIN_SAMPLES = 12
        booster.RETRAIN_THRESHOLD = 6
        booster.is_trained = False
        booster.model = None
        booster.training_data = []
        booster.last_train_count = 0

        features = booster.extract_features(_make_df(), {"direction": "LONG"})
        assert features is not None, "extract_features phai tra ve vector"
        assert len(features) == len(ml_mod.FEATURE_NAMES)

        for i in range(12):
            booster.add_training_sample(features, label=i % 2, pnl=1.0, trade_key=f"T{i}")

        assert len(booster.training_data) == 12, "Phai luu du 12 sample"
        assert booster.is_trained, "Sau khi du MIN_SAMPLES phai tu dong train"
        assert os.path.exists(ml_mod.ML_TRAINING_FILE), "Training data phai duoc ghi ra file"
        assert os.path.exists(ml_mod.ML_MODEL_FILE), "Model phai duoc ghi ra file"
        print(f"  OK: tu dong train | is_trained={booster.is_trained} | "
              f"accuracy={booster.model_accuracy:.2f} | samples={len(booster.training_data)}")

        result = booster.predict(_make_df(), {"direction": "LONG", "bull_score": 5, "bear_score": 5})
        assert result["is_trained"] is True
        assert result.get("_features") is not None, "Sau khi train van phai thu thap feature"
        print(f"  OK: predict sau train | confidence={result['confidence']} "
              f"| rating_adjust={result['rating_adjust']:+d}")

        # Singleton: moi noi dung chung 1 instance -> status khong bi stale
        assert get_booster() is get_booster(), "get_booster phai tra ve singleton"
        print("  OK: get_booster() la singleton")
    finally:
        _restore_ml_files(originals)
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ==========================================
#  [7] TRADE ENGINE - AI DETAILS PERSIST
# ==========================================

def test_open_position_persists_ai_details():
    """
    C3b: open_position() phai luu 'ai_details' (kem '_features') vao position,
    neu khong thi `pos.get("ai_details", {})` luon rong -> ML khong bao gio co sample.
    Dung file tam + sqlite_db=None de KHONG ghi vao data/ that.
    """
    print("=== [7] TRADE ENGINE: open_position luu ai_details (C3b) ===")
    import execution.trade_engine as te_mod

    tmp_dir = tempfile.mkdtemp(prefix="cbs_te_")
    old_data_file = te_mod.TradeEngine.DATA_FILE
    old_sqlite = te_mod.sqlite_db
    te_mod.TradeEngine.DATA_FILE = os.path.join(tmp_dir, "paper_trading.json")
    te_mod.sqlite_db = None  # khong ghi vao DB that
    try:
        te = te_mod.TradeEngine()
        te.balance = 10000.0
        te.positions = {}
        te.auto_trade_enabled = True
        te.daily_date = te._today()
        te.daily_realized_pnl = 0.0
        te.daily_start_balance = te.balance

        ai_details = {
            "ml": {"_features": [0.1] * len(ml_mod.FEATURE_NAMES), "confidence": 0.7},
            "regime": {"regime": "TRENDING", "rating_adj": 1},
            "total_adjust": 1,
        }
        pos = te.open_position({
            "key": "BTC_1h",
            "coin": "BTC",
            "type": "FUTURES",
            "direction": "LONG",
            "entry": 100000.0,
            "sl": 98000.0,
            "tp1": 102000.0,
            "tp2": 104000.0,
            "tp3": 108000.0,
            "leverage": 5,
            "rating": 4,
            "tf": "1h",
            "ai_details": ai_details,
        })
        assert pos is not None, "Phai mo duoc position (auto_trade_enabled=True)"

        saved = te.positions.get("BTC_1h")
        assert saved is not None, "Position phai nam trong te.positions"
        assert saved.get("ai_details") == ai_details, \
            "ai_details phai duoc luu nguyen ven vao position"
        assert saved["ai_details"]["ml"]["_features"] is not None, \
            "Position phai giu '_features' de ML training feedback loop"
        print(f"  OK: ai_details duoc luu | ml._features="
              f"{len(saved['ai_details']['ml']['_features'])} chieu")
    finally:
        te_mod.TradeEngine.DATA_FILE = old_data_file
        te_mod.sqlite_db = old_sqlite
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ==========================================
#  [8] WHALE TRACKER - M1
# ==========================================

async def test_whale_public_endpoints_only():
    """
    M1: endpoint liquidation cua Binance da hong
    (/fapi/v1/allForceOrders -> 404, /fapi/v1/forceOrders -> 401 USER_DATA)
    -> khong duoc goi trong compute_whale_bias (gay spam log ma vo dung).
    Whale-alert.io chi duoc bat khi co Config.WHALE_ALERT_API_KEY.
    """
    print("=== [8] WHALE TRACKER: chi dung endpoint public (M1) ===")
    import ast
    from analytics import whale_tracker as wt_mod

    src_path = BACKEND_DIR / "analytics" / "whale_tracker.py"
    tree = ast.parse(src_path.read_text(encoding="utf-8"))

    targets = [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "compute_whale_bias"]
    assert targets, "Khong tim thay compute_whale_bias"
    fn = targets[0]

    called = {n.func.attr for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "analyze_liquidations" not in called, \
        "compute_whale_bias khong duoc goi analyze_liquidations (endpoint da hong)"

    str_lits = [n.value for n in ast.walk(fn)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    broken = [s for s in str_lits if "forceOrders" in s]
    assert not broken, f"Van con goi endpoint liquidation hong: {broken}"

    print(f"  OK: compute_whale_bias khong goi analyze_liquidations "
          f"({len(called)} method duoc goi trong ham)")

    tracker = WhaleTracker()
    result = await tracker.analyze_external_whale_flows("BTCUSDT")
    assert result["direction"] in ("LONG", "SHORT", "NEUTRAL")
    assert result["weight"] >= 0
    if not tracker._whale_alert_enabled:
        assert result["signal"] is None, "Khong co API key thi phai tra ve NEUTRAL"
        print("  OK: whale-alert OFF (thieu WHALE_ALERT_API_KEY) -> NEUTRAL, khong goi API")
    else:
        print("  OK: whale-alert ON -> da goi API whale-alert.io")
    await tracker.close()


# ==========================================
#  [10] ML FEEDBACK LOOP - MAT XICH CUOI
# ==========================================

def test_ml_features_flow_through_ai_details():
    """
    Mat xich cuoi cua feedback loop: _apply_ai_adjustments() build ai_details["ml"]
    bang dict key co dinh. Neu khong copy '_features' thi trade_engine khong bao gio
    thu duoc sample du predict() da tra ve '_features' (loop dut giua chung).
    Test nay mo phong tron ven: predict -> ai_details -> add sample -> auto train.
    """
    print("=== [10] ML FEEDBACK LOOP: _features phai di het vao ai_details ===")
    tmp_dir = tempfile.mkdtemp(prefix="cbs_ml_")
    originals = _patch_ml_files(tmp_dir)
    try:
        reset_booster()
        from analytics.signal_scanner import SignalScanner
        sc = SignalScanner(symbols=["BTC/USDT"], timeframes=["1h"], interval_seconds=300)
        booster = sc.ml_booster
        booster.is_trained = False
        booster.model = None
        booster.training_data = []
        booster.MIN_SAMPLES = 12
        booster.RETRAIN_THRESHOLD = 6

        rating, details = sc._apply_ai_adjustments(
            3, {"direction": "LONG", "bull_score": 7, "bear_score": 2},
            _make_df(), "1h", "NEUTRAL", symbol="BTC/USDT"
        )
        ml = details.get("ml", {})
        assert ml.get("_features") is not None, \
            "ai_details['ml'] phai giu '_features' (neu khong feedback loop ML bi dut)"
        assert len(ml["_features"]) == len(ml_mod.FEATURE_NAMES), \
            f"_features phai co {len(ml_mod.FEATURE_NAMES)} chieu"

        # Mo phong luong trade_engine: them sample -> tu dong train khi du nguong
        features = np.array(ml["_features"])
        for i in range(booster.MIN_SAMPLES):
            booster.add_training_sample(features, label=i % 2, pnl=1.0, trade_key=f"K{i}")
        assert len(booster.training_data) == booster.MIN_SAMPLES
        assert booster.is_trained, "Feedback loop phai tu dong train khi du sample"
        assert os.path.exists(ml_mod.ML_TRAINING_FILE), "Sample phai duoc ghi ra file"

        # Predict sau khi train van phai tra _features (tiep tuc hoc)
        result = booster.predict(_make_df(), {"direction": "LONG"})
        assert result.get("_features") is not None
        print(f"  OK: _features {len(ml['_features'])} chieu -> {len(booster.training_data)} sample "
              f"-> is_trained={booster.is_trained} -> loop tiep tuc")
    finally:
        _restore_ml_files(originals)
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ==========================================
#  [11] WHALE - OI + PRICE SIDEWAY (M6)
# ==========================================

async def test_oi_price_context_logic():
    """
    M6: OI surge CHI dung khi gia sideway; OI drop kem boi canh gia de biet
    trend con song khong. Monkeypatch du lieu -> deterministic, khong can mang.
    """
    print("=== [11] WHALE: OI surge/drop ket hop boi canh gia (M6) ===")
    t = WhaleTracker()

    # --- OI tang dan (surge 4h: +14%) + gia sideway -> OI_SURGE ---
    oi_up = [{"sumOpenInterest": str(100 + i * 0.3)} for i in range(48)]

    async def oi_up_fn(symbol, period="5m", limit=48):
        return oi_up

    async def px_sideway(symbol, hours=4):
        return {"range_pct": 1.0, "trend_pct": 0.2, "close": 100.0}

    t.get_oi_history = oi_up_fn
    t._fetch_price_context = px_sideway
    r = await t.analyze_open_interest("BTCUSDT")
    assert r["signal"] == "OI_SURGE", f"Ky vong OI_SURGE, nhan {r['signal']} ({r['detail']})"
    assert "sideway" in r["detail"]
    print(f"  OK: OI surge + sideway -> OI_SURGE | {r['detail'][:70]}")

    # --- OI surge nhung gia da bien dong manh -> khong con pre-breakout ---
    async def px_trending(symbol, hours=4):
        return {"range_pct": 8.0, "trend_pct": 6.0, "close": 100.0}

    t._fetch_price_context = px_trending
    r2 = await t.analyze_open_interest("BTCUSDT")
    assert r2["signal"] is None, "Gia da bien dong manh thi khong duoc bao pre-breakout"
    assert "pre-breakout" in r2["detail"]
    print(f"  OK: OI surge + gia da chay -> khong bao | {r2['detail'][:70]}")

    # --- OI drop manh (-13%/1h) + gia giam -> OI_DUMP trend het luc ---
    oi_down = [{"sumOpenInterest": str(120 - i * 1.0)} for i in range(48)]

    async def oi_down_fn(symbol, period="5m", limit=48):
        return oi_down

    async def px_down(symbol, hours=4):
        return {"range_pct": 2.0, "trend_pct": -1.5, "close": 100.0}

    t.get_oi_history = oi_down_fn
    t._fetch_price_context = px_down
    r3 = await t.analyze_open_interest("BTCUSDT")
    assert r3["signal"] == "OI_DUMP" and "het luc" in r3["detail"]
    print(f"  OK: OI drop + gia giam -> trend het luc")

    # --- OI drop nhung gia tang -> short squeeze (trend con song) ---
    async def px_up(symbol, hours=4):
        return {"range_pct": 2.0, "trend_pct": 1.0, "close": 100.0}

    t._fetch_price_context = px_up
    r4 = await t.analyze_open_interest("BTCUSDT")
    assert r4["signal"] == "OI_DUMP" and "Short squeeze" in r4["detail"]
    print(f"  OK: OI drop + gia tang -> Short squeeze (trend con song)")
    await t.close()


# ==========================================
#  [12] NEWS INTEL - KHONG DOUBLE PENALTY (M7)
# ==========================================

def test_event_adjustments_no_double_penalty():
    """
    M7: CRITICAL event truoc day bi tru 2 sao VA pause auto-trade (double penalty).
    Sau fix: CRITICAL = pause auto-trade (rating giu nguyen),
    HIGH = tru 1 sao (khong pause).
    """
    print("=== [12] NEWS INTELLIGENCE: CRITICAL khong double penalty (M7) ===")
    intel = NewsIntelligence()

    critical = [{
        "title": "FOMC Meeting", "type": "FOMC", "impact": "CRITICAL",
        "hours_until": 5, "is_past": False, "info": {},
    }]
    adj = intel.get_event_adjustments(critical)
    assert adj["has_critical_event"] is True
    assert adj["should_pause_auto_trade"] is True, "CRITICAL phai pause auto-trade"
    assert adj["rating_adjust"] == 0, \
        f"CRITICAL khong duoc tru sao nua (pause la co che duy nhat), nhan {adj['rating_adjust']}"
    print(f"  OK: CRITICAL -> pause auto-trade, rating giu nguyen (adj={adj['rating_adjust']})")

    high = [dict(critical[0], impact="HIGH", hours_until=10)]
    adj2 = intel.get_event_adjustments(high)
    assert adj2["should_pause_auto_trade"] is False, "HIGH khong duoc pause"
    assert adj2["rating_adjust"] == -1, f"HIGH van giu co che tru sao, nhan {adj2['rating_adjust']}"
    print(f"  OK: HIGH -> tru 1 sao, khong pause (adj={adj2['rating_adjust']})")

SYNC_TESTS = [
    test_scanner_no_undefined_global_names,
    test_parse_event_dt,
    test_llm_client_wiring,
    test_ml_features_collected_before_training,
    test_ml_feedback_loop_trains_automatically,
    test_ml_features_flow_through_ai_details,
    test_open_position_persists_ai_details,
    test_event_adjustments_no_double_penalty,
]

ASYNC_TESTS = [
    test_news_bias_contract,
    test_event_impact_db_records_outcome,
    test_whale_public_endpoints_only,
    test_oi_price_context_logic,
]


async def run_all():
    total = len(SYNC_TESTS) + len(ASYNC_TESTS)
    print("=" * 60)
    print(f"  AI INTELLIGENCE TEST SUITE ({total} tests)")
    print("=" * 60)

    failed = []
    for fn in SYNC_TESTS:
        try:
            fn()
        except Exception as e:
            print(f"  FAIL {fn.__name__}: {type(e).__name__}: {e}")
            failed.append(fn.__name__)
        print("-" * 60)

    for fn in ASYNC_TESTS:
        try:
            await fn()
        except Exception as e:
            print(f"  FAIL {fn.__name__}: {type(e).__name__}: {e}")
            failed.append(fn.__name__)
        print("-" * 60)

    print("=" * 60)
    if failed:
        print(f"  KET QUA: {len(failed)}/{total} TEST FAIL: {failed}")
        print("=" * 60)
        raise SystemExit(1)
    print(f"  KET QUA: TAT CA {total} TEST PASSED")
    print("=" * 60)


if __name__ == '__main__':
    asyncio.run(run_all())
