"""
Base class for all data feeds.
"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Callable, List, Optional
from dataclasses import dataclass
import threading


@dataclass
class Tick:
    """A single price tick."""
    symbol: str
    price: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume: Optional[float] = None
    timestamp: datetime = None
    source: str = ""
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


class BaseFeed(ABC):
    """Base class for all data feeds."""
    
    name: str = "BaseFeed"
    
    def __init__(self, symbols: List[str], on_tick: Callable[[Tick], None] = None):
        self.symbols = symbols
        self.on_tick = on_tick
        self.running = False
        self._thread: Optional[threading.Thread] = None
    
    @abstractmethod
    def connect(self) -> bool:
        """Connect to the data source."""
        pass
    
    @abstractmethod
    def disconnect(self):
        """Disconnect from the data source."""
        pass
    
    @abstractmethod
    def _run(self):
        """Main loop - implement in subclass."""
        pass
    
    def start(self):
        """Start the feed in a background thread."""
        if self.running:
            return
        
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"[{self.name}] Started for {len(self.symbols)} symbols")
    
    def stop(self):
        """Stop the feed."""
        self.running = False
        self.disconnect()
        if self._thread:
            self._thread.join(timeout=5)
        print(f"[{self.name}] Stopped")
    
    def emit_tick(self, tick: Tick):
        """Emit a tick to the callback."""
        if self.on_tick:
            self.on_tick(tick)
