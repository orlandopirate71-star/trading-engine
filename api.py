"""
FastAPI backend for the trading dashboard.
"""
import os
import json
import requests
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
import os
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import asyncio

from connections import get_db_connection, redis_client
from trading_engine import get_engine
from models import TradeStatus, TradeDirection
from feed_symbols import get_feed_info, get_active_symbols
from trade_manager import get_trade_manager
from oanda_broker import OandaBroker
from candle_aggregator import get_candle_aggregator, Timeframe


app = FastAPI(title="Trading Station API", version="1.0.0")

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve screenshots
screenshots_dir = Path("screenshots")
screenshots_dir.mkdir(exist_ok=True)
app.mount("/screenshots", StaticFiles(directory=str(screenshots_dir)), name="screenshots")


# === Pydantic Models ===

class StrategyToggle(BaseModel):
    enabled: bool

class AutoTradeToggle(BaseModel):
    enabled: bool

class ApprovalToggle(BaseModel):
    required: bool

class ManualTrade(BaseModel):
    symbol: str
    direction: str
    quantity: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

class MoveStopRequest(BaseModel):
    new_stop: float

class MoveTakeProfitRequest(BaseModel):
    new_tp: float

class TrailingStopRequest(BaseModel):
    trail_pips: float
    activation_pips: float = 0

class TrailingStopDollarRequest(BaseModel):
    trigger_profit: float  # Profit ($) that triggers the trailing stop
    lock_profit: float     # Profit ($) to lock in when triggered

class CloseTradeRequest(BaseModel):
    reason: str = "Manual close"

class CloseAllRequest(BaseModel):
    symbol: Optional[str] = None
    reason: str = "Close all"

class StrategySettingsRequest(BaseModel):
    max_positions: Optional[int] = None
    max_positions_per_symbol: Optional[int] = None
    pip_multipliers: Optional[dict] = None
    trailing_stop_trigger: Optional[float] = None
    trailing_stop_lock: Optional[float] = None

class OandaOrderRequest(BaseModel):
    symbol: str
    side: str  # BUY or SELL
    units: int

class VolatilityConfigRequest(BaseModel):
    low_threshold: Optional[float] = None  # Global low threshold (ATR%)
    high_threshold: Optional[float] = None  # Global high threshold (ATR%)
    symbol_thresholds: Optional[dict] = None  # Per-symbol: {"EURUSD": {"low": 0.01, "high": 0.02}}
    enabled: Optional[bool] = None
    refresh_interval: Optional[int] = None  # seconds between volatility checks

class VolatilityOverrideRequest(BaseModel):
    enabled: bool  # Manual override for trading allowed/blocked
    take_profit: Optional[float] = None

class BrokerModeRequest(BaseModel):
    mode: str  # "paper" or "oanda"


class ConfidenceThresholdRequest(BaseModel):
    threshold: float


class SymbolUnitsRequest(BaseModel):
    symbol: str
    units: Optional[float] = None  # None means use default (no trade if 0)


# === Symbol Units ===

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Subscribe to Redis for price updates
        pubsub = redis_client.pubsub()
        pubsub.subscribe("ticks")
        
        while True:
            # Check for price updates
            message = pubsub.get_message(timeout=0.1)
            if message and message["type"] == "message":
                data = message["data"]
                # Handle both JSON format and legacy format
                if isinstance(data, str) and data.startswith("{"):
                    tick = json.loads(data)
                    await websocket.send_json({
                        "type": "tick",
                        "symbol": tick.get("symbol", "UNKNOWN"),
                        "price": float(tick.get("price", 0)),
                        "bid": tick.get("bid"),
                        "ask": tick.get("ask"),
                        "source": tick.get("source", ""),
                        "timestamp": tick.get("timestamp", datetime.utcnow().isoformat())
                    })
                else:
                    # Legacy format - just a price
                    await websocket.send_json({
                        "type": "tick",
                        "symbol": "BTCUSDT",
                        "price": float(data),
                        "timestamp": datetime.utcnow().isoformat()
                    })
            
            # Check for client messages
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                # Handle client commands if needed
            except asyncio.TimeoutError:
                pass
            
            await asyncio.sleep(0.05)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    finally:
        pubsub.unsubscribe()


@app.get("/api/prices")
def get_all_prices():
    """Get all latest prices from all feeds, filtered to feed_config symbols only."""
    active_symbols = set(get_active_symbols())
    prices = redis_client.hgetall("latest_prices")
    return {symbol: float(price) for symbol, price in prices.items() if symbol in active_symbols}


@app.get("/api/feeds")
def get_feeds():
    """Get feed configuration and active symbols."""
    return get_feed_info()


@app.get("/api/symbols")
def get_symbols():
    """Get list of active symbols from enabled feeds."""
    return {"symbols": get_active_symbols()}


# === Engine Status ===

@app.get("/api/status")
def get_status():
    """Get trading engine status."""
    engine = get_engine()
    return engine.get_status()


@app.post("/api/engine/start")
def start_engine():
    """Start the trading engine."""
    engine = get_engine()
    if not engine.running:
        engine.start()
    return {"status": "started"}


@app.post("/api/engine/stop")
def stop_engine():
    """Stop the trading engine."""
    engine = get_engine()
    if engine.running:
        engine.stop()
    return {"status": "stopped"}


@app.get("/api/system/status")
def get_system_status():
    """Get status of all system components."""
    engine = get_engine()

    # Check Redis
    redis_ok = False
    try:
        redis_client.ping()
        redis_ok = True
    except:
        pass

    # Check database
    db_ok = False
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        db_ok = True
    except:
        pass

    # Check if feed is publishing ticks
    feed_ok = False
    try:
        latest = redis_client.hget("latest_prices", "EURUSD")
        feed_ok = latest is not None
    except:
        pass

    # Check if engine is processing
    engine_ok = engine.running

    # Check OANDA
    oanda_ok = engine.oanda_broker is not None

    return {
        "redis": redis_ok,
        "database": db_ok,
        "feed": feed_ok,
        "engine": engine_ok,
        "oanda": oanda_ok,
        "all_ok": redis_ok and db_ok and feed_ok and engine_ok
    }

@app.get("/api/broker")
def get_broker_mode():
    """Get current broker mode."""
    engine = get_engine()
    return {
        "mode": engine.broker_mode,
        "oanda_available": engine.oanda_broker is not None
    }


@app.post("/api/broker")
def set_broker_mode(request: BrokerModeRequest):
    """Set broker mode: 'paper' or 'oanda'."""
    engine = get_engine()
    try:
        engine.set_broker_mode(request.mode)
        return {
            "success": True,
            "mode": engine.broker_mode
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


SYMBOL_UNITS_KEY = "symbol_units"  # Redis hash: symbol -> units


@app.get("/api/symbol-units")
def get_symbol_units():
    """Get all symbol units settings."""
    units = redis_client.hgetall(SYMBOL_UNITS_KEY) or {}
    # Convert values to float, None for empty/zero
    result = {}
    for symbol, val in units.items():
        try:
            fval = float(val)
            result[symbol] = fval if fval > 0 else None
        except (ValueError, TypeError):
            result[symbol] = None
    return result


@app.post("/api/symbol-units")
def set_symbol_units(request: SymbolUnitsRequest):
    """Set units for a symbol. If units is None or 0, symbol will not trade."""
    if request.units is None or request.units <= 0:
        redis_client.hdel(SYMBOL_UNITS_KEY, request.symbol)
    else:
        redis_client.hset(SYMBOL_UNITS_KEY, request.symbol, str(request.units))
    return {"symbol": request.symbol, "units": request.units}


def get_symbol_units_map() -> Dict[str, float]:
    """Get symbol units as a dict for use by trading engine."""
    units = redis_client.hgetall(SYMBOL_UNITS_KEY) or {}
    result = {}
    for symbol, val in units.items():
        try:
            fval = float(val)
            if fval > 0:
                result[symbol] = fval
        except (ValueError, TypeError):
            pass
    return result


# === AI Activity Log ===

AI_ACTIVITY_KEY = "ai_activity_log"  # Redis list of AI activity events
MAX_ACTIVITY_LOG = 500  # Keep last 500 events


def log_ai_activity(event_type: str, data: dict):
    """Log an AI activity event to Redis."""
    event = {
        "type": event_type,
        "timestamp": datetime.utcnow().isoformat(),
        "data": data
    }
    redis_client.lpush(AI_ACTIVITY_KEY, json.dumps(event))
    redis_client.ltrim(AI_ACTIVITY_KEY, 0, MAX_ACTIVITY_LOG - 1)


@app.get("/api/ai-activity")
def get_ai_activity(limit: int = Query(default=50, le=100)):
    """Get recent AI activity logs."""
    events = redis_client.lrange(AI_ACTIVITY_KEY, 0, limit - 1)
    result = []
    for event in events:
        try:
            result.append(json.loads(event))
        except json.JSONDecodeError:
            pass
    return {"events": result}


@app.delete("/api/ai-activity")
def clear_ai_activity():
    """Clear all AI activity logs."""
    redis_client.delete(AI_ACTIVITY_KEY)
    return {"status": "ok", "message": "AI activity log cleared"}


@app.delete("/api/ai-activity/old")
def clear_old_ai_activity(max_age_hours: int = Query(default=24, ge=1, le=720)):
    """Clear AI activity logs older than specified hours."""
    cutoff = datetime.utcnow().timestamp() - (max_age_hours * 3600)
    events = redis_client.lrange(AI_ACTIVITY_KEY, 0, -1)
    deleted = 0
    for event in events:
        try:
            parsed = json.loads(event)
            event_time = datetime.fromisoformat(parsed.get("timestamp", "2000-01-01"))
            if event_time.timestamp() < cutoff:
                redis_client.lrem(AI_ACTIVITY_KEY, 1, event)
                deleted += 1
        except:
            pass
    return {"status": "ok", "deleted": deleted, "older_than_hours": max_age_hours}


@app.post("/api/candles/cleanup")
def cleanup_old_candles(days: int = Query(default=14, ge=1, le=60)):
    """Delete candles older than specified days (default 14)."""
    from candle_store import get_candle_store
    store = get_candle_store()
    deleted = store.cleanup_old_candles(days)
    return {"status": "ok", "deleted": deleted, "older_than_days": days}


@app.get("/api/candles/count")
def get_candle_count():
    """Get total candle count and date range in database."""
    from candle_store import get_candle_store
    store = get_candle_store()
    date_range = store.get_date_range()
    return {
        "count": date_range["total_candles"],
        "oldest": date_range["oldest"],
        "newest": date_range["newest"],
        "retention_days": 14
    }


# === Volatility Switch ===

# Default per-symbol thresholds (M15 ATR%)
DEFAULT_VOLATILITY_THRESHOLDS = {
    "AUDUSD": {"low": 0.030, "high": 0.042},
    "EURGBP": {"low": 0.017, "high": 0.023},
    "EURJPY": {"low": 0.020, "high": 0.034},
    "EURUSD": {"low": 0.014, "high": 0.026},
    "GBPJPY": {"low": 0.024, "high": 0.038},
    "GBPUSD": {"low": 0.022, "high": 0.033},
    "NZDUSD": {"low": 0.030, "high": 0.038},
    "USDCAD": {"low": 0.012, "high": 0.019},
    "USDCHF": {"low": 0.022, "high": 0.035},
    "USDJPY": {"low": 0.015, "high": 0.039},
    "XAGUSD": {"low": 0.107, "high": 0.305},
    "XAUUSD": {"low": 0.082, "high": 0.259},
}


def calculate_atr_percent(symbol: str, period: int = 14, timeframe: str = "M15") -> Optional[float]:
    """
    Calculate ATR as a percentage of current price.
    Returns ATR% which allows comparison across different price levels.
    Uses M15 by default for better volatility representation.
    """
    try:
        from candle_store import get_candle_store
        store = get_candle_store()
        candles = store.get_recent_candles(symbol, timeframe, count=period + 2)
        if not candles or len(candles) < period + 1:
            return None

        # Calculate True Range
        tr_values = []
        for i in range(1, len(candles)):
            high = candles[i]['high']
            low = candles[i]['low']
            prev_close = candles[i-1]['close']

            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            tr_values.append(tr)

        if len(tr_values) < period:
            return None

        # ATR = smoothed average of TR (simple average for now)
        atr = sum(tr_values[-period:]) / period
        current_price = candles[-1]['close']

        if current_price == 0:
            return None

        # ATR as percentage of price
        return (atr / current_price) * 100

    except Exception as e:
        print(f"[Volatility] Error calculating ATR for {symbol}: {e}")
        return None


def get_volatility_thresholds(symbol: str) -> dict:
    """
    Get volatility thresholds for a specific symbol.
    Tries Redis first, then falls back to defaults.
    """
    # Check Redis for custom threshold
    redis_key = f"volatility_threshold:{symbol}"
    saved = redis_client.hgetall(redis_key)

    # Check for global defaults in Redis
    global_low = redis_client.get("volatility_low_threshold")
    global_high = redis_client.get("volatility_high_threshold")

    # Use default thresholds for this symbol
    default = DEFAULT_VOLATILITY_THRESHOLDS.get(symbol, {"low": 0.02, "high": 0.05})

    return {
        "low": float(saved.get("low", global_low)) if global_low else default["low"],
        "high": float(saved.get("high", global_high)) if global_high else default["high"]
    }


def get_symbol_volatility(symbol: str) -> dict:
    """
    Get volatility status for a specific symbol.
    """
    atr_pct = calculate_atr_percent(symbol, period=14)
    thresholds = get_volatility_thresholds(symbol)

    if atr_pct is None:
        return {
            "symbol": symbol,
            "atr_percent": None,
            "status": "unknown",
            "trading_allowed": True,  # Default to allowing if we can't calculate
            "thresholds": thresholds,
            "error": "Not enough candle data"
        }

    if atr_pct < thresholds["low"]:
        status = "low"
        allowed = False
    elif atr_pct < thresholds["high"]:
        status = "caution"
        allowed = True
    else:
        status = "high"
        allowed = True

    # Check for manual override
    override = redis_client.get("volatility_override")
    if override == "disabled":
        allowed = False
        status = "manual_off"
    elif override == "enabled":
        allowed = True
        status = "manual_on"

    return {
        "symbol": symbol,
        "atr_percent": round(atr_pct, 4),
        "status": status,
        "trading_allowed": allowed,
        "thresholds": thresholds,
        "last_updated": datetime.utcnow().isoformat()
    }


def get_market_volatility() -> dict:
    """
    Calculate aggregate market volatility across all active symbols.
    Uses per-symbol thresholds for more accurate trading decisions.
    Returns dict with current volatility status and per-symbol data.
    """
    from feed_symbols import get_active_symbols

    active_symbols = get_active_symbols()
    symbol_results = {}
    allowed_count = 0
    blocked_count = 0

    for symbol in active_symbols:
        result = get_symbol_volatility(symbol)
        symbol_results[symbol] = result
        if result["atr_percent"] is not None:
            if result["trading_allowed"]:
                allowed_count += 1
            else:
                blocked_count += 1

    # Overall status
    total_tracked = allowed_count + blocked_count
    if total_tracked == 0:
        overall_status = "unknown"
        trading_allowed = True
    elif blocked_count == total_tracked:
        overall_status = "all_low"
        trading_allowed = False
    elif blocked_count > allowed_count:
        overall_status = "mostly_low"
        trading_allowed = False
    else:
        overall_status = "sufficient"
        trading_allowed = True

    # Check for manual override
    override = redis_client.get("volatility_override")
    if override in ("enabled", "disabled"):
        trading_allowed = override == "enabled"
        overall_status = f"manual_{'on' if override == 'enabled' else 'off'}"

    return {
        "status": overall_status,
        "trading_allowed": trading_allowed,
        "symbols_allowed": allowed_count,
        "symbols_blocked": blocked_count,
        "total_symbols": len(active_symbols),
        "symbols": symbol_results,
        "volatility_enabled": redis_client.get("volatility_enabled") != "false",
        "manual_override": override in ("enabled", "disabled"),
        "last_updated": datetime.utcnow().isoformat()
    }


def _get_volatility_thresholds() -> dict:
    """Get global volatility thresholds (fallback)."""
    return {
        "low_threshold": float(redis_client.get("volatility_low_threshold") or 0.04),
        "high_threshold": float(redis_client.get("volatility_high_threshold") or 0.08),
        "enabled": redis_client.get("volatility_enabled") != "false"
    }


@app.get("/api/volatility")
def get_volatility():
    """
    Get current market volatility status.
    Used by dashboard to display volatility gauge and trading status.
    """
    return get_market_volatility()


@app.get("/api/volatility/config")
def get_volatility_config():
    """Get volatility configuration (thresholds, enabled state)."""
    thresholds = _get_volatility_thresholds()
    override = redis_client.get("volatility_override")
    return {
        "low_threshold": thresholds["low_threshold"],
        "high_threshold": thresholds["high_threshold"],
        "enabled": thresholds["enabled"],
        "manual_override": override in ("enabled", "disabled"),
        "override_active": override is not None
    }


@app.post("/api/volatility/config")
def set_volatility_config(request: VolatilityConfigRequest):
    """Configure volatility thresholds and enabled state."""
    if request.low_threshold is not None:
        if not 0 <= request.low_threshold <= 10:
            raise HTTPException(status_code=400, detail="low_threshold must be 0-10")
        redis_client.set("volatility_low_threshold", str(request.low_threshold))

    if request.high_threshold is not None:
        if not 0 <= request.high_threshold <= 10:
            raise HTTPException(status_code=400, detail="high_threshold must be 0-10")
        redis_client.set("volatility_high_threshold", str(request.high_threshold))

    # Handle per-symbol thresholds
    if request.symbol_thresholds is not None:
        for symbol, thresholds in request.symbol_thresholds.items():
            if isinstance(thresholds, dict):
                low = thresholds.get("low", thresholds.get("low_threshold"))
                high = thresholds.get("high", thresholds.get("high_threshold"))
                redis_key = f"volatility_threshold:{symbol}"
                if low is not None:
                    redis_client.hset(redis_key, "low", str(low))
                if high is not None:
                    redis_client.hset(redis_key, "high", str(high))

    if request.enabled is not None:
        redis_client.set("volatility_enabled", "true" if request.enabled else "false")

    if request.refresh_interval is not None:
        if not 10 <= request.refresh_interval <= 3600:
            raise HTTPException(status_code=400, detail="refresh_interval must be 10-3600 seconds")
        redis_client.set("volatility_refresh_interval", str(request.refresh_interval))

    # Clear any manual override when reconfiguring
    redis_client.delete("volatility_override")

    return get_volatility_config()


@app.post("/api/volatility/override")
def set_volatility_override(request: VolatilityOverrideRequest):
    """
    Manually override volatility trading state.
    When override is active, it takes precedence over calculated volatility.
    """
    if request.enabled:
        redis_client.set("volatility_override", "enabled")
    else:
        redis_client.set("volatility_override", "disabled")

    return get_market_volatility()


@app.post("/api/volatility/clear-override")
def clear_volatility_override():
    """Clear manual volatility override, return to calculated state."""
    redis_client.delete("volatility_override")
    return get_market_volatility()


@app.get("/api/volatility/check")
def check_trading_allowed():
    """
    Quick check if trading is currently allowed based on volatility.
    Used by trading engine before processing signals.
    """
    volatility = get_market_volatility()
    return {
        "allowed": volatility["trading_allowed"],
        "status": volatility["status"],
        "symbols_allowed": volatility["symbols_allowed"],
        "symbols_blocked": volatility["symbols_blocked"],
        "total_symbols": volatility["total_symbols"]
    }


@app.get("/api/volatility/symbol/{symbol}")
def get_symbol_volatility_status(symbol: str):
    """
    Get volatility status for a specific symbol.
    Used to determine if a trade on this symbol should be allowed.
    """
    result = get_symbol_volatility(symbol.upper())
    return result


@app.get("/api/volatility/symbol/{symbol}/check")
def check_symbol_trading_allowed(symbol: str):
    """
    Quick check if trading is allowed for a specific symbol.
    """
    result = get_symbol_volatility(symbol.upper())
    return {
        "symbol": symbol.upper(),
        "allowed": result["trading_allowed"],
        "status": result["status"],
        "atr_percent": result["atr_percent"]
    }


@app.post("/api/auto-trade")
def set_auto_trade(toggle: AutoTradeToggle):
    """Enable/disable auto trading."""
    engine = get_engine()
    engine.set_auto_trade(toggle.enabled)
    return {"auto_trade": toggle.enabled}


@app.post("/api/require-approval")
def set_require_approval(toggle: ApprovalToggle):
    """Enable/disable AI approval requirement."""
    engine = get_engine()
    engine.set_require_approval(toggle.required)
    return {"require_approval": toggle.required}


@app.get("/api/validator-mode")
def get_validator_mode():
    """Get current validator mode (ai_validator)."""
    return {"mode": "ai_validator"}


@app.get("/api/ai-confidence")
def get_ai_confidence_threshold():
    """Get current AI confidence threshold for trade approval."""
    # First try to load from Redis, then fallback to engine
    saved_threshold = redis_client.get("ai_confidence_threshold")
    if saved_threshold:
        try:
            return {"confidence_threshold": float(saved_threshold)}
        except (ValueError, TypeError):
            pass

    engine = get_engine()
    if engine.validator:
        return {"confidence_threshold": engine.validator.get_confidence_threshold()}
    return {"confidence_threshold": 0.75}


@app.post("/api/ai-confidence")
def set_ai_confidence_threshold(request: ConfidenceThresholdRequest):
    """Set AI confidence threshold for trade approval (0.0-1.0)."""
    engine = get_engine()
    if not engine.validator:
        raise HTTPException(status_code=500, detail="AI validator not initialized")

    # Validate range
    if request.threshold < 0.0 or request.threshold > 1.0:
        raise HTTPException(status_code=400, detail="Threshold must be between 0.0 and 1.0")

    engine.validator.set_confidence_threshold(request.threshold)
    # Persist to Redis
    redis_client.set("ai_confidence_threshold", str(request.threshold))
    return {"confidence_threshold": request.threshold}


@app.get("/api/ai-monitor-confidence")
def get_ai_monitor_confidence():
    """Get current AI confidence threshold for position monitoring."""
    # First try to load from Redis, then fallback to engine
    saved_threshold = redis_client.get("ai_monitor_confidence_threshold")
    if saved_threshold:
        try:
            return {"monitor_confidence": float(saved_threshold)}
        except (ValueError, TypeError):
            pass

    engine = get_engine()
    if engine.validator:
        return {"monitor_confidence": engine.validator.get_monitor_confidence_threshold()}
    return {"monitor_confidence": 0.6}


@app.post("/api/ai-monitor-confidence")
def set_ai_monitor_confidence(request: ConfidenceThresholdRequest):
    """Set AI confidence threshold for position monitoring (0.0-1.0). Lower = more active."""
    engine = get_engine()
    if not engine.validator:
        raise HTTPException(status_code=500, detail="AI validator not initialized")

    if request.threshold < 0.0 or request.threshold > 1.0:
        raise HTTPException(status_code=400, detail="Threshold must be between 0.0 and 1.0")

    engine.validator.set_monitor_confidence_threshold(request.threshold)
    # Persist to Redis
    redis_client.set("ai_monitor_confidence_threshold", str(request.threshold))
    return {"monitor_confidence": request.threshold}


# === Ollama Mode Control ===

@app.get("/api/ollama-mode")
def get_ollama_mode():
    """Get current Ollama mode (auto, primary, backup) and status."""
    # Return persisted mode from Redis first
    saved_mode = redis_client.get("ollama_mode")
    mode = saved_mode.decode() if isinstance(saved_mode, bytes) else (saved_mode or "auto")
    
    # Try to get live status from client
    using_backup = False
    try:
        from ai_trading.ai_client import get_ai_client
        client = get_ai_client()
        status = client.get_current_ollama_status()
        using_backup = status.get("using_backup", False)
        # Use runtime mode if available, otherwise use persisted
        if "mode" in status:
            mode = status["mode"]
    except Exception:
        pass
    
    return {"mode": mode, "using_backup": using_backup, "persisted_mode": mode}


class OllamaModeRequest(BaseModel):
    mode: str  # "auto", "primary", "backup"


@app.post("/api/ollama-mode")
def set_ollama_mode(request: OllamaModeRequest):
    """Set Ollama mode: 'auto' (auto-failover), 'primary' (force localhost), 'backup' (force backup server)."""
    from ai_trading.ai_client import get_ai_client

    if request.mode not in ("auto", "primary", "backup"):
        raise HTTPException(status_code=400, detail="Mode must be 'auto', 'primary', or 'backup'")

    try:
        client = get_ai_client()
        client.set_force_ollama_mode(request.mode)
        # Persist to Redis
        redis_client.set("ollama_mode", request.mode)
        return {"mode": request.mode, "using_backup": client._using_backup}
    except Exception as e:
        # Still save to Redis even if client fails
        redis_client.set("ollama_mode", request.mode)
        raise HTTPException(status_code=500, detail=str(e))


# === Monitor AI Mode Control ===

@app.get("/api/monitor-ai-mode")
def get_monitor_ai_mode():
    """Get current monitor AI mode (cloud, local, or off)."""
    # Return persisted mode from Redis - this is the source of truth
    saved_mode = redis_client.get("monitor_ai_mode")
    mode = saved_mode.decode() if isinstance(saved_mode, bytes) else (saved_mode or "cloud")
    
    # Get client info for model details
    try:
        from ai_trading.ai_client import get_ai_client
        client = get_ai_client()
        return {
            "mode": mode,
            "local_model": getattr(client, '_monitor_local_model', 'qwen2.5:14b'),
            "local_base": getattr(client, '_monitor_local_base', 'http://192.168.0.35:11434'),
            "persisted_mode": mode
        }
    except Exception:
        return {"mode": mode, "persisted_mode": mode}


class MonitorAIModeRequest(BaseModel):
    mode: str  # "cloud", "local", or "off"


@app.post("/api/monitor-ai-mode")
def set_monitor_ai_mode(request: MonitorAIModeRequest):
    """Set monitor AI mode: 'cloud' (default/backup), 'local' (qwen2.5:14b localhost), or 'off' (disabled)."""
    from ai_trading.ai_client import get_ai_client

    if request.mode not in ("cloud", "local", "off"):
        raise HTTPException(status_code=400, detail="Mode must be 'cloud', 'local', or 'off'")

    try:
        client = get_ai_client()
        client.set_monitor_ai_mode(request.mode)
        # Persist to Redis
        redis_client.set("monitor_ai_mode", request.mode)
        return {
            "mode": request.mode,
            "local_model": client._monitor_local_model,
            "local_base": client._monitor_local_base
        }
    except Exception as e:
        # Still save to Redis even if client fails
        redis_client.set("monitor_ai_mode", request.mode)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/monitor-ai-test")
def test_monitor_ai():
    """Test the monitor AI connection (local or cloud)."""
    from ai_trading.ai_client import get_ai_client
    from ai_trading.prompts import POSITION_MONITOR_SYSTEM_LOCAL, position_monitor_prompt_local
    import time
    
    try:
        client = get_ai_client()
        mode = client.get_monitor_ai_mode()
        
        # Create a dummy position for testing
        test_position = {
            "symbol": "EURUSD",
            "direction": "LONG",
            "entry_price": 1.0850,
            "current_price": 1.0865,
            "stop_loss": 1.0800,
            "take_profit": 1.0950,
            "unrealized_pnl": 150.0
        }
        
        # Create dummy candles
        test_candles = [
            {"time": "12:00:00", "open": 1.0850, "high": 1.0860, "low": 1.0845, "close": 1.0855},
            {"time": "12:05:00", "open": 1.0855, "high": 1.0865, "low": 1.0850, "close": 1.0865},
        ]
        
        market_context = "Test market context - bullish momentum on EURUSD"
        
        if mode == "local":
            # Test local model
            prompt = position_monitor_prompt_local(test_position, market_context, test_candles)
            system = POSITION_MONITOR_SYSTEM_LOCAL
            
            start = time.time()
            response = client.generate_for_monitor(
                prompt=prompt,
                system=system,
                max_tokens=512,
                temperature=0.2,
                timeout=30.0
            )
            latency = (time.time() - start) * 1000
            
            # Try to parse JSON
            data = client.extract_json(response)
            
            return {
                "status": "success",
                "mode": mode,
                "model": response.model,
                "latency_ms": round(latency, 1),
                "response_preview": response.content[:200],
                "parsed_json": data is not None,
                "action": data.get("action") if data else None,
                "confidence": data.get("confidence") if data else None
            }
        else:
            # Test cloud mode
            return {
                "status": "success",
                "mode": mode,
                "message": "Cloud mode active - monitor will use primary/backup Ollama flow"
            }
            
    except Exception as e:
        return {
            "status": "error",
            "mode": mode if 'mode' in locals() else "unknown",
            "error": str(e),
            "hint": "If using local mode, ensure qwen2.5:14b is pulled: ollama pull qwen2.5:14b"
        }


# === Strategies ===

@app.get("/api/strategies")
def list_strategies():
    """List all loaded strategies."""
    engine = get_engine()
    return engine.strategy_loader.list_strategies()


@app.post("/api/strategies/{name}/toggle")
def toggle_strategy(name: str, toggle: StrategyToggle):
    """Enable/disable a strategy."""
    engine = get_engine()
    if toggle.enabled:
        engine.strategy_loader.enable_strategy(name)
    else:
        engine.strategy_loader.disable_strategy(name)
    return {"name": name, "enabled": toggle.enabled}


@app.post("/api/strategies/reload")
def reload_strategies():
    """Reload all strategies."""
    engine = get_engine()
    engine.strategy_loader.load_all()
    return {"status": "reloaded", "strategies": engine.strategy_loader.list_strategies()}


@app.post("/api/strategies/{name}/settings")
def update_strategy_settings(name: str, settings: StrategySettingsRequest):
    """Update strategy settings like max_positions and pip_multipliers."""
    engine = get_engine()
    loader = engine.strategy_loader

    with loader._lock:
        if name not in loader.strategies:
            raise HTTPException(status_code=404, detail="Strategy not found")

        strategy = loader.strategies[name]
        if not strategy.instance:
            raise HTTPException(status_code=400, detail="Strategy has no instance")

        # Update settings
        if settings.max_positions is not None:
            strategy.instance.max_positions = settings.max_positions
        if settings.max_positions_per_symbol is not None:
            strategy.instance.max_positions_per_symbol = settings.max_positions_per_symbol
        if settings.pip_multipliers is not None:
            strategy.instance.pip_multipliers = settings.pip_multipliers
        if settings.trailing_stop_trigger is not None:
            strategy.instance.trailing_stop_trigger = settings.trailing_stop_trigger
        if settings.trailing_stop_lock is not None:
            strategy.instance.trailing_stop_lock = settings.trailing_stop_lock

        # Persist to Redis
        redis_client.hset(
            f"strategy_settings:{name}",
            mapping={
                "max_positions": strategy.instance.max_positions,
                "max_positions_per_symbol": strategy.instance.max_positions_per_symbol,
                "pip_multipliers": json.dumps(strategy.instance.pip_multipliers),
                "trailing_stop_trigger": strategy.instance.trailing_stop_trigger,
                "trailing_stop_lock": strategy.instance.trailing_stop_lock
            }
        )

    return {
        "name": name,
        "max_positions": strategy.instance.max_positions,
        "max_positions_per_symbol": strategy.instance.max_positions_per_symbol,
        "pip_multipliers": strategy.instance.pip_multipliers
    }


class StrategySymbolsRequest(BaseModel):
    symbols: List[str]


@app.get("/api/strategies/{name}/symbols")
def get_strategy_symbols(name: str):
    """Get the list of symbols a strategy is allowed to trade on."""
    engine = get_engine()
    loader = engine.strategy_loader
    
    with loader._lock:
        if name not in loader.strategies:
            raise HTTPException(status_code=404, detail="Strategy not found")
        
        strategy = loader.strategies[name]
        
        # Get saved symbol selections from Redis
        saved_symbols = redis_client.smembers(f"strategy_symbols:{name}")
        
        # Get all active symbols from feed_config
        all_symbols = get_active_symbols()
        
        return {
            "name": name,
            "all_symbols": all_symbols,
            "selected_symbols": list(saved_symbols) if saved_symbols else [],
            "uses_all_symbols": not saved_symbols or len(saved_symbols) == 0
        }


@app.post("/api/strategies/{name}/symbols")
def update_strategy_symbols(name: str, request: StrategySymbolsRequest):
    """Update the list of symbols a strategy is allowed to trade on."""
    engine = get_engine()
    loader = engine.strategy_loader
    
    with loader._lock:
        if name not in loader.strategies:
            raise HTTPException(status_code=404, detail="Strategy not found")
        
        strategy = loader.strategies[name]
        if not strategy.instance:
            raise HTTPException(status_code=400, detail="Strategy has no instance")
        
        # Validate symbols exist in feed_config
        all_symbols = set(get_active_symbols())
        valid_symbols = [s for s in request.symbols if s in all_symbols]
        invalid_symbols = [s for s in request.symbols if s not in all_symbols]
        
        # Save to Redis as a set
        redis_key = f"strategy_symbols:{name}"
        
        if valid_symbols:
            # Clear existing and add new
            redis_client.delete(redis_key)
            redis_client.sadd(redis_key, *valid_symbols)
            # Update the strategy instance
            strategy.instance.symbols = valid_symbols
        else:
            # Empty list means use all symbols
            redis_client.delete(redis_key)
            strategy.instance.symbols = None
        
        return {
            "name": name,
            "symbols": valid_symbols,
            "invalid_symbols": invalid_symbols,
            "uses_all_symbols": not valid_symbols
        }


# === Trades ===

@app.get("/api/trades")
def get_trades(
    status: Optional[str] = None,
    strategy: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = Query(default=100, le=1000),
    offset: int = 0
):
    """Get trade history with filters."""
    conn = get_db_connection()
    cur = conn.cursor()
    
    query = """
        SELECT id, signal_id, strategy_name, symbol, direction, status,
               entry_price, exit_price, stop_loss, take_profit,
               quantity, leverage, pnl, pnl_percent, fees,
               ai_approved, ai_analysis, ai_confidence,
               signal_time, approved_time, entry_time, exit_time,
               entry_screenshot, exit_screenshot, metadata,
               trailing_stop_trigger, trailing_stop_lock, trailing_stop_activated
        FROM trades
        WHERE 1=1
    """
    params = []
    
    if status:
        query += " AND status = %s"
        params.append(status)
    if strategy:
        query += " AND strategy_name = %s"
        params.append(strategy)
    if symbol:
        query += " AND symbol = %s"
        params.append(symbol)
    
    query += " ORDER BY signal_time DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])
    
    cur.execute(query, params)
    columns = [desc[0] for desc in cur.description]
    trades = [dict(zip(columns, row)) for row in cur.fetchall()]
    
    # Get total count
    count_query = "SELECT COUNT(*) FROM trades WHERE 1=1"
    count_params = []
    if status:
        count_query += " AND status = %s"
        count_params.append(status)
    if strategy:
        count_query += " AND strategy_name = %s"
        count_params.append(strategy)
    if symbol:
        count_query += " AND symbol = %s"
        count_params.append(symbol)
    
    cur.execute(count_query, count_params)
    total = cur.fetchone()[0]
    
    cur.close()
    conn.close()
    
    # Convert datetime objects to strings
    for trade in trades:
        for key in ['signal_time', 'approved_time', 'entry_time', 'exit_time']:
            if trade[key]:
                trade[key] = trade[key].isoformat()
        # Convert Decimal to float
        for key in ['entry_price', 'exit_price', 'stop_loss', 'take_profit',
                    'quantity', 'leverage', 'pnl', 'pnl_percent', 'fees',
                    'ai_confidence', 'trailing_stop_trigger', 'trailing_stop_lock']:
            if trade[key] is not None:
                trade[key] = float(trade[key])
        if 'trailing_stop_activated' in trade:
            trade['trailing_stop_activated'] = bool(trade['trailing_stop_activated'])

    return {"trades": trades, "total": total}


@app.get("/api/trades/{trade_id}")
def get_trade(trade_id: int):
    """Get a specific trade."""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, signal_id, strategy_name, symbol, direction, status,
               entry_price, exit_price, stop_loss, take_profit,
               quantity, leverage, pnl, pnl_percent, fees,
               ai_approved, ai_analysis, ai_confidence,
               signal_time, approved_time, entry_time, exit_time,
               entry_screenshot, exit_screenshot, metadata,
               trailing_stop_trigger, trailing_stop_lock, trailing_stop_activated
        FROM trades WHERE id = %s
    """, (trade_id,))

    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Trade not found")

    columns = [desc[0] for desc in cur.description]
    trade = dict(zip(columns, row))

    cur.close()
    conn.close()

    # Convert types
    for key in ['signal_time', 'approved_time', 'entry_time', 'exit_time']:
        if trade[key]:
            trade[key] = trade[key].isoformat()
    for key in ['entry_price', 'exit_price', 'stop_loss', 'take_profit',
                'quantity', 'leverage', 'pnl', 'pnl_percent', 'fees',
                'ai_confidence', 'trailing_stop_trigger', 'trailing_stop_lock']:
        if trade[key] is not None:
            trade[key] = float(trade[key])
    if 'trailing_stop_activated' in trade:
        trade['trailing_stop_activated'] = bool(trade['trailing_stop_activated'])

    return trade


@app.post("/api/trades/{trade_id}/execute")
def execute_trade(trade_id: int):
    """Execute a pending trade."""
    engine = get_engine()
    trade = engine.execute_pending_trade(trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found or not pending")
    return {"status": "executed", "trade_id": trade_id}


@app.post("/api/trades/{trade_id}/close")
def close_trade(trade_id: int, request: CloseTradeRequest = None):
    """Close an open position."""
    tm = get_trade_manager()
    reason = request.reason if request else "Manual close"
    success, message = tm.close_trade(trade_id, reason)
    if not success:
        raise HTTPException(status_code=404, detail=message)
    return {"status": "closed", "message": message}


# === Trade Management ===

@app.post("/api/trades/{trade_id}/move-stop")
def move_stop_loss(trade_id: int, request: MoveStopRequest):
    """Move stop loss for a trade."""
    tm = get_trade_manager()
    success, message = tm.move_stop_loss(trade_id, request.new_stop)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}


@app.post("/api/trades/{trade_id}/move-tp")
def move_take_profit(trade_id: int, request: MoveTakeProfitRequest):
    """Move take profit for a trade."""
    tm = get_trade_manager()
    success, message = tm.move_take_profit(trade_id, request.new_tp)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}


@app.post("/api/trades/{trade_id}/break-even")
def set_break_even(trade_id: int, offset_pips: float = 0):
    """Move stop loss to break even."""
    tm = get_trade_manager()
    success, message = tm.set_break_even(trade_id, offset_pips)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}


@app.post("/api/trades/{trade_id}/trailing-stop")
def enable_trailing_stop(trade_id: int, request: TrailingStopRequest):
    """Enable trailing stop for a trade."""
    tm = get_trade_manager()
    success, message = tm.enable_trailing_stop(trade_id, request.trail_pips, request.activation_pips)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}


@app.delete("/api/trades/{trade_id}/trailing-stop")
def disable_trailing_stop(trade_id: int):
    """Disable trailing stop for a trade."""
    tm = get_trade_manager()
    success, message = tm.disable_trailing_stop(trade_id)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}


@app.post("/api/trades/{trade_id}/trailing-stop-dollar")
def set_trailing_stop_dollar(trade_id: int, request: TrailingStopDollarRequest):
    """Set trailing stop using dollar profit amounts instead of pips."""
    tm = get_trade_manager()
    success, message = tm.set_trailing_stop_dollar(trade_id, request.trigger_profit, request.lock_profit)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}


@app.post("/api/trades/close-all")
def close_all_trades(request: CloseAllRequest = None):
    """Close all open trades."""
    tm = get_trade_manager()
    symbol = request.symbol if request else None
    reason = request.reason if request else "Close all"
    count, message = tm.close_all_trades(symbol, reason)
    return {"status": "success", "closed": count, "message": message}


@app.delete("/api/trades")
def clear_trade_history():
    """Clear trade history from database, but keep open OANDA positions."""
    conn = get_db_connection()
    cur = conn.cursor()

    # Get count before delete (excluding open OANDA positions)
    cur.execute("""
        SELECT COUNT(*) FROM trades
        WHERE status != 'open' OR metadata IS NULL OR metadata->>'oanda_order_id' IS NULL
    """)
    count = cur.fetchone()[0]

    # Delete trades that are not open OANDA positions
    cur.execute("""
        DELETE FROM trades
        WHERE status != 'open' OR metadata IS NULL OR metadata->>'oanda_order_id' IS NULL
    """)
    conn.commit()

    cur.close()
    conn.close()

    return {"status": "cleared", "deleted": count}


@app.delete("/api/signals")
def clear_signal_history():
    """Clear all signal history from database."""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Check if signals table exists
    cur.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'signals'
        )
    """)
    
    if cur.fetchone()[0]:
        cur.execute("SELECT COUNT(*) FROM signals")
        count = cur.fetchone()[0]
        cur.execute("DELETE FROM signals")
        conn.commit()
    else:
        count = 0
    
    cur.close()
    conn.close()
    
    return {"status": "cleared", "deleted": count}


@app.delete("/api/history")
def clear_all_history():
    """Clear all history (trades, signals, strategy states) but keep open OANDA positions."""
    conn = get_db_connection()
    cur = conn.cursor()

    deleted = {"trades": 0, "signals": 0, "strategy_states": 0}

    # Clear trades (but keep open OANDA positions)
    cur.execute("""
        SELECT COUNT(*) FROM trades
        WHERE status != 'open' OR metadata IS NULL OR metadata->>'oanda_order_id' IS NULL
    """)
    deleted["trades"] = cur.fetchone()[0]
    cur.execute("""
        DELETE FROM trades
        WHERE status != 'open' OR metadata IS NULL OR metadata->>'oanda_order_id' IS NULL
    """)

    # Clear signals if table exists
    cur.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'signals'
        )
    """)
    if cur.fetchone()[0]:
        cur.execute("SELECT COUNT(*) FROM signals")
        deleted["signals"] = cur.fetchone()[0]
        cur.execute("DELETE FROM signals")

    conn.commit()
    cur.close()
    conn.close()

    # Clear strategy states from Redis
    deleted["strategy_states"] = redis_client.delete("strategy_states")

    # Clear engine state from Redis
    redis_client.delete("engine_state")
    
    return {"status": "cleared", "deleted": deleted}


# === Positions ===

def _get_monitor_confidence(trade_id: str) -> Optional[dict]:
    """Get last AI monitor result for a trade from Redis."""
    try:
        data = redis_client.get(f"monitor_result:{trade_id}")
        if data:
            import json
            return json.loads(data)
    except Exception:
        pass
    return None

@app.get("/api/positions")
def get_positions():
    """Get all open positions from OANDA and database."""
    positions = []
    summary = {
        "total_positions": 0,
        "total_unrealized_pnl": 0,
        "winning_positions": 0,
        "losing_positions": 0,
        "by_symbol": {}
    }

    # Get OANDA positions
    try:
        broker = get_oanda_broker()
        if broker.connected:
            # Get open trades from OANDA
            oanda_trades = broker.get_open_trades()
            
            # Get strategy names from database for OANDA trades
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT symbol, strategy_name, metadata
                FROM trades
                WHERE status = 'open' AND strategy_name IS NOT NULL
                ORDER BY entry_time DESC
            """)
            
            strategy_lookup = {}
            symbol_strategy = {}
            
            for row in cur.fetchall():
                db_symbol, strat_name, meta = row
                if meta and isinstance(meta, dict):
                    oanda_order_id = meta.get('oanda_order_id')
                    if oanda_order_id:
                        strategy_lookup[str(oanda_order_id)] = strat_name
                
                if db_symbol not in symbol_strategy:
                    symbol_strategy[db_symbol] = strat_name
            
            cur.close()
            conn.close()
            
            for trade in oanda_trades:
                symbol = trade.get("instrument", "").replace("_", "")
                units = int(float(trade.get("units", 0)))
                direction = "long" if units > 0 else "short"
                strategy_name = strategy_lookup.get(str(trade['id'])) or symbol_strategy.get(symbol) or "Manual/OANDA"
                
                positions.append({
                    "trade_id": f"oanda_trade_{trade.get('id')}",
                    "symbol": symbol,
                    "direction": direction,
                    "entry_price": float(trade.get("price", 0)),
                    "current_price": float(trade.get("price", 0)),
                    "quantity": abs(units),
                    "stop_loss": float(trade.get("stop_loss")) if trade.get("stop_loss") else None,
                    "take_profit": float(trade.get("take_profit")) if trade.get("take_profit") else None,
                    "unrealized_pnl": float(trade.get("unrealized_pnl", 0)),
                    "unrealized_pnl_pct": (float(trade.get("unrealized_pnl", 0)) / (float(trade.get("price", 1)) * abs(units))) * 100 if trade.get("price") and units else 0,
                    "strategy_name": strategy_name,
                    "broker": "oanda",
                    "opened_at": trade.get("open_time"),
                    "trailing_stop_trigger": None,
                    "trailing_stop_lock": None,
                    "trailing_stop_activated": False,
                    "ai_monitor": _get_monitor_confidence(f"oanda_trade_{trade.get('id')}")
                })
    except Exception as e:
        print(f"[API] Error getting OANDA positions: {e}")

    # Calculate summary
    summary["total_positions"] = len(positions)
    summary["total_unrealized_pnl"] = sum(p.get("unrealized_pnl", 0) for p in positions)

    for p in positions:
        sym = p["symbol"]
        if sym not in summary["by_symbol"]:
            summary["by_symbol"][sym] = {"count": 0, "pnl": 0, "long": 0, "short": 0}
        summary["by_symbol"][sym]["count"] += 1
        summary["by_symbol"][sym]["pnl"] += p.get("unrealized_pnl", 0)
        if p["direction"].lower() == "long":
            summary["by_symbol"][sym]["long"] += 1
        else:
            summary["by_symbol"][sym]["short"] += 1

        if p.get("unrealized_pnl", 0) > 0:
            summary["winning_positions"] += 1
        elif p.get("unrealized_pnl", 0) < 0:
            summary["losing_positions"] += 1

    return {"positions": positions, "summary": summary}


# === Performance ===

@app.get("/api/performance")
def get_performance(
    days: int = Query(default=30, le=365),
    strategy: Optional[str] = None
):
    """Get performance metrics."""
    conn = get_db_connection()
    cur = conn.cursor()
    
    start_date = datetime.utcnow() - timedelta(days=days)
    
    # Overall stats
    query = """
        SELECT 
            COUNT(*) as total_trades,
            COUNT(*) FILTER (WHERE pnl > 0) as winning_trades,
            COUNT(*) FILTER (WHERE pnl < 0) as losing_trades,
            COUNT(*) FILTER (WHERE pnl = 0) as breakeven_trades,
            COALESCE(SUM(pnl), 0) as total_pnl,
            COALESCE(AVG(pnl) FILTER (WHERE pnl > 0), 0) as avg_win,
            COALESCE(AVG(pnl) FILTER (WHERE pnl < 0), 0) as avg_loss,
            COALESCE(AVG(pnl_percent), 0) as avg_pnl_percent
        FROM trades
        WHERE status = 'closed' AND exit_time >= %s
    """
    params = [start_date]
    
    if strategy:
        query += " AND strategy_name = %s"
        params.append(strategy)
    
    cur.execute(query, params)
    row = cur.fetchone()
    
    total_trades = row[0]
    winning = row[1]
    losing = row[2]
    
    stats = {
        "total_trades": total_trades,
        "winning_trades": winning,
        "losing_trades": losing,
        "breakeven_trades": row[3],
        "win_rate": (winning / total_trades * 100) if total_trades > 0 else 0,
        "total_pnl": float(row[4]),
        "avg_win": float(row[5]),
        "avg_loss": float(row[6]),
        "avg_pnl_percent": float(row[7]),
        "profit_factor": abs(float(row[5]) * winning / (float(row[6]) * losing)) if losing > 0 and row[6] != 0 else 0
    }
    
    # Daily P&L for chart
    cur.execute("""
        SELECT DATE(exit_time) as date, SUM(pnl) as daily_pnl
        FROM trades
        WHERE status = 'closed' AND exit_time >= %s
        GROUP BY DATE(exit_time)
        ORDER BY date
    """, [start_date])
    
    daily_pnl = [{"date": row[0].isoformat(), "pnl": float(row[1])} for row in cur.fetchall()]
    
    # Cumulative P&L
    cumulative = 0
    cumulative_pnl = []
    for day in daily_pnl:
        cumulative += day["pnl"]
        cumulative_pnl.append({"date": day["date"], "cumulative_pnl": cumulative})
    
    cur.close()
    conn.close()
    
    return {
        "stats": stats,
        "daily_pnl": daily_pnl,
        "cumulative_pnl": cumulative_pnl
    }


@app.get("/api/performance/by-strategy")
def get_performance_by_strategy(days: int = Query(default=30, le=365)):
    """Get performance breakdown by strategy."""
    conn = get_db_connection()
    cur = conn.cursor()
    
    start_date = datetime.utcnow() - timedelta(days=days)
    
    cur.execute("""
        SELECT 
            strategy_name,
            COUNT(*) as total_trades,
            COUNT(*) FILTER (WHERE pnl > 0) as winning_trades,
            COALESCE(SUM(pnl), 0) as total_pnl,
            COALESCE(AVG(pnl_percent), 0) as avg_pnl_percent
        FROM trades
        WHERE status = 'closed' AND exit_time >= %s
        GROUP BY strategy_name
        ORDER BY total_pnl DESC
    """, [start_date])
    
    strategies = []
    for row in cur.fetchall():
        total = row[1]
        winning = row[2]
        strategies.append({
            "strategy": row[0],
            "total_trades": total,
            "winning_trades": winning,
            "win_rate": (winning / total * 100) if total > 0 else 0,
            "total_pnl": float(row[3]),
            "avg_pnl_percent": float(row[4])
        })
    
    cur.close()
    conn.close()
    
    return strategies


# === Balance ===

@app.get("/api/balance")
def get_balance():
    """Get current account balance."""
    engine = get_engine()
    return engine.executor.get_balance()


# === Logs ===

@app.get("/api/logs/{log_name}")
def get_log(log_name: str, lines: int = 100):
    """Get contents of a log file."""
    allowed_logs = ["api.log", "feeds.log", "dashboard.log"]
    if log_name not in allowed_logs:
        raise HTTPException(status_code=400, detail=f"Invalid log name. Allowed: {allowed_logs}")

    log_path = Path(__file__).parent / "logs" / log_name
    if not log_path.exists():
        return {"lines": [], "error": "Log file not found"}

    try:
        with open(log_path, 'r') as f:
            all_lines = f.readlines()
            # Get last N lines
            recent_lines = all_lines[-lines:] if lines > 0 else all_lines
            return {
                "lines": [l.strip() for l in recent_lines],
                "total_lines": len(all_lines),
                "filename": log_name
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/logs")
def list_logs():
    """List all available log files."""
    logs_dir = Path(__file__).parent / "logs"
    logs = []
    if logs_dir.exists():
        for f in logs_dir.iterdir():
            if f.is_file() and f.suffix == '.log':
                logs.append({
                    "name": f.name,
                    "size": f.stat().st_size,
                    "modified": datetime.now().isoformat()
                })
    return {"logs": logs}


# === Screenshots ===

@app.get("/api/screenshots/status")
def get_screenshots_status():
    """Get current screenshot enabled status."""
    # Read from Redis first, fall back to engine service
    try:
        saved = redis_client.get("screenshots_enabled")
        if saved is not None:
            enabled = saved.decode() if isinstance(saved, bytes) else saved
            return {"enabled": enabled == "1" or enabled == "True"}
    except Exception:
        pass
    
    # Fall back to engine service
    engine = get_engine()
    return {"enabled": engine.screenshot_service.is_enabled()}


class ScreenshotToggleRequest(BaseModel):
    enabled: bool


@app.post("/api/screenshots/toggle")
def toggle_screenshots(request: ScreenshotToggleRequest):
    """Enable or disable screenshots."""
    engine = get_engine()
    engine.screenshot_service.set_enabled(request.enabled)
    return {"enabled": request.enabled}


@app.get("/api/screenshots/{trade_id}")
def get_trade_screenshots(trade_id: int):
    """Get screenshots for a trade."""
    engine = get_engine()
    return engine.screenshot_service.get_screenshots_for_trade(trade_id)


class ScreenshotRequest(BaseModel):
    symbol: str
    trade_id: int
    event_type: str = "entry"  # "entry" or "exit"
    source: str = "all"  # "tradingview", "oanda", "screen", or "all"
    username: Optional[str] = None
    password: Optional[str] = None


@app.post("/api/screenshots/capture")
def capture_screenshots(request: ScreenshotRequest):
    """Capture screenshots for a trade from all sources."""
    engine = get_engine()
    service = engine.screenshot_service

    if request.source == "tradingview":
        results = {"tradingview": service.capture_tradingview(
            symbol=request.symbol,
            trade_id=request.trade_id,
            event_type=request.event_type,
            username=request.username,
            password=request.password
        )}
    elif request.source == "oanda":
        path = service.capture_oanda(request.symbol, request.trade_id, request.event_type)
        results = {"oanda": [{"path": path}]}
    elif request.source == "screen":
        path = service.capture_full_screen(request.trade_id, request.event_type)
        results = {"screen": path}
    else:  # "all"
        results = service.capture_all(
            symbol=request.symbol,
            trade_id=request.trade_id,
            event_type=request.event_type,
            username=request.username,
            password=request.password
        )

    return {"success": True, "screenshots": results}


# === OANDA Live Trading ===

# Initialize OANDA broker from feed config
_oanda_broker = None

def get_oanda_broker():
    """Get or create OANDA broker singleton."""
    global _oanda_broker
    if _oanda_broker is None:
        # Load config from feed_config.json
        config_path = Path(__file__).parent / "feed_config.json"
        with open(config_path) as f:
            config = json.load(f)
        
        # Find OANDA feed config
        oanda_config = None
        for feed in config.get("feeds", []):
            if feed.get("type") == "oanda":
                oanda_config = feed
                break
        
        if not oanda_config:
            raise HTTPException(status_code=500, detail="OANDA not configured in feed_config.json")
        
        _oanda_broker = OandaBroker(
            account_id=oanda_config["account_id"],
            api_token=oanda_config["api_token"],
            practice=oanda_config.get("practice", True)
        )
        _oanda_broker.connect()
    
    return _oanda_broker


@app.get("/api/oanda/account")
def get_oanda_account():
    """Get OANDA account info and balance."""
    broker = get_oanda_broker()
    return broker.get_balance()


@app.get("/api/oanda/positions")
def get_oanda_positions():
    """Get all open positions on OANDA."""
    broker = get_oanda_broker()
    return broker.get_all_positions()


@app.get("/api/oanda/trades")
def get_oanda_trades():
    """Get all open trades on OANDA with details."""
    broker = get_oanda_broker()
    return broker.get_open_trades()


@app.post("/api/oanda/order")
def place_oanda_order(order: OandaOrderRequest):
    """Place a market order on OANDA demo account."""
    broker = get_oanda_broker()
    
    result = broker.place_market_order(
        symbol=order.symbol,
        side=order.side.upper(),
        quantity=order.units,
        stop_loss=order.stop_loss,
        take_profit=order.take_profit
    )
    
    if result.success:
        return {
            "success": True,
            "order_id": result.order_id,
            "filled_price": result.filled_price,
            "filled_quantity": result.filled_quantity,
            "timestamp": result.timestamp.isoformat() if result.timestamp else None
        }
    else:
        raise HTTPException(status_code=400, detail=result.error)


@app.post("/api/oanda/close/{symbol}")
def close_oanda_position(symbol: str):
    """Close all positions for a symbol on OANDA."""
    broker = get_oanda_broker()
    result = broker.close_position(symbol)
    
    if result.success:
        return {
            "success": True,
            "filled_price": result.filled_price,
            "filled_quantity": result.filled_quantity
        }
    else:
        raise HTTPException(status_code=400, detail=result.error)


@app.post("/api/oanda/close-trade/{trade_id}")
def close_oanda_trade(trade_id: str):
    """Close a specific trade by ID on OANDA."""
    broker = get_oanda_broker()
    result = broker.close_trade(trade_id)
    
    if result.success:
        return {
            "success": True,
            "filled_price": result.filled_price
        }
    else:
        raise HTTPException(status_code=400, detail=result.error)


@app.get("/api/oanda/trade-history")
def get_oanda_trade_history(limit: int = Query(default=50, le=100)):
    """Get OANDA trade history with realized P&L."""
    broker = get_oanda_broker()

    try:
        # First, get the transaction IDs
        response = requests.get(
            f"{broker.api_url}/v3/accounts/{broker.account_id}/transactions",
            headers=broker.headers,
            params={"type": "ORDER_FILL", "count": limit},
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            trades = []

            # Fetch actual transaction details from pages
            for page_url in data.get("pages", []):
                page_resp = requests.get(page_url, headers=broker.headers, timeout=10)
                if page_resp.status_code == 200:
                    page_data = page_resp.json()

                    for tx in page_data.get("transactions", []):
                        # Only include trades that have realized PL (closing trades)
                        pl = tx.get("pl")
                        units = tx.get("units")
                        if pl is not None and units is not None:
                            instrument = tx.get("instrument", "")
                            symbol = instrument.replace("_", "")
                            units_int = int(float(units))
                            
                            # For ORDER_FILL with P&L, the price is the EXIT price
                            exit_price = float(tx.get("price", 0))
                            
                            # Calculate entry price from P&L and exit price
                            # P&L = (exit - entry) * units for long, (entry - exit) * units for short
                            pnl = float(pl)
                            units_abs = abs(units_int)
                            
                            if units_abs > 0:
                                if units_int > 0:  # Long position
                                    # pnl = (exit - entry) * units
                                    entry_price = exit_price - (pnl / units_abs)
                                else:  # Short position
                                    # pnl = (entry - exit) * units
                                    entry_price = exit_price + (pnl / units_abs)
                            else:
                                entry_price = exit_price

                            trades.append({
                                "id": tx.get("id"),
                                "symbol": symbol,
                                "instrument": instrument,
                                "units": units_abs,
                                "direction": "long" if units_int > 0 else "short",
                                "entry_price": entry_price,
                                "exit_price": exit_price,
                                "realized_pnl": pnl,
                                "time": tx.get("time"),
                                "reason": tx.get("reason", "CLOSE")
                            })

            # Try to match with database trades to get strategy names
            db_conn = get_db_connection()
            db_cur = db_conn.cursor()

            # Get all trades from DB (both open and closed) with strategy names
            db_cur.execute("""
                SELECT id, symbol, strategy_name, metadata, entry_time, exit_time, status
                FROM trades
                WHERE strategy_name IS NOT NULL
                ORDER BY COALESCE(exit_time, entry_time, signal_time) DESC
                LIMIT %s
            """, (limit * 2,))

            # Build a lookup by OANDA order ID and by symbol
            db_strategies = {}
            symbol_strategies = {}
            
            for row in db_cur.fetchall():
                trade_id, db_symbol, strategy_name, metadata, entry_time, exit_time, status = row
                
                # Match by OANDA order ID if available
                if metadata and isinstance(metadata, dict):
                    oanda_order_id = metadata.get('oanda_order_id')
                    if oanda_order_id:
                        db_strategies[str(oanda_order_id)] = strategy_name
                
                # Also keep most recent strategy per symbol as fallback
                if db_symbol not in symbol_strategies:
                    symbol_strategies[db_symbol] = strategy_name

            db_cur.close()
            db_conn.close()

            # Apply strategy names to trades
            for trade in trades:
                # Try to find strategy: first by order ID, then by symbol
                matched_strategy = db_strategies.get(str(trade["id"])) or symbol_strategies.get(trade["symbol"])
                trade["strategy_name"] = matched_strategy or "Manual/OANDA"

            return {
                "trades": trades,
                "total": len(trades),
                "total_pnl": sum(t["realized_pnl"] for t in trades)
            }
        else:
            raise HTTPException(status_code=400, detail="Failed to fetch trade history")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/oanda/performance")
def get_oanda_performance(days: int = Query(default=30, le=365)):
    """Get performance stats from OANDA trade history."""
    try:
        broker = get_oanda_broker()

        # Get transactions for the period
        from datetime import datetime, timedelta
        start_time = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"

        response = requests.get(
            f"{broker.api_url}/v3/accounts/{broker.account_id}/transactions",
            headers=broker.headers,
            params={"type": "ORDER_FILL", "count": 500, "from": start_time},
            timeout=10
        )

        if response.status_code != 200:
            return {
                "stats": {
                    "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
                    "breakeven_trades": 0, "win_rate": 0, "total_pnl": 0,
                    "avg_win": 0, "avg_loss": 0, "avg_pnl_percent": 0, "profit_factor": 0
                },
                "daily_pnl": [], "cumulative_pnl": [], "by_symbol": []
            }

        data = response.json()
        closed_trades = []
        daily_pnl = {}

        for page_url in data.get("pages", []):
            page_resp = requests.get(page_url, headers=broker.headers, timeout=10)
            if page_resp.status_code == 200:
                page_data = page_resp.json()
                for tx in page_data.get("transactions", []):
                    pl = tx.get("pl")
                    units = tx.get("units")
                    if pl is not None and units is not None:
                        pl_float = float(pl)
                        if pl_float != 0:  # Only closed trades
                            instrument = tx.get("instrument", "")
                            symbol = instrument.replace("_", "")
                            tx_time = tx.get("time", "")
                            date_key = tx_time[:10] if tx_time else "unknown"

                            if date_key not in daily_pnl:
                                daily_pnl[date_key] = 0
                            daily_pnl[date_key] += pl_float

                            closed_trades.append({
                                "symbol": symbol,
                                "pnl": pl_float,
                                "direction": "long" if int(float(units)) > 0 else "short",
                                "time": tx_time
                            })

        # Calculate stats
        winning_trades = [t for t in closed_trades if t["pnl"] > 0]
        losing_trades = [t for t in closed_trades if t["pnl"] < 0]
        breakeven_trades = [t for t in closed_trades if t["pnl"] == 0]

        total_pnl = sum(t["pnl"] for t in closed_trades)
        win_rate = (len(winning_trades) / len(closed_trades) * 100) if closed_trades else 0
        avg_win = sum(t["pnl"] for t in winning_trades) / len(winning_trades) if winning_trades else 0
        avg_loss = sum(t["pnl"] for t in losing_trades) / len(losing_trades) if losing_trades else 0
        gross_profit = sum(t["pnl"] for t in winning_trades)
        gross_loss = abs(sum(t["pnl"] for t in losing_trades))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        avg_pnl_percent = (total_pnl / len(closed_trades)) if closed_trades else 0

        # By symbol stats
        symbols = {}
        for t in closed_trades:
            sym = t["symbol"]
            if sym not in symbols:
                symbols[sym] = {"trades": 0, "wins": 0, "pnl": 0}
            symbols[sym]["trades"] += 1
            if t["pnl"] > 0:
                symbols[sym]["wins"] += 1
            symbols[sym]["pnl"] += t["pnl"]

        by_symbol = []
        for sym, stats in symbols.items():
            by_symbol.append({
                "symbol": sym,
                "total_trades": stats["trades"],
                "winning_trades": stats["wins"],
                "losing_trades": stats["trades"] - stats["wins"],
                "win_rate": (stats["wins"] / stats["trades"] * 100) if stats["trades"] > 0 else 0,
                "total_pnl": stats["pnl"]
            })

        # Sort by P&L
        by_symbol.sort(key=lambda x: x["total_pnl"], reverse=True)

        # Daily P&L sorted
        daily_pnl_list = [{"date": k, "pnl": v} for k, v in daily_pnl.items()]
        daily_pnl_list.sort(key=lambda x: x["date"])

        # Cumulative P&L
        cumulative = 0
        cumulative_pnl = []
        for d in daily_pnl_list:
            cumulative += d["pnl"]
            cumulative_pnl.append({"date": d["date"], "cumulative_pnl": cumulative})

        return {
            "stats": {
                "total_trades": len(closed_trades),
                "winning_trades": len(winning_trades),
                "losing_trades": len(losing_trades),
                "breakeven_trades": len(breakeven_trades),
                "win_rate": win_rate,
                "total_pnl": total_pnl,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "avg_pnl_percent": avg_pnl_percent,
                "profit_factor": profit_factor
            },
            "daily_pnl": daily_pnl_list,
            "cumulative_pnl": cumulative_pnl,
            "by_symbol": by_symbol
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/symbol-bias")
def get_symbol_bias(timeframe: str = Query(default="H1")):
    """
    Get bullish/bearish bias for all active symbols based on price action.
    Uses EMA crossover and trend analysis.
    """
    try:
        # Map timeframe string to Timeframe enum
        tf_map = {
            "M5": Timeframe.M5, "M15": Timeframe.M15,
            "H1": Timeframe.H1, "H4": Timeframe.H4, "D1": Timeframe.D1
        }
        tf = tf_map.get(timeframe.upper(), Timeframe.H1)

        aggregator = get_candle_aggregator()
        symbols = get_active_symbols()

        biases = {}
        for symbol in symbols:
            closes = aggregator.get_closes(symbol, tf, count=50)
            if len(closes) < 10:
                biases[symbol] = {"bias": "neutral", "strength": 0, "tf": timeframe}
                continue

            # Calculate EMAs
            ema_fast = sum(closes[-5:]) / 5
            ema_medium = sum(closes[-15:]) / 15 if len(closes) >= 15 else sum(closes) / len(closes)
            ema_slow = sum(closes[-30:]) / 30 if len(closes) >= 30 else ema_medium

            current_price = closes[-1]
            prev_price = closes[-2] if len(closes) > 1 else current_price

            # Bullish signals
            bullish_signals = 0
            bearish_signals = 0

            # EMA crossover
            if ema_fast > ema_medium > ema_slow:
                bullish_signals += 2
            elif ema_fast < ema_medium < ema_slow:
                bearish_signals += 2

            # Price vs EMAs
            if current_price > ema_fast:
                bullish_signals += 1
            else:
                bearish_signals += 1

            # Recent trend (last 10 candles)
            recent_trend = closes[-1] - closes[-10] if len(closes) >= 10 else 0
            if recent_trend > 0:
                bullish_signals += 1
            else:
                bearish_signals += 1

            # Candle direction
            if len(closes) >= 2 and closes[-1] > closes[-2]:
                bullish_signals += 1
            else:
                bearish_signals += 1

            total_signals = bullish_signals + bearish_signals
            if total_signals > 0:
                strength = abs(bullish_signals - bearish_signals) / total_signals * 100
            else:
                strength = 0

            if bullish_signals > bearish_signals:
                bias = "bullish"
            elif bearish_signals > bullish_signals:
                bias = "bearish"
            else:
                bias = "neutral"

            biases[symbol] = {
                "bias": bias,
                "strength": round(strength, 1),
                "price": round(current_price, 5),
                "ema_fast": round(ema_fast, 5),
                "ema_medium": round(ema_medium, 5),
                "ema_slow": round(ema_slow, 5),
                "tf": timeframe
            }

        return {"biases": biases, "timeframe": timeframe}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# === Trade Buckets ===

class TradeBucket:
    """In-memory bucket for grouping trades."""
    def __init__(self, name: str):
        self.name = name
        self.trade_ids = []
        self.auto_close_if_profit = False

_buckets = {}

@app.get("/api/buckets")
def get_buckets():
    """Get all buckets with their trades."""
    # Get current positions
    positions_data = get_positions()
    positions = positions_data.get("positions", [])

    result = []
    for name, bucket in _buckets.items():
        bucket_positions = [p for p in positions if f"bucket_{name}_{p['trade_id']}" in bucket.trade_ids or p["trade_id"] in bucket.trade_ids]
        total_pnl = sum(p.get("unrealized_pnl", 0) for p in bucket_positions)

        result.append({
            "name": name,
            "positions": bucket_positions,
            "count": len(bucket_positions),
            "total_pnl": total_pnl,
            "in_profit": total_pnl > 0,
            "auto_close_if_profit": bucket.auto_close_if_profit
        })
    return result

@app.post("/api/buckets/{bucket_name}")
def create_bucket(bucket_name: str):
    """Create a new bucket."""
    if bucket_name not in _buckets:
        _buckets[bucket_name] = TradeBucket(bucket_name)
    return {"success": True, "bucket": bucket_name}

@app.delete("/api/buckets/{bucket_name}")
def delete_bucket(bucket_name: str):
    """Delete a bucket (doesn't close trades)."""
    if bucket_name in _buckets:
        del _buckets[bucket_name]
    return {"success": True}

@app.post("/api/buckets/{bucket_name}/add/{trade_id}")
def add_to_bucket(bucket_name: str, trade_id: str):
    """Add a trade to a bucket."""
    if bucket_name not in _buckets:
        _buckets[bucket_name] = TradeBucket(bucket_name)
    _buckets[bucket_name].trade_ids.append(trade_id)
    return {"success": True, "bucket": bucket_name, "trade_id": trade_id}

@app.post("/api/buckets/{bucket_name}/remove/{trade_id}")
def remove_from_bucket(bucket_name: str, trade_id: str):
    """Remove a trade from a bucket."""
    if bucket_name in _buckets:
        if trade_id in _buckets[bucket_name].trade_ids:
            _buckets[bucket_name].trade_ids.remove(trade_id)
    return {"success": True}

@app.post("/api/buckets/{bucket_name}/close")
def close_bucket(bucket_name: str):
    """Close all trades in a bucket."""
    if bucket_name not in _buckets:
        return {"success": False, "error": "Bucket not found"}

    bucket = _buckets[bucket_name]
    positions_data = get_positions()
    positions = positions_data.get("positions", [])

    closed = []
    errors = []

    for trade_id in bucket.trade_ids:
        position = next((p for p in positions if p["trade_id"] == trade_id), None)
        if not position:
            continue

        try:
            if position["broker"] == "oanda":
                # Extract OANDA trade ID
                if trade_id.startswith("oanda_trade_"):
                    oanda_trade_id = trade_id.replace("oanda_trade_", "")
                elif trade_id.startswith("oanda_"):
                    oanda_trade_id = trade_id.replace("oanda_", "")
                else:
                    oanda_trade_id = trade_id

                broker = get_oanda_broker()
                result = broker.close_trade(oanda_trade_id)
                if result.success:
                    closed.append(trade_id)
                else:
                    errors.append({"trade_id": trade_id, "error": result.error})
            else:
                errors.append({"trade_id": trade_id, "error": "Unknown broker"})
        except Exception as e:
            errors.append({"trade_id": trade_id, "error": str(e)})

    # Clear the bucket
    bucket.trade_ids = []

    return {
        "success": len(errors) == 0,
        "closed": closed,
        "errors": errors,
        "bucket_pnl": sum(p.get("unrealized_pnl", 0) for p in positions if p["trade_id"] in closed)
    }

@app.post("/api/buckets/{bucket_name}/close-if-profit")
def close_bucket_if_profit(bucket_name: str):
    """Close all trades in bucket if bucket is in profit."""
    if bucket_name not in _buckets:
        return {"success": False, "error": "Bucket not found"}

    bucket = _buckets[bucket_name]
    positions_data = get_positions()
    positions = positions_data.get("positions", [])

    bucket_positions = [p for p in positions if p["trade_id"] in bucket.trade_ids]
    total_pnl = sum(p.get("unrealized_pnl", 0) for p in bucket_positions)

    if total_pnl > 0:
        return close_bucket(bucket_name)
    else:
        return {"success": True, "skipped": True, "reason": "Bucket not in profit", "pnl": total_pnl}

@app.post("/api/buckets/{bucket_name}/auto-close")
def set_bucket_auto_close(bucket_name: str, enabled: bool = True):
    """Set bucket to auto-close when in profit."""
    if bucket_name not in _buckets:
        _buckets[bucket_name] = TradeBucket(bucket_name)
    _buckets[bucket_name].auto_close_if_profit = enabled
    return {"success": True, "auto_close": enabled}


# === Strategy Performance ===

@app.get("/api/strategy-performance")
def get_strategies_performance(days: int = Query(default=7, ge=1, le=90)):
    """
    Get performance metrics for all strategies.
    
    Args:
        days: Number of days to analyze (1-90, default 7)
    
    Returns:
        List of strategy performance metrics sorted by total PnL
    """
    try:
        from datetime import timedelta
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        period_end = datetime.utcnow()
        period_start = period_end - timedelta(days=days)
        
        # Get unique strategies
        cur.execute("""
            SELECT DISTINCT strategy_name FROM trades
            WHERE signal_time >= %s
            ORDER BY strategy_name
        """, (period_start,))
        
        strategies = [row[0] for row in cur.fetchall() if row[0]]
        results = []
        
        for strategy in strategies:
            # Get trade stats
            cur.execute("""
                SELECT 
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
                    SUM(pnl) as total_pnl,
                    AVG(pnl) as avg_pnl,
                    MAX(pnl) as max_pnl,
                    MIN(pnl) as min_pnl,
                    AVG(CASE WHEN pnl > 0 THEN pnl END) as avg_win,
                    AVG(CASE WHEN pnl < 0 THEN pnl END) as avg_loss,
                    SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END) as gross_profit,
                    SUM(CASE WHEN pnl < 0 THEN ABS(pnl) ELSE 0 END) as gross_loss
                FROM trades
                WHERE strategy_name = %s 
                AND status IN ('closed', 'open')
                AND signal_time >= %s
            """, (strategy, period_start))
            
            trade_stats = cur.fetchone()
            
            total_trades = trade_stats[0] or 0
            wins = trade_stats[1] or 0
            losses = trade_stats[2] or 0
            total_pnl = float(trade_stats[3] or 0)
            avg_pnl = float(trade_stats[4] or 0)
            max_pnl = float(trade_stats[5] or 0)
            min_pnl = float(trade_stats[6] or 0)
            avg_win = float(trade_stats[7] or 0)
            avg_loss = float(trade_stats[8] or 0)
            gross_profit = float(trade_stats[9] or 0)
            gross_loss = float(trade_stats[10] or 0)
            
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
            profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0
            
            results.append({
                "strategy": strategy,
                "total_trades": total_trades,
                "winning_trades": wins,
                "losing_trades": losses,
                "win_rate": round(win_rate, 2),
                "total_pnl": round(total_pnl, 2),
                "avg_pnl": round(avg_pnl, 2),
                "max_pnl": round(max_pnl, 2),
                "min_pnl": round(min_pnl, 2),
                "avg_win": round(avg_win, 2),
                "avg_loss": round(avg_loss, 2),
                "profit_factor": round(profit_factor, 2),
                "gross_profit": round(gross_profit, 2),
                "gross_loss": round(gross_loss, 2)
            })
        
        cur.close()
        conn.close()
        
        # Sort by total PnL descending
        results.sort(key=lambda x: x["total_pnl"], reverse=True)
        
        return {
            "strategies": results,
            "period_days": days,
            "total_strategies": len(results)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculating performance: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    
    # Start engine
    engine = get_engine(auto_trade=False, require_approval=True)
    engine.start()
    
    # Run API
    uvicorn.run(app, host="0.0.0.0", port=8000)
