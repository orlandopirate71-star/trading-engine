"""
Strategy Performance Tracking - Track and analyze strategy performance metrics.
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from connections import get_db_connection


class StrategyPerformance:
    """Track and analyze performance metrics for trading strategies."""
    
    def __init__(self):
        self._init_table()
    
    def _init_table(self):
        """Create strategy_performance table if it doesn't exist."""
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS strategy_performance (
                id SERIAL PRIMARY KEY,
                strategy_name VARCHAR(100) NOT NULL,
                period_start TIMESTAMP NOT NULL,
                period_end TIMESTAMP NOT NULL,
                total_signals INTEGER DEFAULT 0,
                total_trades INTEGER DEFAULT 0,
                winning_trades INTEGER DEFAULT 0,
                losing_trades INTEGER DEFAULT 0,
                total_pnl DECIMAL(15, 2) DEFAULT 0,
                avg_pnl DECIMAL(15, 2) DEFAULT 0,
                max_pnl DECIMAL(15, 2) DEFAULT 0,
                min_pnl DECIMAL(15, 2) DEFAULT 0,
                win_rate DECIMAL(5, 2) DEFAULT 0,
                avg_win DECIMAL(15, 2) DEFAULT 0,
                avg_loss DECIMAL(15, 2) DEFAULT 0,
                profit_factor DECIMAL(10, 2) DEFAULT 0,
                sharpe_ratio DECIMAL(10, 4) DEFAULT 0,
                max_drawdown DECIMAL(15, 2) DEFAULT 0,
                ai_approval_rate DECIMAL(5, 2) DEFAULT 0,
                avg_confidence DECIMAL(5, 2) DEFAULT 0,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Create index on strategy_name and period
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_strategy_performance_name 
            ON strategy_performance(strategy_name, period_end DESC)
        """)
        
        conn.commit()
        cur.close()
        conn.close()
    
    def update_performance(self, strategy_name: str, days: int = 7):
        """
        Calculate and update performance metrics for a strategy.
        
        Args:
            strategy_name: Name of the strategy
            days: Number of days to analyze (default 7)
        """
        conn = get_db_connection()
        cur = conn.cursor()
        
        period_end = datetime.utcnow()
        period_start = period_end - timedelta(days=days)
        
        # Get all trades for this strategy in the period
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
            WHERE strategy = %s 
            AND status = 'closed'
            AND closed_at >= %s
            AND closed_at <= %s
        """, (strategy_name, period_start, period_end))
        
        trade_stats = cur.fetchone()
        
        # Get signal stats
        cur.execute("""
            SELECT 
                COUNT(*) as total_signals,
                SUM(CASE WHEN openclaw_approved = true THEN 1 ELSE 0 END) as approved,
                AVG(confidence) as avg_confidence
            FROM signals
            WHERE strategy_name = %s
            AND timestamp >= %s
            AND timestamp <= %s
        """, (strategy_name, period_start, period_end))
        
        signal_stats = cur.fetchone()
        
        # Calculate metrics
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
        
        total_signals = signal_stats[0] or 0
        approved = signal_stats[1] or 0
        avg_confidence = float(signal_stats[2] or 0)
        
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        ai_approval_rate = (approved / total_signals * 100) if total_signals > 0 else 0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0
        
        # Insert or update performance record
        cur.execute("""
            INSERT INTO strategy_performance (
                strategy_name, period_start, period_end,
                total_signals, total_trades, winning_trades, losing_trades,
                total_pnl, avg_pnl, max_pnl, min_pnl,
                win_rate, avg_win, avg_loss, profit_factor,
                ai_approval_rate, avg_confidence, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
            )
            ON CONFLICT DO NOTHING
        """, (
            strategy_name, period_start, period_end,
            total_signals, total_trades, wins, losses,
            total_pnl, avg_pnl, max_pnl, min_pnl,
            win_rate, avg_win, avg_loss, profit_factor,
            ai_approval_rate, avg_confidence
        ))
        
        conn.commit()
        cur.close()
        conn.close()
    
    def get_all_strategies_performance(self, days: int = 7) -> List[Dict]:
        """
        Get performance metrics for all strategies.
        
        Args:
            days: Number of days to analyze
            
        Returns:
            List of strategy performance dictionaries
        """
        conn = get_db_connection()
        cur = conn.cursor()
        
        period_end = datetime.utcnow()
        period_start = period_end - timedelta(days=days)
        
        # Get unique strategies
        cur.execute("""
            SELECT DISTINCT strategy_name FROM trades
            WHERE created_at >= %s
            UNION
            SELECT DISTINCT strategy_name FROM signals
            WHERE timestamp >= %s
        """, (period_start, period_start))
        
        strategies = [row[0] for row in cur.fetchall()]
        
        results = []
        for strategy in strategies:
            if not strategy:
                continue
                
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
                AND created_at >= %s
            """, (strategy, period_start))
            
            trade_stats = cur.fetchone()
            
            # Get signal stats
            cur.execute("""
                SELECT 
                    COUNT(*) as total_signals,
                    SUM(CASE WHEN openclaw_approved = true THEN 1 ELSE 0 END) as approved,
                    SUM(CASE WHEN openclaw_approved = false THEN 1 ELSE 0 END) as rejected,
                    AVG(confidence) as avg_confidence
                FROM signals
                WHERE strategy_name = %s
                AND timestamp >= %s
            """, (strategy, period_start))
            
            signal_stats = cur.fetchone()
            
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
            
            total_signals = signal_stats[0] or 0
            approved = signal_stats[1] or 0
            rejected = signal_stats[2] or 0
            avg_confidence = float(signal_stats[3] or 0)
            
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
            ai_approval_rate = (approved / total_signals * 100) if total_signals > 0 else 0
            profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0
            
            results.append({
                "strategy": strategy,
                "total_signals": total_signals,
                "approved_signals": approved,
                "rejected_signals": rejected,
                "ai_approval_rate": round(ai_approval_rate, 2),
                "avg_confidence": round(avg_confidence, 2),
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
        
        return results


def get_strategy_performance():
    """Get singleton instance of StrategyPerformance."""
    return StrategyPerformance()
