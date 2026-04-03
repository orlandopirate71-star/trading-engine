# Trading Engine - AI Assistant Memory Guide

> **For AI Assistants**: This document contains everything needed to understand and work with this trading system. Read this first before making any changes.

## Quick Overview

A Python-based algorithmic trading engine with AI-powered trade validation, supporting OANDA broker integration, multiple data feeds, and a React dashboard. Uses event-driven architecture with hot-reloading strategy support.

**Key Tech Stack**: Python 3.12, FastAPI, Redis, PostgreSQL, React, Ollama AI

---

## System Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────┐
│ Data Feeds  │────▶│   Redis      │────▶│ Strategies  │────▶│ AI Val.  │
│ (OANDA,etc) │     │ (ticks/pub)  │     │ (on_candle) │     │(Ollama)  │
└─────────────┘     └──────────────┘     └─────────────┘     └────┬─────┘
       │                                                           │
       ▼                                                           ▼
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────┐
│PostgreSQL   │◀────│Candle Store  │◀────│Candle Agg.  │◀────│OANDA API │
│(candles,    │     │              │     │ (M5,H1,D1)  │     │(execution)│
│trades)      │     └──────────────┘     └─────────────┘     └──────────┘
└─────────────┘                                                    │
       │                                                           │
       ▼                                                           ▼
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────┐
│Dashboard    │◀────│FastAPI       │◀────│Trade Manager│◀────│Executor  │
│(React)      │     │(WebSocket)   │     │(positions)   │     │(orders)  │
└─────────────┘     └──────────────┘     └─────────────┘     └──────────┘
```

---

## Directory Structure

```
trading_engine/
├── api.py                  # FastAPI backend (all HTTP/WebSocket endpoints)
├── trading_engine.py       # Main orchestrator - starts/stops all components
├── strategy_loader.py      # Hot-reloading strategy manager
├── executor.py             # Trade execution (pending → open orders)
├── trade_manager.py        # Position lifecycle management
├── candle_aggregator.py    # Tick → candle aggregation
├── candle_store.py         # PostgreSQL candle persistence
├── oanda_broker.py         # OANDA REST API wrapper
├── models.py               # TradeSignal, Trade dataclasses
├── indicators.py           # Technical analysis functions
├── screenshot.py           # Trade entry/exit screenshots (selenium)
├── feed_symbols.py         # Symbol config management
├── connections.py          # Redis/PostgreSQL connections
│
├── strategies/             # Trading strategies (auto-loaded)
│   ├── strategy_loader.py  # Contains BaseStrategy class
│   ├── breakout_pullback.py
│   ├── quick_flip_scalper.py
│   ├── ema_1min_scalper.py
│   └── ... (20+ strategies)
│
├── ai_trading/             # AI validation system
│   ├── ai_client.py       # LLM client (Ollama primary, cloud fallback)
│   ├── prompts.py         # AI system prompts
│   ├── validators/
│   │   ├── ai_validator.py    # Signal validation (APPROVE/REJECT)
│   │   └── position_monitor.py # Position monitoring (HOLD/CLOSE/EXTEND)
│   └── brain_client.py    # MCP memory integration
│
├── dashboard/              # React + Vite frontend
│   └── src/pages/
│       ├── Dashboard.jsx      # Main trading view
│       ├── Strategies.jsx     # Strategy management + symbol selection
│       ├── Trades.jsx         # Trade history
│       └── Positions.jsx      # Open positions
│
└── feeds/                  # Data feed implementations
```

---

## How Strategies Work (CRITICAL)

### BaseStrategy Class - Required Pattern

**Every strategy MUST inherit from `strategy_loader.BaseStrategy`:**

```python
from strategy_loader import BaseStrategy
from models import TradeSignal
from typing import Optional

class MyStrategy(BaseStrategy):
    # Required class attributes
    name = "MyStrategy"                    # Unique identifier
    symbols = None                         # None = all, or ["EURUSD", "GBPUSD"]
    timeframe = "M5"                       # M1, M5, M15, H1, H4, D1
    max_positions = 0                      # 0 = unlimited total positions
    max_positions_per_symbol = 1           # Per-symbol limit
    
    # Optional: Expand SL/TP for volatile instruments
    pip_multipliers = {"XAUUSD": 3.0, "XAGUSD": 2.0}
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        # Custom params from settings
        self.period = params.get('period', 14) if params else 14
    
    def on_candle(self, symbol: str, candle: dict) -> Optional[TradeSignal]:
        """
        Called on each new candle for each symbol in active_symbols.
        
        Args:
            symbol: Trading pair (e.g., "EURUSD")
            candle: Dict with:
                - open, high, low, close, volume (float)
                - timestamp (datetime)
                - timeframe (str)
                - history: CandleHistory object with methods:
                    - get_closes(n) → List[float]
                    - get_highs(n) → List[float]
                    - get_lows(n) → List[float]
                    - get_candles(n) → List[Candle]
        
        Returns:
            TradeSignal or None
        """
        history = candle.get('history')
        if not history:
            return None
            
        closes = history.get_closes(20)
        if len(closes) < 20:
            return None
            
        # Your logic...
        if self.should_enter(symbol, closes):
            return self.create_signal(
                symbol=symbol,
                direction="LONG",           # or "SHORT"
                entry_price=candle['close'],
                stop_loss=candle['close'] - 0.0010,
                take_profit=candle['close'] + 0.0020,
                confidence=0.75,            # 0.0 - 1.0
                reason="Bullish breakout"
            )
        return None
```

### Critical Pattern: ATR Scaling for Metals

**Always implement `_get_atr_multiplier()` for XAGUSD/XAUUSD:**

```python
def _get_atr_multiplier(self, symbol: str) -> float:
    """Scale SL/TP for metals to avoid AI rejection (TP too close to entry)."""
    symbol_upper = symbol.upper()
    
    if 'XAU' in symbol_upper or 'GOLD' in symbol_upper:
        return 0.1   # Gold: reduce by 90%
    elif 'XAG' in symbol_upper or 'SILVER' in symbol_upper:
        return 0.15  # Silver: reduce by 85%
    elif 'JPY' in symbol_upper:
        return 0.01  # JPY pairs
    elif any(c in symbol_upper for c in ['BTC', 'ETH']):
        return 0.5   # Crypto
    
    return 1.0  # Standard forex

# Use in on_candle():
multiplier = self._get_atr_multiplier(symbol)
adjusted_range = raw_range * multiplier
adjusted_sl_buffer = sl_buffer * multiplier
```

### Strategy Lifecycle

1. **File dropped** in `strategies/` → Auto-detected by `watchdog`
2. **Class loaded** by `StrategyLoader.load_strategy_file()`
3. **Instance created** with saved settings from Redis
4. **Enabled** → `on_candle()` called on each new candle
5. **Signal returned** → Goes to AI validator
6. **Approved** → Pending trade created
7. **Executed** → Position opened via OANDA

### Strategy Settings API

```bash
# Toggle enable/disable
POST /api/strategies/{name}/toggle {"enabled": true}

# Update settings
POST /api/strategies/{name}/settings {
    "max_positions": 5,
    "max_positions_per_symbol": 2,
    "pip_multipliers": {"XAUUSD": 3.0},
    "trailing_stop_trigger": 100,
    "trailing_stop_lock": 50
}

# Symbol selection (new feature)
GET /api/strategies/{name}/symbols
POST /api/strategies/{name}/symbols {"symbols": ["EURUSD", "GBPUSD"]}
```

---

## Data Flow Deep Dive

### 1. Price Ingestion Pipeline

```
OANDA WebSocket → tick → Redis PUBLISH ticks
                       ↓
                candle_aggregator.py (subscribes)
                       ↓
                Builds M1, M5, M15, H1 candles
                       ↓
                Stores in PostgreSQL (candles table)
                       ↓
                Publishes "new_candle:{timeframe}:{symbol}"
                       ↓
                Strategies receive via on_candle()
```

### 2. Signal → Trade Pipeline

```
Strategy.on_candle() returns TradeSignal
            ↓
ai_trading/validators/ai_validator.py
            ↓
LLM Prompt → System prompt + Signal context + Market data
            ↓
Response: {"approved": bool, "confidence": 0.0-1.0, "reason": str}
            ↓
If approved: Create pending trade in DB
            ↓
executor.py → OANDA order
            ↓
trade_manager.py tracks position
            ↓
PositionMonitor (AI) monitors open positions every 5 min
            ↓
Action: HOLD / CLOSE / EXTEND_SL / TRAIL_STOP
```

### 3. Dashboard Real-Time Updates

```
WebSocket /ws endpoint
    ↓
Subscribes to Redis "ticks" channel
    ↓
Broadcasts JSON: {"type": "tick", "symbol": "EURUSD", "price": 1.0850}
    ↓
React Dashboard receives → Updates price displays
```

---

## Configuration Files

### feed_config.json
```json
{
  "feeds": {
    "oanda": {
      "enabled": true,
      "symbols": ["EUR_USD", "GBP_USD", "XAU_USD", "XAG_USD"],
      "account_id": "...",
      "api_key": "..."
    }
  },
  "symbols": {
    "EURUSD": {"enabled": true, "pip_value": 0.0001},
    "XAUUSD": {"enabled": true, "pip_value": 0.01, "is_metal": true},
    "XAGUSD": {"enabled": true, "pip_value": 0.001, "is_metal": true}
  }
}
```

### connections.py
```python
import redis

redis_client = redis.Redis(host='localhost', port=6379, db=0)

DB_CONFIG = {
    'host': 'localhost',
    'database': 'trading',
    'user': 'trader',
    'password': '...'
}

OANDA_API_KEY = "..."
OANDA_ACCOUNT_ID = "..."
OANDA_ENVIRONMENT = "practice"  # or "live"
```

---

## Database Schema

### Core Tables

**trades** - All trade records
```sql
id SERIAL PRIMARY KEY,
signal_id INTEGER,
strategy_name VARCHAR(255),
symbol VARCHAR(50),
direction VARCHAR(10),  -- 'long' or 'short'
status VARCHAR(50),     -- pending, approved, rejected, executed, open, closed, failed
entry_price DECIMAL(20, 10),
exit_price DECIMAL(20, 10),
stop_loss DECIMAL(20, 10),
take_profit DECIMAL(20, 10),
quantity DECIMAL(20, 8),
pnl DECIMAL(20, 4),
pnl_percent DECIMAL(10, 4),
ai_approved BOOLEAN,
ai_confidence DECIMAL(5, 4),
ai_analysis TEXT,
signal_time TIMESTAMP,
approved_time TIMESTAMP,
entry_time TIMESTAMP,
exit_time TIMESTAMP,
entry_screenshot VARCHAR(500),
exit_screenshot VARCHAR(500),
metadata JSONB
```

**candles** - OHLCV data
```sql
id SERIAL PRIMARY KEY,
symbol VARCHAR(50),
timeframe VARCHAR(10),  -- M1, M5, M15, H1, H4, D1
open_time TIMESTAMP,
close_time TIMESTAMP,
open DECIMAL(20, 10),
high DECIMAL(20, 10),
low DECIMAL(20, 10),
close DECIMAL(20, 10),
volume DECIMAL(20, 8)
```

---

## Key API Endpoints

### Engine Control
```
GET  /api/status              → Engine status, running strategies
POST /api/engine/start        → Start trading engine
POST /api/engine/stop         → Stop trading engine
```

### Strategies
```
GET  /api/strategies                    → List all strategies
POST /api/strategies/{name}/toggle      → Enable/disable
POST /api/strategies/{name}/settings    → Update max_positions, pip_multipliers
GET  /api/strategies/{name}/symbols     → Get symbol selections
POST /api/strategies/{name}/symbols     → Update symbol selections
POST /api/strategies/reload             → Hot-reload all strategies
```

### Trades & Positions
```
GET  /api/trades                    → List trades (filter: status, strategy, symbol)
GET  /api/trades/{id}               → Get specific trade
POST /api/trades/{id}/execute       → Execute pending trade
POST /api/trades/{id}/close         → Close open position
GET  /api/positions                 → List open positions from OANDA
```

### Configuration
```
GET  /api/broker                    → Get mode (paper/oanda)
POST /api/broker                    → Set mode
GET  /api/symbols                   → List active symbols
POST /api/symbol-units              → Set position size per symbol
GET  /api/ai-confidence             → Get AI threshold
POST /api/ai-confidence             → Set threshold (0.0-1.0)
GET  /api/ollama-mode               → Get Ollama mode (auto/primary/backup)
POST /api/ollama-mode               → Set mode
```

### WebSocket
```
WS /ws                              → Real-time ticks
Message: {"type": "tick", "symbol": "EURUSD", "price": 1.0850, "timestamp": "..."}
```

---

## Running the System

### Development (4 terminals)

```bash
# Terminal 1: Price feed
python data_feed.py

# Terminal 2: Main trading engine
python trading_engine.py

# Terminal 3: API server
uvicorn api:app --reload --host 0.0.0.0 --port 8000

# Terminal 4: Dashboard
cd dashboard && npm run dev
```

### Production

```bash
# Use the start script
./start.sh

# Or systemd
sudo systemctl start trading-engine
sudo systemctl start trading-api
sudo systemctl start trading-dashboard
```

---

## Common Patterns & Solutions

### Problem: AI Rejects Trades (TP too close)

**Cause**: XAGUSD range of $0.60 on $30 price = 2% distance, AI expects <1%

**Solution**: Apply `_get_atr_multiplier()`:

```python
multiplier = self._get_atr_multiplier(symbol)
adjusted_sl = raw_sl * multiplier
adjusted_tp = raw_tp * multiplier
```

### Problem: Strategy Not Loading

**Check**:
1. Class inherits `BaseStrategy`
2. Has `name` class attribute
3. Name is unique across all strategies
4. No syntax/import errors in logs

### Problem: No Price Data

**Debug**:
```bash
redis-cli ping                    # Redis running?
redis-cli hgetall latest_prices   # Any prices?
python feed_symbols.py            # Symbols configured?
```

---

## Adding a New Strategy (Step-by-Step)

1. **Create file**: `strategies/my_strategy.py`

2. **Template**:
```python
"""
MyStrategy - Short description

Longer description of strategy logic.
"""
from strategy_loader import BaseStrategy
from models import TradeSignal
from typing import Optional
from datetime import datetime

class MyStrategy(BaseStrategy):
    name = "MyStrategy"
    symbols = None
    timeframe = "M15"
    max_positions = 5
    max_positions_per_symbol = 1
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        self.fast_period = params.get('fast', 12) if params else 12
        self.slow_period = params.get('slow', 26) if params else 26
    
    def on_candle(self, symbol: str, candle: dict) -> Optional[TradeSignal]:
        history = candle.get('history')
        if not history:
            return None
        
        closes = history.get_closes(self.slow_period + 10)
        if len(closes) < self.slow_period:
            return None
        
        # Calculate indicators
        fast_sma = sum(closes[-self.fast_period:]) / self.fast_period
        slow_sma = sum(closes[-self.slow_period:]) / self.slow_period
        
        # Entry logic
        if fast_sma > slow_sma and closes[-2] <= slow_sma:
            # Golden cross entry
            entry = candle['close']
            stop = entry - (entry * 0.01)  # 1% stop
            target = entry + (entry * 0.02)  # 2% target
            
            # Apply multiplier for metals
            multiplier = self._get_atr_multiplier(symbol)
            stop = entry - ((entry - stop) * multiplier)
            target = entry + ((target - entry) * multiplier)
            
            return self.create_signal(
                symbol=symbol,
                direction="LONG",
                entry_price=entry,
                stop_loss=stop,
                take_profit=target,
                confidence=0.70,
                reason=f"Golden cross on {symbol}"
            )
        
        return None
```

3. **Strategy auto-loads** - check dashboard or `GET /api/strategies`

4. **Enable via dashboard**: Strategies page → toggle on

---

## Symbol Format Conversions

| Source | Format | Example |
|--------|--------|---------|
| OANDA API | Underscore | `EUR_USD`, `XAU_USD` |
| Internal | No separator | `EURUSD`, `XAUUSD` |
| JPY pairs | 3 decimals | `USDJPY` = 150.123 |
| Metals | 2-3 decimals | `XAUUSD` = 2050.50 |

**Use `feed_symbols.py` for conversion**:
```python
from feed_symbols import normalize_symbol, to_oanda_format

normalized = normalize_symbol("EUR_USD")  # → "EURUSD"
oanda_format = to_oanda_format("EURUSD")  # → "EUR_USD"
```

---

## Trade Status Lifecycle

```
PENDING → Signal created, awaiting AI
    ↓
APPROVED → AI validated, waiting execution
    ↓
EXECUTED → Order placed with broker
    ↓
OPEN → Position confirmed open
    ↓
CLOSED → Position closed (profit/loss recorded)

OR:

PENDING → REJECTED (AI rejected)
EXECUTED → FAILED (order error)
```

---

## Key Conventions

1. **Timestamps**: Always UTC, use `datetime.utcnow()`
2. **Symbols**: Use internal format (no underscores) in strategies
3. **Prices**: Don't round - OANDA handles precision
4. **Units**: OANDA uses units, not lots (1 lot = 100,000 units)
5. **Timeframes**: M1, M5, M15, H1, H4, D1 only
6. **Redis Keys**:
   - `latest_prices` - Hash of current prices
   - `strategy_settings:{name}` - Strategy config
   - `strategy_symbols:{name}` - Per-symbol selections
   - `symbol_units` - Per-symbol position sizes

---

## For Future AI Assistants

When working on this codebase:

1. **Read this README first** - It's the system bible
2. **Check models.py** - Understand data structures
3. **Look at existing strategies** - Follow established patterns
4. **Test with metals** - Always apply ATR multiplier for XAGUSD/XAUUSD
5. **Use the dashboard** - Most features have UI at `localhost:5173`
6. **Check logs** - `logs/` directory has detailed output
7. **Redis for state** - Check `redis-cli` for runtime state
8. **Hot reload works** - Edit strategy files, they auto-reload

**Critical files to understand**:
- `strategy_loader.py` - How strategies work
- `trading_engine.py` - System orchestration
- `models.py` - Data structures
- `oanda_broker.py` - Execution logic
- `ai_trading/validators/ai_validator.py` - AI validation

---

**Project**: orlandopirate71-star/trading-engine
**Updated**: April 2026
**Maintainer**: See GitHub repository

```bash
sudo -u postgres psql
CREATE DATABASE trading;
CREATE USER trader WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE trading TO trader;
```

### 3. Setup Redis

```bash
sudo apt install redis-server
sudo systemctl start redis
```

### 4. Setup Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gpt-oss:120b-cloud
ollama serve
```

### 5. Setup Dashboard

```bash
cd dashboard
npm install
```

### 6. Configure

```bash
cp feed_config.json.example feed_config.json
cp connections.py.example connections.py
# Edit with your credentials
```

## Running

```bash
# Terminal 1: API Server
python api.py

# Terminal 2: Feed Manager
python -m feeds.feed_manager

# Terminal 3: Dashboard
cd dashboard && npm run dev

# Terminal 4: Trading Engine
python trading_engine.py
```

Or use the start script:
```bash
./start.sh
```

## Configuration

### feed_config.json

```json
{
  "feeds": [
    {
      "type": "oanda",
      "enabled": true,
      "account_id": "YOUR_OANDA_ACCOUNT_ID",
      "api_token": "YOUR_OANDA_API_TOKEN",
      "practice": true,
      "symbols": ["EUR_USD", "GBP_USD", "XAU_USD"]
    }
  ]
}
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_AI_VALIDATOR` | `true` | Enable AI signal validation (required) |
| `BRAIN_API` | `http://192.168.0.32:8000` | Brain MCP server |

## AI Architecture

The system uses **two separate AI systems** with different endpoints:

### 1. AI Validator (Trade Signal Validation)
**Purpose**: Pre-trade validation of strategy signals before execution

**AI Endpoints**:
- **Primary**: `http://localhost:11434` (Local Ollama)
- **Backup/Cloud**: Different IP address (configured in connections.py)

**Behavior**:
- Validates each `TradeSignal` from strategies
- Returns: `{"approved": bool, "confidence": 0.0-1.0, "reason": str}`
- Falls back to cloud if localhost fails
- Configurable via dashboard: **Ollama Mode** button (AUTO/PRIMARY/BACKUP)

### 2. AI Monitor (Position Monitoring)
**Purpose**: Post-trade monitoring of open positions

**AI Endpoint**: `http://192.168.0.35:11434` (Remote Ollama server only)

**Modes** (configurable via dashboard **Monitor AI** button):
- **CLOUD**: Uses cloud Ollama model on 192.168.0.35 (gpt-oss:120b-cloud)
- **LOCAL**: Uses local LLM on 192.168.0.35 (qwen2.5:14b)
- **OFF**: Disables position monitoring completely

**Behavior**:
- Checks open positions every 5 minutes
- Returns: `{"action": "HOLD|CLOSE|EXTEND|TRAIL_STOP", "confidence": 0.0-1.0}`
- Only acts if confidence > threshold (default 0.8)
- Logs all decisions to Redis for dashboard display

### Key Differences

| Feature | AI Validator | AI Monitor |
|---------|-------------|------------|
| **Purpose** | Pre-trade validation | Post-trade monitoring |
| **Endpoint** | localhost + cloud fallback | 192.168.0.35 only |
| **Frequency** | Every signal | Every 5 minutes |
| **Models** | Cloud Ollama | Cloud/Local/OFF |
| **Dashboard Control** | Ollama Mode button | Monitor AI button |

### Configuration

**AI Validator Settings**:
```python
# connections.py
OLLAMA_BASE = "http://localhost:11434"
OLLAMA_BACKUP_BASE = "http://[cloud-ip]:11434"
```

**AI Monitor Settings**:
```python
# ai_trading/ai_client.py
_monitor_local_base = "http://192.168.0.35:11434"
_monitor_local_model = "qwen2.5:14b"  # LOCAL mode
# Cloud mode uses default model on same endpoint
```

**Dashboard Controls**:
- **Ollama Mode**: Controls AI Validator fallback behavior
- **Monitor AI**: Controls position monitoring (CLOUD/LOCAL/OFF)
- **AI Confidence**: Minimum confidence threshold for validator (0.0-1.0)
- **Monitor Confidence**: Minimum confidence threshold for monitor actions (0.0-1.0)

### AI Activity Logging

All AI decisions are logged to Redis and displayed in the dashboard at `http://localhost:3000/ai-activity`:
- Signal validations (approved/rejected)
- Position monitoring decisions (hold/close/trail)
- Confidence scores and reasoning
- Latency metrics
- Provider information (cloud/local/disabled)

## Creating Strategies

Create a `.py` file in `strategies/`:

```python
from strategy_loader import BaseStrategy
from indicators import Indicators
from datetime import datetime
from typing import Optional
from models import TradeSignal

class MyStrategy(BaseStrategy):
    name = "MyStrategy"
    symbols = ["EURUSD"]

    def __init__(self, params=None):
        super().__init__(params)
        self.ind = Indicators(max_history=200)

    def on_tick(self, symbol, price, timestamp):
        self.ind.add(price)
        if self.ind.count < 50:
            return None

        rsi = self.ind.rsi(14)
        if rsi and rsi < 30 and self.ind.is_crossover(9, 21):
            return self.create_signal(
                symbol=symbol,
                direction="LONG",
                entry_price=price,
                stop_loss=price * 0.98,
                take_profit=price * 1.04,
                confidence=0.7,
                reason=f"RSI oversold ({rsi:.1f}) + EMA crossover"
            )
        return None
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ai-activity` | GET | AI validation/monitoring events |
| `/api/positions` | GET | Open positions |
| `/api/trades` | GET | Trade history |
| `/api/strategies` | GET | Strategy list |
| `/api/system/status` | GET | System health |
| `/api/auto-trade` | POST | Toggle auto-trading |
| `/api/validator-mode` | GET | Returns `{"mode": "ai_validator"}` |

Dashboard: http://localhost:3000
API Docs: http://localhost:8000/docs

## File Structure

```
trading_engine/
├── trading_engine.py         # Main engine
├── strategy_loader.py        # Hot-reload strategies
├── executor.py               # Trade execution
├── indicators.py             # Technical indicators
├── screenshot.py             # Chart screenshots
├── models.py                 # Data models
├── connections.py             # Redis/PostgreSQL connections
├── api.py                    # FastAPI backend
├── feed_config.json          # Feed credentials
├── ai_trading/               # AI validation system
│   ├── ai_client.py          # Ollama/Anthropic client
│   ├── brain_client.py       # Brain MCP integration
│   ├── prompts.py            # AI prompts
│   └── validators/
│       ├── ai_validator.py   # Engine interface
│       ├── signal_validator.py
│       └── position_monitor.py
├── feeds/                    # Data feeds
├── strategies/               # Trading strategies
├── screenshots/              # Trade screenshots
├── logs/                    # Service logs
└── dashboard/               # React frontend
```

## Troubleshooting

### AI Validator Errors
- Ensure Ollama is running: `curl http://localhost:11434/api/tags`
- Or set `ANTHROPIC_API_KEY` for Anthropic fallback

### Redis Connection Error
```bash
sudo systemctl start redis
```

### Dashboard Proxy Error
Ensure `dashboard/vite.config.js` uses `127.0.0.1` not `localhost`.
