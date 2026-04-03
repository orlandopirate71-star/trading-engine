"""
Candle Store - Persists candles to database for AI validation.
Provides historical candle retrieval for AI analysis.
"""
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from connections import redis_client, get_db_connection


def init_candle_table():
    """Create the market_candles table if it doesn't exist."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS market_candles (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(20) NOT NULL,
            timeframe VARCHAR(5) NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume BIGINT DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(symbol, timeframe, timestamp)
        )
    """)
    # Index for fast lookups
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_candles_symbol_timeframe
        ON market_candles(symbol, timeframe, timestamp DESC)
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("[CandleStore] Database table initialized")


class CandleStore:
    """
    Persists candles to database and retrieves them for AI validation.
    Uses the existing candle_aggregator for tick aggregation - this class only
    handles DB persistence and retrieval.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._enabled = True

    def on_candle_close(self, candle, history=None):
        """Callback from candle_aggregator when a candle closes."""
        if not self._enabled:
            return
        try:
            self._write_candle(candle)
        except Exception as e:
            print(f"[CandleStore] Error writing candle: {e}")

    def _write_candle(self, candle):
        """Write a single candle to the database."""
        with self._lock:
            conn = get_db_connection()
            cur = conn.cursor()
            try:
                cur.execute("""
                    INSERT INTO market_candles (symbol, timeframe, timestamp, open, high, low, close, volume)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (symbol, timeframe, timestamp)
                    DO UPDATE SET open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                                  close = EXCLUDED.close, volume = EXCLUDED.volume
                """, (
                    candle.symbol,
                    candle.timeframe.name if hasattr(candle.timeframe, 'name') else str(candle.timeframe),
                    candle.timestamp,
                    candle.open,
                    candle.high,
                    candle.low,
                    candle.close,
                    int(candle.volume or 0)
                ))
                conn.commit()
            except Exception as e:
                print(f"[CandleStore] DB write error: {e}")
            finally:
                cur.close()
                conn.close()

    def get_recent_candles(self, symbol: str, timeframe: str, count: int = 20) -> List[dict]:
        """Get recent candles for AI validation."""
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT timestamp, open, high, low, close, volume
                FROM market_candles
                WHERE symbol = %s AND timeframe = %s
                ORDER BY timestamp DESC
                LIMIT %s
            """, (symbol, timeframe, count))
            rows = cur.fetchall()
            cur.close()
            conn.close()

            # Return newest last for AI ( chronological order)
            candles = []
            for row in reversed(rows):
                candles.append({
                    "timestamp": row[0].isoformat() if isinstance(row[0], datetime) else row[0],
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": int(row[5])
                })
            return candles
        except Exception as e:
            print(f"[CandleStore] Failed to get candles: {e}")
            return []

    def cleanup_old_candles(self, days: int = 14):
        """Delete candles older than specified days."""
        with self._lock:
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cutoff = datetime.utcnow() - timedelta(days=days)
                cur.execute("""
                    DELETE FROM market_candles WHERE timestamp < %s
                """, (cutoff,))
                deleted = cur.rowcount
                conn.commit()
                cur.close()
                conn.close()
                if deleted > 0:
                    print(f"[CandleStore] Cleaned up {deleted} old candles")
                return deleted
            except Exception as e:
                print(f"[CandleStore] Cleanup error: {e}")
                return 0

    def cleanup_single_day(self, days_to_keep: int = 14):
        """
        Delete exactly one day of old candles (the day that's days_to_keep+1 days old).
        This maintains a rolling 14-day window where we delete only the oldest day each run.
        
        Example: With days_to_keep=14, we delete candles from 15 days ago,
        keeping candles from day 14 through today.
        """
        with self._lock:
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                
                # Calculate the day to delete (e.g., 15 days ago)
                now = datetime.utcnow()
                delete_day_start = now - timedelta(days=days_to_keep + 1)
                delete_day_end = delete_day_start + timedelta(days=1)
                
                cur.execute("""
                    DELETE FROM market_candles 
                    WHERE timestamp >= %s AND timestamp < %s
                """, (delete_day_start, delete_day_end))
                deleted = cur.rowcount
                conn.commit()
                cur.close()
                conn.close()
                if deleted > 0:
                    print(f"[CandleStore] Deleted {deleted} candles from {delete_day_start.date()} (rolling retention)")
                return deleted
            except Exception as e:
                print(f"[CandleStore] Daily cleanup error: {e}")
                return 0

    def get_date_range(self) -> dict:
        """Get the date range of candles in the database."""
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT MIN(timestamp), MAX(timestamp), COUNT(*) 
                FROM market_candles
            """)
            row = cur.fetchone()
            cur.close()
            conn.close()
            return {
                "oldest": row[0].isoformat() if row[0] else None,
                "newest": row[1].isoformat() if row[1] else None,
                "total_candles": row[2] or 0
            }
        except Exception as e:
            print(f"[CandleStore] Failed to get date range: {e}")
            return {"oldest": None, "newest": None, "total_candles": 0}

    def get_candle_count(self) -> int:
        """Get total candle count in database."""
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM market_candles")
            count = cur.fetchone()[0]
            cur.close()
            conn.close()
            return count
        except:
            return 0

    def set_enabled(self, enabled: bool):
        """Enable/disable candle persistence."""
        self._enabled = enabled


# Singleton
_candle_store: Optional[CandleStore] = None


def get_candle_store() -> CandleStore:
    global _candle_store
    if _candle_store is None:
        _candle_store = CandleStore()
    return _candle_store


def init_candle_store() -> CandleStore:
    """Initialize candle store and create table."""
    global _candle_store
    init_candle_table()
    _candle_store = CandleStore()
    return _candle_store
