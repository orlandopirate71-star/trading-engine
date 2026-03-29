"""
Main Trading Engine - Orchestrates all components.
"""
import time
import json
import threading
from datetime import datetime
from typing import Optional, Dict, List
from dataclasses import asdict

from connections import redis_client, get_db_connection
from models import Trade, TradeSignal, TradeStatus, TradeDirection, init_database
from strategy_loader import get_strategy_loader, BaseStrategy
from executor import get_executor
from screenshot import get_screenshot_service
from candle_aggregator import get_candle_aggregator, Candle, CandleHistory, Timeframe
from candle_store import init_candle_store, get_candle_store
from oanda_broker import OandaBroker


def is_market_open() -> bool:
    """Check if forex market is currently open (weekdays 22:00-21:00 UTC)."""
    now = datetime.utcnow()
    utc_hour = now.hour
    utc_day = now.weekday()  # 0=Monday, 6=Sunday

    # Weekend - market closed
    if utc_day == 6:  # Saturday
        return False
    if utc_day == 0 and utc_hour < 22:  # Sunday before 22:00
        return False

    # Active trading: 22:00-21:00 UTC (Sydney/Asian session through NY close)
    # Low activity: 21:00-22:00 UTC ( NY close through London open gap)
    if utc_hour >= 22 or utc_hour < 6:
        return True

    # Night lull / weekend crossover - consider closed
    return False


class TradingEngine:
    """
    Main trading engine that coordinates:
    - Strategy execution
    - AI validation (replaces legacy OpenClaw)
    - Trade execution
    - Screenshot capture
    - Database persistence
    """
    
    STATE_KEY = "engine_state"  # Redis key for persisted state
    
    def __init__(
        self,
        strategies_dir: str = "strategies",
        auto_trade: bool = False,
        require_approval: bool = True
    ):
        self.strategies_dir = strategies_dir
        
        # Load persisted state or use defaults
        saved_state = self._load_state()
        self.auto_trade = saved_state.get("auto_trade", auto_trade)
        self.require_approval = saved_state.get("require_approval", require_approval)
        
        # Broker mode: "paper" or "oanda"
        self.broker_mode = saved_state.get("broker_mode", "oanda")
        
        print(f"[ENGINE] Loaded state: auto_trade={self.auto_trade}, require_approval={self.require_approval}, broker={self.broker_mode}")
        
        # Initialize components
        self.strategy_loader = get_strategy_loader(strategies_dir)

        # Use AI Validator
        import os
        use_ai = os.environ.get("USE_AI_VALIDATOR", "true").lower() == "true"

        if use_ai:
            try:
                from ai_trading.validators.ai_validator import init_ai_validator
                self.validator = init_ai_validator(
                    auto_trade=self.auto_trade,
                    require_approval=self.require_approval
                )
                print("[ENGINE] Using AI Validator")
            except Exception as e:
                print(f"[ENGINE] AI Validator init error: {e}")
                raise RuntimeError("AI Validator failed to initialize - cannot continue without AI validation")
        else:
            raise RuntimeError("USE_AI_VALIDATOR=false is not supported - AI validation is required")

        # Initialize AI Position Monitor
        self.position_monitor = None
        if use_ai:
            try:
                from ai_trading.validators.position_monitor import PositionMonitor
                self.position_monitor = PositionMonitor(
                    check_interval=30.0,
                    confidence_threshold=0.7,
                    enabled=True
                )
                print("[ENGINE] AI Position Monitor initialized")
            except Exception as e:
                print(f"[ENGINE] Position Monitor init error: {e}")

        self.executor = get_executor()
        self.screenshot_service = get_screenshot_service()

        # Initialize OANDA broker
        self.oanda_broker = None
        self._init_oanda_broker()
        
        # Candle aggregator for time-based OHLC
        self.candle_aggregator = get_candle_aggregator(
            timeframes=[Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.H1]
        )
        self.candle_aggregator.on_candle_close = self._on_candle_close

        # Candle store for DB persistence (for AI validation)
        self.candle_store = init_candle_store()
        self.candle_aggregator.add_candle_callback(self.candle_store.on_candle_close)
        
        # State
        self.running = False
        self.last_prices: Dict[str, float] = {}
        self.pending_trades: List[Trade] = []
        self._lock = threading.Lock()
        
        # Redis subscription
        self.pubsub = None
        self.subscriber_thread = None
        
        # Initialize database
        self._init_db()
    
    def _load_state(self) -> dict:
        """Load persisted engine state from Redis."""
        try:
            state_json = redis_client.get(self.STATE_KEY)
            if state_json:
                return json.loads(state_json)
        except Exception as e:
            print(f"[ENGINE] Failed to load state: {e}")
        return {}
    
    def _save_state(self):
        """Save engine state to Redis for persistence."""
        try:
            state = {
                "auto_trade": self.auto_trade,
                "require_approval": self.require_approval,
                "broker_mode": self.broker_mode
            }
            redis_client.set(self.STATE_KEY, json.dumps(state))
        except Exception as e:
            print(f"[ENGINE] Failed to save state: {e}")

    def _init_oanda_broker(self):
        """Initialize OANDA broker from feed config."""
        try:
            import json as json_module
            from pathlib import Path
            config_path = Path(__file__).parent / "feed_config.json"
            with open(config_path) as f:
                config = json_module.load(f)
            
            for feed in config.get("feeds", []):
                if feed.get("type") == "oanda" and feed.get("enabled"):
                    self.oanda_broker = OandaBroker(
                        account_id=feed["account_id"],
                        api_token=feed["api_token"],
                        practice=feed.get("practice", True)
                    )
                    if self.oanda_broker.connect():
                        print(f"[ENGINE] OANDA broker connected (practice={feed.get('practice', True)})")
                    else:
                        print("[ENGINE] OANDA broker connection failed")
                        self.oanda_broker = None
                    break
        except Exception as e:
            print(f"[ENGINE] Failed to init OANDA broker: {e}")
            self.oanda_broker = None
    
    def set_broker_mode(self, mode: str):
        """Set broker mode: 'paper' or 'oanda'."""
        if mode not in ["paper", "oanda"]:
            raise ValueError("Broker mode must be 'paper' or 'oanda'")
        
        if mode == "oanda" and self.oanda_broker is None:
            raise ValueError("OANDA broker not available")
        
        self.broker_mode = mode
        self._save_state()
        print(f"[ENGINE] Broker mode set to: {mode}")
    
    def _init_db(self):
        """Initialize database schema."""
        try:
            conn = get_db_connection()
            init_database(conn)
            conn.close()
            print("[ENGINE] Database initialized")
        except Exception as e:
            print(f"[ENGINE] Database init error: {e}")
    
    def start(self):
        """Start the trading engine."""
        print("[ENGINE] Starting trading engine...")

        # NOTE: Don't clear latest_prices here - feeds are the source of truth
        # Clearing it causes feed status to fail after engine restart
        # redis_client.delete("latest_prices")

        # Set running FIRST before starting subscriber
        self.running = True
        
        # Load strategies
        self.strategy_loader.load_all()
        self.strategy_loader.start_watching()
        
        # Connect executor
        self.executor.connect()
        
        # Start Redis subscriber
        self._start_subscriber()

        print("[ENGINE] Trading engine started")
        print(f"[ENGINE] Auto-trade: {self.auto_trade}")
        print(f"[ENGINE] Require approval: {self.require_approval}")

        # Start AI Position Monitor if available
        if self.position_monitor and self.broker_mode == "oanda":
            self.position_monitor.start(
                get_positions_fn=self._get_open_positions_for_monitor,
                action_callback=self._on_position_monitor_action
            )
            threading.Thread(target=self._position_monitor_loop, daemon=True).start()

        # Sync OANDA positions on startup and start background sync thread
        if self.broker_mode == "oanda" and self.oanda_broker:
            self._sync_oanda_positions()
            threading.Thread(target=self._oanda_sync_loop, daemon=True).start()

        # Start candle cleanup thread (runs daily)
        threading.Thread(target=self._candle_cleanup_loop, daemon=True).start()

    def _position_monitor_loop(self):
        """Background thread for position monitor decisions."""
        while self.running:
            time.sleep(60)  # Check every minute
            if self.running and self.position_monitor:
                try:
                    # Position monitor checks positions via callback
                    pass
                except Exception as e:
                    print(f"[ENGINE] Position monitor error: {e}")

    def _get_open_positions_for_monitor(self) -> List[dict]:
        """Get open positions for the AI position monitor."""
        positions = []
        try:
            # Get positions from OANDA
            if self.oanda_broker:
                oanda_trades = self.oanda_broker.get_open_trades()
                for t in oanda_trades:
                    positions.append({
                        "trade_id": f"oanda_{t['id']}",
                        "symbol": t["instrument"].replace("_", ""),
                        "direction": "long" if t["units"] > 0 else "short",
                        "entry_price": t["price"],
                        "current_price": t["price"],
                        "quantity": abs(t["units"]),
                        "unrealized_pnl": t.get("unrealized_pnl", 0),
                        "stop_loss": t.get("stop_loss"),
                        "take_profit": t.get("take_profit")
                    })
        except Exception as e:
            print(f"[ENGINE] Error getting positions for monitor: {e}")
        return positions

    def _on_position_monitor_action(self, position: dict, result):
        """Handle AI position monitor decisions."""
        # Skip logging when market is closed - no trading decisions needed
        if not is_market_open():
            return

        try:
            action = result.action.value
            print(f"[ENGINE] AI Monitor: {position.get('symbol')} -> {action} (confidence: {result.confidence:.2f})")
            print(f"[ENGINE] Reasoning: {result.reasoning[:150]}...")

            # Log to Redis for AI Activity dashboard
            try:
                import json
                event = {
                    "type": "position_monitor",
                    "symbol": position.get("symbol"),
                    "action": action,
                    "confidence": result.confidence,
                    "reasoning": result.reasoning[:300],
                    "urgency": result.urgency,
                    "new_stop_loss": result.new_stop_loss,
                    "new_take_profit": result.new_take_profit,
                    "provider": result.provider,
                    "latency_ms": result.latency_ms
                }
                redis_client.lpush("ai_activity_log", json.dumps(event))
                redis_client.ltrim("ai_activity_log", 0, 499)
            except Exception as log_err:
                pass  # Don't fail for logging errors

            if not self.position_monitor.should_act(result):
                return

            trade_id = position.get("trade_id")

            if action == "CLOSE":
                self._ai_close_position(trade_id, result)
            elif action == "TRAIL_STOP" and result.new_stop_loss:
                self._ai_adjust_stop(trade_id, result.new_stop_loss, result)
            elif action == "ADJUST_TP" and result.new_take_profit:
                self._ai_adjust_tp(trade_id, result.new_take_profit, result)
            # EXTEND would require adding to position - not implemented yet

        except Exception as e:
            print(f"[ENGINE] Error handling monitor action: {e}")

    def _ai_close_position(self, trade_id: str, result):
        """Close position based on AI monitor decision."""
        try:
            if trade_id.startswith("oanda_"):
                oanda_trade_id = trade_id.replace("oanda_", "")
                close_result = self.oanda_broker.close_trade(oanda_trade_id)
                if close_result.success:
                    print(f"[ENGINE] AI closed OANDA trade {oanda_trade_id}")
        except Exception as e:
            print(f"[ENGINE] Error closing position: {e}")

    def _ai_adjust_stop(self, trade_id: str, new_stop: float, result):
        """Adjust stop loss based on AI monitor decision."""
        try:
            if trade_id.startswith("oanda_"):
                oanda_trade_id = trade_id.replace("oanda_", "")
                mod_result = self.oanda_broker.modify_trade(oanda_trade_id, stop_loss=new_stop)
                if mod_result.success:
                    print(f"[ENGINE] AI adjusted SL for OANDA trade {oanda_trade_id} to {new_stop}")
                    # Update in DB
                    self._update_trade_stop(oanda_trade_id, new_stop)
                else:
                    print(f"[ENGINE] AI SL adjustment failed: {mod_result.error}")
        except Exception as e:
            print(f"[ENGINE] Error adjusting stop: {e}")

    def _ai_adjust_tp(self, trade_id: str, new_tp: float, result):
        """Adjust take profit based on AI monitor decision."""
        try:
            if trade_id.startswith("oanda_"):
                oanda_trade_id = trade_id.replace("oanda_", "")
                mod_result = self.oanda_broker.modify_trade(oanda_trade_id, take_profit=new_tp)
                if mod_result.success:
                    print(f"[ENGINE] AI adjusted TP for OANDA trade {oanda_trade_id} to {new_tp}")
                    # Update in DB
                    self._update_trade_tp(oanda_trade_id, new_tp)
                else:
                    print(f"[ENGINE] AI TP adjustment failed: {mod_result.error}")
        except Exception as e:
            print(f"[ENGINE] Error adjusting take profit: {e}")

    def _update_trade_stop(self, trade_id: str, new_stop: float):
        """Update stop loss in database."""
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                UPDATE trades SET stop_loss = %s, trailing_stop_trigger = %s
                WHERE metadata->>'oanda_order_id' = %s AND status = 'open'
            """, (new_stop, None, trade_id))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[ENGINE] Error updating trade stop in DB: {e}")

    def _update_trade_tp(self, trade_id: str, new_tp: float):
        """Update take profit in database."""
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                UPDATE trades SET take_profit = %s
                WHERE metadata->>'oanda_order_id' = %s AND status = 'open'
            """, (new_tp, trade_id))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[ENGINE] Error updating trade TP in DB: {e}")

    def _oanda_sync_loop(self):
        """Background thread to periodically sync OANDA positions."""
        while self.running:
            time.sleep(30)  # Sync every 30 seconds
            if self.running and self.broker_mode == "oanda" and self.oanda_broker:
                try:
                    self._sync_oanda_positions()
                except Exception as e:
                    print(f"[ENGINE] OANDA sync error: {e}")

    def _candle_cleanup_loop(self):
        """Background thread to periodically clean up old candles."""
        while self.running:
            time.sleep(86400)  # Run once per day
            if self.running:
                try:
                    self.candle_store.cleanup_old_candles(days=14)
                except Exception as e:
                    print(f"[ENGINE] Candle cleanup error: {e}")

    def _sync_oanda_positions(self):
        """Sync open positions with OANDA - close trades in DB that are closed on OANDA."""
        if not self.oanda_broker:
            return

        try:
            # Get all open positions from OANDA
            oanda_positions = self.oanda_broker.get_all_positions()
            oanda_symbols = set(oanda_positions.keys())

            # Get all open trades from DB that might be OANDA trades
            # (open status AND have oanda_order_id in metadata)
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT id, symbol, direction, quantity, entry_price, metadata FROM trades
                WHERE status = 'open'
            """)
            db_trades = cur.fetchall()

            for trade_id, symbol, direction, quantity, entry_price, metadata in db_trades:
                # Check if this is an OANDA trade (has oanda_order_id in metadata)
                is_oanda_trade = metadata and metadata.get('oanda_order_id')

                # If OANDA doesn't have this symbol open and it's an OANDA trade, close it
                if is_oanda_trade and symbol not in oanda_symbols:
                    print(f"[ENGINE] OANDA sync: Trade {trade_id} ({symbol}) closed on OANDA, updating DB")
                    # Get current price for P&L calculation
                    current_price = self.last_prices.get(symbol)

                    # Convert to float for calculation (DB returns Decimal)
                    quantity = float(quantity) if quantity else 0
                    entry_price = float(entry_price) if entry_price else 0

                    # Calculate P&L
                    pnl = 0
                    pnl_percent = 0
                    if entry_price and current_price:
                        if direction == "long":
                            pnl = (current_price - entry_price) * quantity
                        else:
                            pnl = (entry_price - current_price) * quantity
                        pnl_percent = (pnl / (entry_price * quantity)) * 100 if entry_price * quantity != 0 else 0

                    # Update trade as closed
                    cur.execute("""
                        UPDATE trades
                        SET status = 'closed',
                            exit_price = %s,
                            exit_time = %s,
                            pnl = %s,
                            pnl_percent = %s
                        WHERE id = %s
                    """, (current_price, datetime.utcnow(), pnl, pnl_percent, trade_id))

            conn.commit()
            cur.close()
            conn.close()
            print(f"[ENGINE] OANDA sync complete: {len(oanda_symbols)} open positions")
        except Exception as e:
            print(f"[ENGINE] OANDA sync failed: {e}")
    
    def stop(self):
        """Stop the trading engine."""
        print("[ENGINE] Stopping trading engine...")
        self.running = False
        
        self.strategy_loader.stop_watching()
        self.screenshot_service.cleanup()
        
        if self.pubsub:
            self.pubsub.unsubscribe()
        
        print("[ENGINE] Trading engine stopped")
    
    def _start_subscriber(self):
        """Start Redis price subscriber."""
        self.pubsub = redis_client.pubsub()
        self.pubsub.subscribe("ticks")
        
        def listen():
            print("[ENGINE] Subscriber thread started, listening...")
            tick_count = 0
            try:
                for message in self.pubsub.listen():
                    if not self.running:
                        print("[ENGINE] Subscriber stopping - running=False")
                        break
                    if message["type"] == "message":
                        try:
                            data = message["data"]
                            # Convert bytes to string if needed
                            if isinstance(data, bytes):
                                data = data.decode('utf-8')
                            # Handle both old format (just price) and new format (JSON with symbol)
                            if isinstance(data, str) and data.startswith("{"):
                                tick = json.loads(data)
                                symbol = tick.get("symbol", "BTCUSDT")
                                price = float(tick.get("price", 0))
                            else:
                                # Legacy format - just a price number
                                symbol = "BTCUSDT"
                                price = float(data)
                            
                            self._on_tick(symbol, price)
                            tick_count += 1
                            if tick_count == 1:
                                print(f"[ENGINE] First tick received: {symbol} @ {price}")
                            elif tick_count % 1000 == 0:
                                print(f"[ENGINE] Processed {tick_count} ticks")
                        except Exception as e:
                            print(f"[ENGINE] Tick error: {e}")
            except Exception as e:
                print(f"[ENGINE] Subscriber thread error: {e}")
        
        self.subscriber_thread = threading.Thread(target=listen, daemon=True)
        self.subscriber_thread.start()
        print("[ENGINE] Subscribed to price feed")
    
    def _on_tick(self, symbol: str, price: float):
        """Handle incoming price tick."""
        timestamp = datetime.utcnow()

        # Update last price
        old_price = self.last_prices.get(symbol)
        self.last_prices[symbol] = price

        # Feed tick to candle aggregator (will trigger on_candle_close when candles complete)
        self.candle_aggregator.on_tick(symbol, price, timestamp=timestamp)

        # Skip strategy processing if price hasn't changed
        if old_price == price:
            return

        # Check if market is open - skip signal generation when market is closed
        if not is_market_open():
            return

        # Check stop loss / take profit on open positions
        close_results = self.executor.check_stop_loss_take_profit(self.last_prices)
        for result in close_results:
            self._on_position_closed(result)
        
        # Run strategies on tick
        strategies = self.strategy_loader.get_enabled_strategies()
        debug_count = 0
        for strategy in strategies:
            try:
                # Only call strategy if it's interested in this symbol
                strategy_symbols = getattr(strategy, 'active_symbols', None) or getattr(strategy, 'symbols', [])
                if strategy_symbols and symbol not in strategy_symbols:
                    continue

                signal = strategy.on_tick(symbol, price, timestamp)
                if signal:
                    self._process_signal(signal, strategy)
                    debug_count += 1
                    print(f"[ENGINE] Signal generated: {strategy.name} {symbol} @ {price}")
            except Exception as e:
                import traceback
                print(f"[ENGINE] Strategy {strategy.name} error: {e}")
                traceback.print_exc()
        if debug_count > 0:
            print(f"[ENGINE] Processed {debug_count} signal(s) for {symbol} @ {price}")
    
    def _on_candle_close(self, candle: Candle, history: CandleHistory):
        """Handle candle close - run candle-based strategies."""
        # Debug: log candle close
        print(f"[ENGINE] Candle closed: {candle.symbol} {candle.timeframe.name} @ {candle.close}")

        # Build candle dict for strategies
        candle_data = {
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
            "timestamp": candle.timestamp,
            "timeframe": candle.timeframe.name,
            "history": history  # Full history for indicators
        }

        # Run strategies on candle close
        strategies = self.strategy_loader.get_enabled_strategies()
        for strategy in strategies:
            try:
                # Check if strategy wants this timeframe
                strategy_tf = getattr(strategy, 'timeframe', 'M5')
                if strategy_tf == candle.timeframe.name or strategy_tf == candle.timeframe:
                    signal = strategy.on_candle(candle.symbol, candle_data)
                    if signal:
                        self._process_signal(signal, strategy)
                        print(f"[ENGINE] Candle signal: {strategy.name} {candle.symbol}")
            except Exception as e:
                print(f"[ENGINE] Strategy {strategy.name} candle error: {e}")
    
    def _process_signal(self, signal: TradeSignal, strategy=None):
        """Process a trade signal through the pipeline."""
        print(f"[ENGINE] Signal from {signal.strategy_name}: {signal.direction.value} {signal.symbol} @ {signal.entry_price}")
        
        # Check position limits before processing
        if strategy and not self._check_position_limits(strategy, signal.symbol):
            print(f"[ENGINE] Position limit reached for {signal.strategy_name} - skipping signal")
            return
        
        # Save signal to database
        signal_id = self._save_signal(signal)
        signal.id = signal_id
        
        # Check if validator is available
        if self.validator is None:
            print(f"[ENGINE] No validator configured - skipping signal")
            return
        
        # Validate with AI
        result = self.validator.validate_signal(
            signal,
            market_context=self._get_market_context(signal.symbol)
        )
        
        if result is None:
            print(f"[ENGINE] Validator returned None - skipping signal")
            return
        
        should_execute, trade = result
        
        # Save trade record
        trade_id = self._save_trade(trade)
        trade.id = trade_id
        
        if trade.openclaw_approved:
            print(f"[ENGINE] AI APPROVED: {trade.openclaw_analysis[:100]}...")

            # Capture entry screenshot (returns list of {timeframe, path} dicts)
            screenshot_results = self.screenshot_service.capture_tradingview(
                signal.symbol,
                trade_id,
                "entry"
            )
            # Store first screenshot path as string
            if screenshot_results and len(screenshot_results) > 0:
                trade.entry_screenshot = screenshot_results[0].get("path")
                print(f"[ENGINE] Screenshot captured: {trade.entry_screenshot}")
            else:
                trade.entry_screenshot = None
                print(f"[ENGINE] Screenshot capture failed/empty")
            self._update_trade(trade)

            if should_execute:
                # Check symbol units - skip if no units configured
                symbol_units = self._get_symbol_units()
                units = symbol_units.get(signal.symbol)
                if units is None or units <= 0:
                    print(f"[ENGINE] No units configured for {signal.symbol} - trade will be saved but not executed")
                    trade.status = TradeStatus.PENDING
                    trade.metadata["reason"] = "no_units_configured"
                    self._update_trade(trade)
                    with self._lock:
                        self.pending_trades.append(trade)
                    return

                # Execute the trade based on broker mode
                if self.broker_mode == "oanda" and self.oanda_broker:
                    trade = self._execute_oanda_trade(trade, signal)
                else:
                    trade = self.executor.execute_trade(trade)
                self._update_trade(trade)
                print(f"[ENGINE] Trade executed ({self.broker_mode}): {trade.status}")
            else:
                # Add to pending for manual execution
                with self._lock:
                    self.pending_trades.append(trade)
                print(f"[ENGINE] Trade pending manual execution")
        else:
            print(f"[ENGINE] AI REJECTED: {trade.openclaw_analysis[:100]}...")
            trade.status = TradeStatus.REJECTED
            self._update_trade(trade)
    
    def _execute_oanda_trade(self, trade: Trade, signal: TradeSignal) -> Trade:
        """Execute trade on OANDA broker."""
        print(f"[ENGINE] _execute_oanda_trade called: symbol={trade.symbol}, direction={trade.direction}")
        if not self.oanda_broker:
            print(f"[ENGINE] OANDA broker not available!")
            trade.status = TradeStatus.FAILED
            trade.metadata["error"] = "OANDA broker not available"
            return trade

        # Determine order side
        side = "BUY" if trade.direction == TradeDirection.LONG else "SELL"

        # Get units from symbol units map
        symbol_units = self._get_symbol_units()
        units = symbol_units.get(signal.symbol, 100)
        if units <= 0:
            units = 100  # Default fallback
        print(f"[ENGINE] Placing OANDA order: {side} {units} {trade.symbol} @ {trade.entry_price}, SL={trade.stop_loss}, TP={trade.take_profit}")

        # Place order on OANDA
        result = self.oanda_broker.place_market_order(
            symbol=trade.symbol,
            side=side,
            quantity=units,
            stop_loss=trade.stop_loss,
            take_profit=trade.take_profit
        )

        print(f"[ENGINE] OANDA result: success={result.success}, filled_price={getattr(result, 'filled_price', 'N/A')}")
        if result.success:
            trade.status = TradeStatus.OPEN
            trade.entry_price = result.filled_price
            trade.quantity = result.filled_quantity
            trade.fees = result.fees
            trade.entry_time = result.timestamp
            trade.metadata["oanda_order_id"] = result.order_id
            trade.metadata["broker"] = "oanda"
            
            print(f"[OANDA] Executed {side} {units} {trade.symbol} @ {result.filled_price}")
        else:
            trade.status = TradeStatus.FAILED
            trade.metadata["error"] = result.error
            print(f"[OANDA] Order failed: {result.error}")
        
        return trade
    
    def _check_position_limits(self, strategy, symbol: str) -> bool:
        """Check if strategy can open a new position based on limits."""
        max_positions = getattr(strategy, 'max_positions', 0)
        max_per_symbol = getattr(strategy, 'max_positions_per_symbol', 0)

        print(f"[ENGINE] Position check: strategy={strategy.name}, max_pos={max_positions}, max_per_sym={max_per_symbol}, symbol={symbol}")

        # 0 means unlimited
        if max_positions == 0 and max_per_symbol == 0:
            return True

        # Count open positions for this strategy
        conn = get_db_connection()
        cur = conn.cursor()

        # Count total open positions for strategy
        cur.execute("""
            SELECT COUNT(*) FROM trades
            WHERE strategy_name = %s AND status = 'open'
        """, (strategy.name,))
        total_open = cur.fetchone()[0]

        # Count open positions for this symbol
        cur.execute("""
            SELECT COUNT(*) FROM trades
            WHERE strategy_name = %s AND symbol = %s AND status = 'open'
        """, (strategy.name, symbol))
        symbol_open = cur.fetchone()[0]

        cur.close()
        conn.close()

        print(f"[ENGINE] Position check: total_open={total_open}, symbol_open={symbol_open}")

        # Check limits
        if max_positions > 0 and total_open >= max_positions:
            print(f"[ENGINE] Position limit BLOCKED: total {total_open} >= {max_positions}")
            return False

        if max_per_symbol > 0 and symbol_open >= max_per_symbol:
            print(f"[ENGINE] Position limit BLOCKED: symbol {symbol_open} >= {max_per_symbol}")
            return False

        return True
    
    def _on_position_closed(self, result: dict):
        """Handle position close event."""
        trade_id = result["trade_id"]
        
        # Capture exit screenshot
        # Need to get symbol from trade
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT symbol FROM trades WHERE id = %s", (trade_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        
        if row:
            symbol = row[0]
            screenshot_path = self.screenshot_service.capture_tradingview(
                symbol,
                trade_id,
                "exit"
            )
            result["exit_screenshot"] = screenshot_path
        
        # Update trade in database
        self._close_trade(trade_id, result)
        
        print(f"[ENGINE] Position closed: Trade {trade_id}, P&L: {result['pnl']:.4f}")
    
    def _get_market_context(self, symbol: str) -> dict:
        """Get market context for AI analysis."""
        price = self.last_prices.get(symbol, 0)
        return {
            "current_price": price,
            "change_24h": None,  # Would need historical data
            "volume": None,
            "rsi": None,
            "trend": None
        }

    def _get_symbol_units(self) -> Dict[str, float]:
        """Get symbol units from Redis."""
        from connections import redis_client
        units = redis_client.hgetall("symbol_units") or {}
        result = {}
        for symbol, val in units.items():
            try:
                fval = float(val)
                if fval > 0:
                    result[symbol] = fval
            except (ValueError, TypeError):
                pass
        return result
    
    def _save_signal(self, signal: TradeSignal) -> int:
        """Save trade signal to database."""
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO trade_signals 
            (strategy_name, symbol, direction, entry_price, stop_loss, take_profit, 
             confidence, reason, timestamp, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            signal.strategy_name,
            signal.symbol,
            signal.direction.value,
            signal.entry_price,
            signal.stop_loss,
            signal.take_profit,
            signal.confidence,
            signal.reason,
            signal.timestamp,
            json.dumps(signal.metadata)
        ))
        
        signal_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        
        return signal_id
    
    def _save_trade(self, trade: Trade) -> int:
        """Save trade to database."""
        conn = get_db_connection()
        cur = conn.cursor()
        
        status = trade.status.value if isinstance(trade.status, TradeStatus) else trade.status
        direction = trade.direction.value if isinstance(trade.direction, TradeDirection) else trade.direction
        
        cur.execute("""
            INSERT INTO trades 
            (signal_id, strategy_name, symbol, direction, status, entry_price, 
             stop_loss, take_profit, openclaw_approved, openclaw_analysis, 
             openclaw_confidence, signal_time, approved_time, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            trade.signal_id,
            trade.strategy_name,
            trade.symbol,
            direction,
            status,
            trade.entry_price,
            trade.stop_loss,
            trade.take_profit,
            trade.openclaw_approved,
            trade.openclaw_analysis,
            trade.openclaw_confidence,
            trade.signal_time,
            trade.approved_time,
            json.dumps(trade.metadata)
        ))
        
        trade_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        
        return trade_id
    
    def _update_trade(self, trade: Trade):
        """Update trade in database."""
        conn = get_db_connection()
        cur = conn.cursor()
        
        status = trade.status.value if isinstance(trade.status, TradeStatus) else trade.status
        
        cur.execute("""
            UPDATE trades SET
                status = %s,
                entry_price = %s,
                quantity = %s,
                fees = %s,
                entry_time = %s,
                entry_screenshot = %s,
                metadata = %s
            WHERE id = %s
        """, (
            status,
            trade.entry_price,
            trade.quantity,
            trade.fees,
            trade.entry_time,
            trade.entry_screenshot,
            json.dumps(trade.metadata),
            trade.id
        ))
        
        conn.commit()
        cur.close()
        conn.close()
    
    def _close_trade(self, trade_id: int, result: dict):
        """Close a trade in database."""
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            UPDATE trades SET
                status = 'closed',
                exit_price = %s,
                pnl = %s,
                pnl_percent = %s,
                exit_time = %s,
                exit_screenshot = %s,
                metadata = metadata || %s
            WHERE id = %s
        """, (
            result["exit_price"],
            result["pnl"],
            result["pnl_percent"],
            result["exit_time"],
            result.get("exit_screenshot"),
            json.dumps({"close_reason": result["close_reason"]}),
            trade_id
        ))
        
        # Remove from positions table
        cur.execute("DELETE FROM positions WHERE trade_id = %s", (trade_id,))
        
        conn.commit()
        cur.close()
        conn.close()
    
    # === Public API ===
    
    def execute_pending_trade(self, trade_id: int) -> Optional[Trade]:
        """Manually execute a pending trade."""
        with self._lock:
            trade = None
            for t in self.pending_trades:
                if t.id == trade_id:
                    trade = t
                    break

            if not trade:
                return None

            self.pending_trades.remove(trade)

        # Execute based on broker mode
        if self.broker_mode == "oanda" and self.oanda_broker:
            trade = self._execute_oanda_trade(trade, None)
        else:
            trade = self.executor.execute_trade(trade)
        self._update_trade(trade)
        return trade
    
    def close_position(self, trade_id: int) -> Optional[dict]:
        """Manually close a position."""
        result = self.executor.close_position(trade_id, "manual")
        if result:
            self._on_position_closed(result)
        return result
    
    def get_status(self) -> dict:
        """Get engine status."""
        return {
            "running": self.running,
            "auto_trade": self.auto_trade,
            "require_approval": self.require_approval,
            "validator": "ai_validator",
            "strategies": self.strategy_loader.list_strategies(),
            "open_positions": len(self.executor.get_open_positions()),
            "pending_trades": len(self.pending_trades),
            "balance": self.executor.get_balance(),
            "last_prices": self.last_prices
        }
    
    def set_auto_trade(self, enabled: bool):
        """Enable/disable auto trading."""
        self.auto_trade = enabled
        if self.validator:
            self.validator.set_auto_trade(enabled)
        self._save_state()
    
    def set_require_approval(self, required: bool):
        """Enable/disable AI approval."""
        self.require_approval = required
        if self.validator:
            self.validator.set_require_approval(required)
        self._save_state()


# Singleton instance
_engine: Optional[TradingEngine] = None


def get_engine(
    strategies_dir: str = "strategies",
    auto_trade: bool = False,
    require_approval: bool = True
) -> TradingEngine:
    """Get or create the trading engine singleton."""
    global _engine
    if _engine is None:
        _engine = TradingEngine(strategies_dir, auto_trade, require_approval)
    return _engine


if __name__ == "__main__":
    import signal
    import sys
    
    engine = get_engine(auto_trade=False, require_approval=True)
    
    def shutdown(sig, frame):
        print("\nShutting down...")
        engine.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    
    engine.start()
    
    # Keep running
    while engine.running:
        time.sleep(1)
