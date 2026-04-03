"""
Hot-reloading strategy loader.
Watches the strategies directory and reloads strategies when files change.
"""
import os
import sys
import time
import importlib.util
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Any, Protocol
from dataclasses import dataclass
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent

from models import TradeSignal, TradeDirection
from connections import redis_client
from feed_symbols import get_active_symbols_cached
import inspect


class StrategyProtocol(Protocol):
    """Protocol that all strategies must implement."""
    name: str
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        """Called on each price tick. Return a TradeSignal or None."""
        ...
    
    def on_candle(self, symbol: str, candle: dict) -> Optional[TradeSignal]:
        """Called on each new candle. Return a TradeSignal or None."""
        ...


class BaseStrategy:
    """Base class for all strategies."""
    name: str = "BaseStrategy"
    symbols: list = None  # None means use all active symbols from feed_config.json
    timeframe: str = "M5"  # Default timeframe for candle-based strategies (M1, M5, M15, H1, H4, D1)
    max_positions: int = 0  # Maximum total concurrent positions for this strategy (0 = unlimited)
    max_positions_per_symbol: int = 1  # Maximum positions per symbol (1 = one trade per symbol per strategy)

    # Pip multipliers for symbols that need expanded trade spaces (e.g., metals with high volume)
    # Override in subclass or via params. Format: {"XAUUSD": 3.0, "XAGUSD": 2.0}
    pip_multipliers: dict = None

    # Trailing stop settings (in profit $ amount)
    trailing_stop_trigger: float = 0  # 0 = disabled
    trailing_stop_lock: float = 0

    @property
    def active_symbols(self) -> list:
        """Get symbols this strategy trades. If symbols is None, uses all active feed symbols."""
        if self.symbols is None:
            return get_active_symbols_cached()
        return self.symbols

    def _get_pip_multiplier(self, symbol: str) -> float:
        """Get the pip multiplier for a symbol. Returns 1.0 if no multiplier defined."""
        if self.pip_multipliers and symbol in self.pip_multipliers:
            return self.pip_multipliers[symbol]
        return 1.0

    def _apply_pip_multiplier(self, symbol: str, stop_loss: float, take_profit: float, entry_price: float):
        """
        Apply pip multiplier to SL/TP distances.
        For metals (gold/silver), this expands the trade space by multiplying the distance from entry.
        Returns (adjusted_stop_loss, adjusted_take_profit).
        """
        multiplier = self._get_pip_multiplier(symbol)
        if multiplier <= 1.0:
            return stop_loss, take_profit

        sl_distance = entry_price - stop_loss if stop_loss else 0
        tp_distance = take_profit - entry_price if take_profit else 0

        # Expand distances by the multiplier
        new_sl_distance = sl_distance * multiplier
        new_tp_distance = tp_distance * multiplier

        new_stop_loss = entry_price - new_sl_distance if stop_loss else None
        new_take_profit = entry_price + new_tp_distance if take_profit else None

        return new_stop_loss, new_take_profit

    def __init__(self, params: dict = None):
        self.params = params or {}
        self.positions = {}
        self.last_signal_time = {}
        # Allow params to override max_positions
        self.max_positions = self.params.get('max_positions', self.__class__.max_positions)
        self.max_positions_per_symbol = self.params.get('max_positions_per_symbol', self.__class__.max_positions_per_symbol)
        # Allow params to override pip_multipliers, with defaults for metals
        if self.params.get('pip_multipliers'):
            self.pip_multipliers = self.params.get('pip_multipliers')
        elif self.pip_multipliers is None:
            # Default multipliers for metals - expand trade spaces for high-volume instruments
            self.pip_multipliers = {"XAUUSD": 3.0, "XAGUSD": 2.0}
        # Trailing stop settings
        self.trailing_stop_trigger = self.params.get('trailing_stop_trigger', self.__class__.trailing_stop_trigger)
        self.trailing_stop_lock = self.params.get('trailing_stop_lock', self.__class__.trailing_stop_lock)
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        """Override this method to implement tick-based logic."""
        return None
    
    def on_candle(self, symbol: str, candle: dict) -> Optional[TradeSignal]:
        """
        Override this method to implement candle-based logic.
        
        Args:
            symbol: Trading symbol
            candle: Dict with keys:
                - open, high, low, close, volume: OHLCV data
                - timestamp: Candle open time
                - timeframe: Timeframe name (M1, M5, M15, H1, etc.)
                - history: CandleHistory object with methods:
                    - get_closes(count) -> List[float]
                    - get_highs(count) -> List[float]
                    - get_lows(count) -> List[float]
                    - get_opens(count) -> List[float]
                    - get_candles(count) -> List[Candle]
        """
        return None
    
    def create_signal(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_loss: float = None,
        take_profit: float = None,
        trailing_stop_trigger: float = None,
        trailing_stop_lock: float = None,
        confidence: float = 0.5,
        reason: str = "",
        apply_multiplier: bool = True
    ) -> TradeSignal:
        """Helper to create a trade signal.

        Args:
            apply_multiplier: If True (default), automatically applies pip multipliers
                             for symbols like gold/silver that need expanded trade spaces.
        """
        # Apply pip multiplier for metals/high-volume symbols
        if apply_multiplier and (stop_loss or take_profit):
            stop_loss, take_profit = self._apply_pip_multiplier(symbol, stop_loss, take_profit, entry_price)

        # Use strategy's trailing stop if not provided in signal
        ts_trigger = trailing_stop_trigger if trailing_stop_trigger is not None else self.trailing_stop_trigger
        ts_lock = trailing_stop_lock if trailing_stop_lock is not None else self.trailing_stop_lock
        # Only use if both are set and > 0
        if ts_trigger <= 0:
            ts_trigger = None
        if ts_lock <= 0:
            ts_lock = None

        # Normalize direction - accept both "LONG"/"BUY" and "SHORT"/"SELL"
        direction_upper = direction.upper()
        if direction_upper in ("LONG", "BUY"):
            trade_direction = TradeDirection.LONG
        elif direction_upper in ("SHORT", "SELL"):
            trade_direction = TradeDirection.SHORT
        else:
            # Default to LONG for unrecognized directions
            print(f"[Strategy] Warning: unrecognized direction '{direction}', defaulting to LONG")
            trade_direction = TradeDirection.LONG

        return TradeSignal(
            strategy_name=self.name,
            symbol=symbol,
            direction=trade_direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trailing_stop_trigger=ts_trigger,
            trailing_stop_lock=ts_lock,
            confidence=confidence,
            reason=reason,
            timestamp=datetime.utcnow()
        )


@dataclass
class LoadedStrategy:
    """Container for a loaded strategy."""
    name: str
    instance: BaseStrategy
    file_path: str
    last_modified: float
    enabled: bool = True
    error: Optional[str] = None
    source_code: Optional[str] = None  # Store strategy source for AI validation


class StrategyFileHandler(FileSystemEventHandler):
    """Handles file system events for strategy files."""
    
    def __init__(self, loader: 'StrategyLoader'):
        self.loader = loader
    
    def on_modified(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith('.py') and not event.src_path.endswith('__init__.py'):
            print(f"[LOADER] Strategy modified: {event.src_path}")
            self.loader.reload_strategy(event.src_path)
    
    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith('.py') and not event.src_path.endswith('__init__.py'):
            print(f"[LOADER] New strategy detected: {event.src_path}")
            self.loader.load_strategy(event.src_path)


class StrategyLoader:
    """
    Manages loading and hot-reloading of trading strategies.
    """
    
    STRATEGY_STATE_KEY = "strategy_states"  # Redis hash for strategy enabled states
    
    def __init__(self, strategies_dir: str = "strategies"):
        self.strategies_dir = Path(strategies_dir)
        self.strategies: Dict[str, LoadedStrategy] = {}
        self.observer: Optional[Observer] = None
        self._lock = threading.Lock()
        
        # Create strategies directory if it doesn't exist
        self.strategies_dir.mkdir(exist_ok=True)
        
        # Create __init__.py if it doesn't exist
        init_file = self.strategies_dir / "__init__.py"
        if not init_file.exists():
            init_file.write_text("# Strategies package\n")
    
    def load_strategy(self, file_path: str) -> Optional[LoadedStrategy]:
        """Load a single strategy from a file."""
        file_path = Path(file_path)
        
        if not file_path.exists():
            print(f"[LOADER] Strategy file not found: {file_path}")
            return None
        
        try:
            # Load the module
            spec = importlib.util.spec_from_file_location(
                file_path.stem,
                file_path
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[file_path.stem] = module
            spec.loader.exec_module(module)
            
            # Find the strategy class (subclass of BaseStrategy or has required methods)
            strategy_class = None
            for name, obj in vars(module).items():
                if (isinstance(obj, type) and 
                    obj is not BaseStrategy and
                    hasattr(obj, 'on_tick') and
                    hasattr(obj, 'name')):
                    strategy_class = obj
                    break
            
            if strategy_class is None:
                print(f"[LOADER] No valid strategy class found in {file_path}")
                return None
            
            # Instantiate the strategy
            instance = strategy_class()

            # Load saved symbol selections from Redis
            saved_symbols = redis_client.smembers(f"strategy_symbols:{instance.name}")
            if saved_symbols:
                instance.symbols = list(saved_symbols)
                print(f"[LOADER] Loaded symbol selection for {instance.name}: {len(instance.symbols)} symbols")

            # Read source code for AI validation
            source_code = None
            try:
                source_code = Path(file_path).read_text()
            except Exception as e:
                print(f"[LOADER] Could not read source for {file_path}: {e}")

            # Check if strategy was previously disabled (persisted state)
            saved_state = redis_client.hget(self.STRATEGY_STATE_KEY, instance.name)
            is_enabled = saved_state != "disabled" if saved_state else True

            loaded = LoadedStrategy(
                name=instance.name,
                instance=instance,
                file_path=str(file_path),
                last_modified=file_path.stat().st_mtime,
                enabled=is_enabled,
                source_code=source_code
            )
            
            with self._lock:
                self.strategies[instance.name] = loaded
            
            print(f"[LOADER] Loaded strategy: {instance.name} from {file_path}")
            return loaded
            
        except Exception as e:
            print(f"[LOADER] Error loading strategy {file_path}: {e}")
            # Store the error for debugging
            loaded = LoadedStrategy(
                name=file_path.stem,
                instance=None,
                file_path=str(file_path),
                last_modified=file_path.stat().st_mtime,
                enabled=False,
                error=str(e)
            )
            with self._lock:
                self.strategies[file_path.stem] = loaded
            return None
    
    def reload_strategy(self, file_path: str) -> Optional[LoadedStrategy]:
        """Reload a strategy from file."""
        file_path = Path(file_path)
        
        # Find and remove old version
        with self._lock:
            to_remove = None
            for name, strat in self.strategies.items():
                if strat.file_path == str(file_path):
                    to_remove = name
                    break
            if to_remove:
                del self.strategies[to_remove]
        
        # Remove from sys.modules to force reimport
        if file_path.stem in sys.modules:
            del sys.modules[file_path.stem]
        
        return self.load_strategy(file_path)
    
    def load_all(self):
        """Load all strategies from the strategies directory."""
        print(f"[LOADER] Scanning {self.strategies_dir} for strategies...")
        
        for file_path in self.strategies_dir.glob("*.py"):
            if file_path.name.startswith("_"):
                continue
            self.load_strategy(file_path)
        
        print(f"[LOADER] Loaded {len([s for s in self.strategies.values() if s.enabled])} strategies")
    
    def start_watching(self):
        """Start watching for file changes."""
        self.observer = Observer()
        handler = StrategyFileHandler(self)
        self.observer.schedule(handler, str(self.strategies_dir), recursive=False)
        self.observer.start()
        print(f"[LOADER] Watching {self.strategies_dir} for changes...")
    
    def stop_watching(self):
        """Stop watching for file changes."""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            print("[LOADER] Stopped watching for changes")
    
    def get_enabled_strategies(self) -> list:
        """Get all enabled strategy instances."""
        with self._lock:
            return [s.instance for s in self.strategies.values() 
                    if s.enabled and s.instance is not None]
    
    def get_strategy(self, name: str) -> Optional[BaseStrategy]:
        """Get a specific strategy by name."""
        with self._lock:
            if name in self.strategies and self.strategies[name].enabled:
                return self.strategies[name].instance
        return None

    def get_strategy_source(self, name: str) -> Optional[str]:
        """Get the source code for a strategy."""
        with self._lock:
            if name in self.strategies:
                return self.strategies[name].source_code
        return None
    
    def enable_strategy(self, name: str):
        """Enable a strategy and persist state."""
        with self._lock:
            if name in self.strategies:
                self.strategies[name].enabled = True
                redis_client.hset(self.STRATEGY_STATE_KEY, name, "enabled")
                print(f"[LOADER] Enabled strategy: {name}")
    
    def disable_strategy(self, name: str):
        """Disable a strategy and persist state."""
        with self._lock:
            if name in self.strategies:
                self.strategies[name].enabled = False
                redis_client.hset(self.STRATEGY_STATE_KEY, name, "disabled")
                print(f"[LOADER] Disabled strategy: {name}")
    
    def list_strategies(self) -> list:
        """List all loaded strategies with their status."""
        with self._lock:
            result = []
            for s in self.strategies.values():
                info = {
                    "name": s.name,
                    "file": s.file_path,
                    "enabled": s.enabled,
                    "error": s.error,
                    "last_modified": datetime.fromtimestamp(s.last_modified).isoformat()
                }
                # Add position limits if instance exists
                if s.instance:
                    info["max_positions"] = getattr(s.instance, 'max_positions', 1)
                    info["max_positions_per_symbol"] = getattr(s.instance, 'max_positions_per_symbol', 1)
                    info["symbols"] = getattr(s.instance, 'active_symbols', [])
                    info["uses_all_symbols"] = s.instance.symbols is None
                    info["pip_multipliers"] = getattr(s.instance, 'pip_multipliers', None)
                    info["trailing_stop_trigger"] = getattr(s.instance, 'trailing_stop_trigger', 0)
                    info["trailing_stop_lock"] = getattr(s.instance, 'trailing_stop_lock', 0)
                    # Extract docstring for description
                    if s.instance.__class__.__doc__:
                        info["description"] = s.instance.__class__.__doc__.strip()
                result.append(info)
            return result


# Singleton instance
_loader: Optional[StrategyLoader] = None


def get_strategy_loader(strategies_dir: str = "strategies") -> StrategyLoader:
    """Get or create the strategy loader singleton."""
    global _loader
    if _loader is None:
        _loader = StrategyLoader(strategies_dir)
    return _loader
