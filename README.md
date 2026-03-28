# Trading Station

A modular Python trading platform with AI-powered signal validation and a real-time React dashboard.

## Features

- **Hot-Reload Strategies**: Drop Python strategy files into `strategies/` folder - they're loaded automatically
- **AI Validator**: Local LLM validation via Ollama (with Anthropic fallback)
- **Position Monitor**: Real-time AI monitoring of open positions (HOLD/CLOSE/EXTEND/TRAIL_STOP)
- **Multi-Source Feeds**: OANDA, MT4, TradingView webhooks, Binance, Polygon, and more
- **Technical Indicators**: SMA, EMA, RSI, MACD, Bollinger Bands, ATR, ADX, etc.
- **Paper Trading**: Test strategies with simulated execution
- **Real-time Dashboard**: React-based UI with AI Activity monitoring
- **Screenshot Capture**: Automatic chart screenshots at trade open/close
- **Brain Integration**: Strategy/market context from knowledge base

## Architecture

```
Feeds → Redis (ticks) → TradingEngine → Strategies → Signals
    ↓
SignalValidator → Brain (context) → AI Client (Ollama/Anthropic)
    ↓
[APPROVED] → Executor → Trade
    ↓
PositionMonitor → Brain → AI Client → Dashboard (AIActivity)
```

## Prerequisites

- Python 3.10+
- PostgreSQL
- Redis
- Ollama (with gpt-oss:120b-cloud model) OR Anthropic API key
- Node.js 18+ (for dashboard)
- Brain MCP server (optional, for context)

## Installation

### 1. Clone and setup Python environment

```bash
cd trading_engine
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Setup PostgreSQL

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

## AI System

The `ai_trading/` module provides:

1. **Signal Validator** - Pre-trade validation with confidence scoring, risk analysis, and market alignment
2. **Position Monitor** - Post-trade monitoring that recommends HOLD/CLOSE/EXTEND/TRAIL_STOP actions
3. **Brain Client** - Queries knowledge base for strategy rules and market context

AI Activity is logged to Redis and displayed in the dashboard at `http://localhost:3000/ai-activity`.

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
