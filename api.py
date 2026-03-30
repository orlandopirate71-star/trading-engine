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
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

class BrokerModeRequest(BaseModel):
    mode: str  # "paper" or "oanda"


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
    """Get total candle count in database."""
    from candle_store import get_candle_store
    store = get_candle_store()
    return {"count": store.get_candle_count()}


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
               openclaw_approved, openclaw_analysis, openclaw_confidence,
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
                    'openclaw_confidence', 'trailing_stop_trigger', 'trailing_stop_lock']:
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
               openclaw_approved, openclaw_analysis, openclaw_confidence,
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
                'openclaw_confidence', 'trailing_stop_trigger', 'trailing_stop_lock']:
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

@app.get("/api/positions")
def get_open_positions_api():
    """Get all open positions with current P&L (OANDA only when in OANDA mode)."""
    tm = get_trade_manager()
    engine = get_engine()
    
    positions_list = []
    
    # Only show paper trades if in paper mode
    if engine.broker_mode == "paper":
        # Get paper/DB positions
        positions = tm.get_open_positions()
        for p in positions:
            positions_list.append({
                "trade_id": p.trade_id,
                "symbol": p.symbol,
                "direction": p.direction.value,
                "entry_price": p.entry_price,
                "current_price": p.current_price,
                "quantity": p.quantity,
                "stop_loss": p.stop_loss,
                "take_profit": p.take_profit,
                "unrealized_pnl": p.unrealized_pnl,
                "unrealized_pnl_pct": p.unrealized_pnl_pct,
                "is_profitable": p.is_profitable,
                "opened_at": p.opened_at.isoformat(),
                "strategy_name": p.strategy_name,
                "broker": "paper",
                "trailing_stop_trigger": p.trailing_stop_trigger,
                "trailing_stop_lock": p.trailing_stop_lock,
                "trailing_stop_activated": p.trailing_stop_activated
            })
    
    # Add OANDA trades if broker is available
    if engine.oanda_broker:
        oanda_trades = engine.oanda_broker.get_open_trades()
        for t in oanda_trades:
            # Convert instrument format (EUR_USD -> EURUSD)
            symbol = t["instrument"].replace("_", "")
            units = t["units"]
            direction = "long" if units > 0 else "short"
            
            positions_list.append({
                "trade_id": f"oanda_{t['id']}",
                "symbol": symbol,
                "direction": direction,
                "entry_price": t["price"],
                "current_price": t["price"],  # Will be updated by price feed
                "quantity": abs(units),
                "stop_loss": float(t["stop_loss"]) if t.get("stop_loss") else None,
                "take_profit": float(t["take_profit"]) if t.get("take_profit") else None,
                "unrealized_pnl": t["unrealized_pnl"],
                "unrealized_pnl_pct": (t["unrealized_pnl"] / (t["price"] * abs(units))) * 100 if t["price"] and units else 0,
                "is_profitable": t["unrealized_pnl"] >= 0,
                "opened_at": t["open_time"],
                "strategy_name": "Manual/OANDA",
                "broker": "oanda"
            })
    
    return {
        "positions": positions_list,
        "summary": tm.get_summary() if engine.broker_mode == "paper" else {"total_positions": len(positions_list), "total_unrealized_pnl": sum(p["unrealized_pnl"] for p in positions_list)}
    }


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

@app.get("/api/positions")
def get_positions():
    """Get all open positions (paper + OANDA)."""
    positions = []
    summary = {
        "total_positions": 0,
        "total_unrealized_pnl": 0,
        "winning_positions": 0,
        "losing_positions": 0,
        "by_symbol": {}
    }

    # Get paper trading positions
    engine = get_engine()
    paper_positions = engine.executor.get_open_positions()
    for p in paper_positions:
        positions.append({
            "trade_id": str(p.trade_id),
            "symbol": p.symbol,
            "direction": p.direction.value,
            "entry_price": p.entry_price,
            "current_price": p.current_price,
            "quantity": p.quantity,
            "stop_loss": p.stop_loss,
            "take_profit": p.take_profit,
            "unrealized_pnl": p.unrealized_pnl,
            "unrealized_pnl_pct": ((p.current_price - p.entry_price) / p.entry_price * 100) if p.direction.value == "long" else ((p.entry_price - p.current_price) / p.entry_price * 100),
            "strategy_name": getattr(p, 'strategy_name', 'Unknown'),
            "broker": "paper",
            "opened_at": p.opened_at.isoformat() if hasattr(p, 'opened_at') else None
        })

    # Get OANDA positions
    try:
        broker = get_oanda_broker()
        if broker.connected:
            oanda_positions = broker.get_all_positions()
            for symbol, pos in oanda_positions.items():
                # Get current price from Redis
                current_price = pos.get("avg_price", 0)
                unrealized_pnl = pos.get("unrealized_pnl", 0)
                direction = pos.get("side", "long").lower()
                # Calculate entry price based on unrealized P&L direction
                entry_adjustment = unrealized_pnl / pos["units"] if pos["units"] != 0 else 0
                entry_price = pos["avg_price"] - entry_adjustment if direction == "long" else pos["avg_price"] + entry_adjustment

                positions.append({
                    "trade_id": f"oanda_{symbol}",
                    "symbol": symbol,
                    "direction": direction,
                    "entry_price": pos["avg_price"],
                    "current_price": current_price,
                    "quantity": pos["units"],
                    "stop_loss": None,
                    "take_profit": None,
                    "unrealized_pnl": unrealized_pnl,
                    "unrealized_pnl_pct": (unrealized_pnl / (pos["avg_price"] * pos["units"]) * 100) if pos["units"] > 0 else 0,
                    "strategy_name": "OANDA",
                    "broker": "oanda",
                    "opened_at": None
                })

            # Also get open trades that might not be in positions
            oanda_trades = broker.get_open_trades()
            for trade in oanda_trades:
                symbol = trade.get("instrument", "").replace("_", "")
                # Check if already in positions
                existing = [p for p in positions if p["symbol"] == symbol and p["broker"] == "oanda"]
                if not existing:
                    positions.append({
                        "trade_id": f"oanda_trade_{trade.get('id')}",
                        "symbol": symbol,
                        "direction": "long" if int(float(trade.get("units", 0))) > 0 else "short",
                        "entry_price": trade.get("price", 0),
                        "current_price": trade.get("price", 0),
                        "quantity": abs(int(float(trade.get("units", 0)))),
                        "stop_loss": trade.get("stop_loss"),
                        "take_profit": trade.get("take_profit"),
                        "unrealized_pnl": trade.get("unrealized_pnl", 0),
                        "unrealized_pnl_pct": 0,
                        "strategy_name": "OANDA",
                        "broker": "oanda",
                        "opened_at": trade.get("open_time")
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

                            trades.append({
                                "id": tx.get("id"),
                                "symbol": symbol,
                                "instrument": instrument,
                                "units": abs(units_int),
                                "direction": "long" if units_int > 0 else "short",
                                "entry_price": float(tx.get("price", 0)),
                                "realized_pnl": float(pl),
                                "time": tx.get("time"),
                                "reason": tx.get("reason", "CLOSE")
                            })

            # Try to match with database trades to get strategy names
            db_conn = get_db_connection()
            db_cur = db_conn.cursor()

            # Get closed trades from DB that have oanda_order_id in metadata
            db_cur.execute("""
                SELECT id, symbol, strategy_name, metadata
                FROM trades
                WHERE status = 'closed' AND metadata IS NOT NULL
                ORDER BY exit_time DESC
                LIMIT %s
            """, (limit,))

            # Build a lookup: (symbol, strategy_name) -> strategy_name from most recent
            db_strategies = {}
            for row in db_cur.fetchall():
                trade_id, db_symbol, strategy_name, metadata = row
                if metadata and isinstance(metadata, dict):
                    oanda_order_id = metadata.get('oanda_order_id')
                    if oanda_order_id:
                        # Match by OANDA order ID
                        db_strategies[oanda_order_id] = strategy_name

            # Also build a time-based lookup as fallback
            # Group by symbol and take the most recent strategy for each
            for row in db_cur.fetchall():
                trade_id, db_symbol, strategy_name, metadata = row
                # Store by symbol, keep the most recent (first since ordered by exit_time DESC)
                if db_symbol not in db_strategies:
                    db_strategies[f"symbol_{db_symbol}"] = strategy_name

            db_cur.close()
            db_conn.close()

            # Apply strategy names to trades
            for trade in trades:
                # Try to find strategy from DB
                matched_strategy = db_strategies.get(trade["id"]) or db_strategies.get(f"symbol_{trade['symbol']}")
                trade["strategy_name"] = matched_strategy or "OANDA"

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
                # Paper trade
                result = requests.post(
                    f"http://localhost:8000/api/trades/{trade_id}/close",
                    json={"reason": f"Bucket close: {bucket_name}"}
                )
                if result.status_code == 200:
                    closed.append(trade_id)
                else:
                    errors.append({"trade_id": trade_id, "error": result.text})
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


if __name__ == "__main__":
    import uvicorn
    
    # Start engine
    engine = get_engine(auto_trade=False, require_approval=True)
    engine.start()
    
    # Run API
    uvicorn.run(app, host="0.0.0.0", port=8000)
