"""
Feed Symbols - Loads active symbols from feed_config.json.
Provides a single source of truth for which symbols strategies should trade.
"""
import json
from pathlib import Path
from typing import List, Set


def get_active_symbols() -> List[str]:
    """
    Get all symbols from enabled feeds in feed_config.json.
    Normalizes symbol format (e.g., EUR_USD -> EURUSD).
    """
    config_path = Path(__file__).parent / "feed_config.json"
    
    if not config_path.exists():
        print("[FeedSymbols] feed_config.json not found")
        return []
    
    try:
        with open(config_path) as f:
            config = json.load(f)
        
        symbols: Set[str] = set()
        
        for feed in config.get("feeds", []):
            if not feed.get("enabled", False):
                continue
            
            feed_symbols = feed.get("symbols", [])
            for symbol in feed_symbols:
                # Normalize: EUR_USD -> EURUSD
                normalized = symbol.replace("_", "")
                symbols.add(normalized)
        
        return sorted(list(symbols))
    
    except Exception as e:
        print(f"[FeedSymbols] Error loading config: {e}")
        return []


def get_feed_info() -> dict:
    """
    Get information about active feeds and their symbols.
    Returns dict with feed type, enabled status, and symbols.
    """
    config_path = Path(__file__).parent / "feed_config.json"
    
    if not config_path.exists():
        return {"feeds": [], "active_symbols": []}
    
    try:
        with open(config_path) as f:
            config = json.load(f)
        
        feeds = []
        all_symbols: Set[str] = set()
        
        for feed in config.get("feeds", []):
            feed_type = feed.get("type", "unknown")
            enabled = feed.get("enabled", False)
            raw_symbols = feed.get("symbols", [])
            
            # Normalize symbols
            normalized = [s.replace("_", "") for s in raw_symbols]
            
            feeds.append({
                "type": feed_type,
                "enabled": enabled,
                "symbols": normalized,
                "symbol_count": len(normalized)
            })
            
            if enabled:
                all_symbols.update(normalized)
        
        return {
            "feeds": feeds,
            "active_symbols": sorted(list(all_symbols)),
            "active_count": len(all_symbols)
        }
    
    except Exception as e:
        print(f"[FeedSymbols] Error: {e}")
        return {"feeds": [], "active_symbols": [], "error": str(e)}


# Cache for performance
_cached_symbols: List[str] = None
_cache_time: float = 0


def get_active_symbols_cached(cache_seconds: float = 60.0) -> List[str]:
    """Get active symbols with caching."""
    import time
    global _cached_symbols, _cache_time
    
    now = time.time()
    if _cached_symbols is None or (now - _cache_time) > cache_seconds:
        _cached_symbols = get_active_symbols()
        _cache_time = now
    
    return _cached_symbols


# For convenience - can be imported directly
ACTIVE_SYMBOLS = get_active_symbols()
