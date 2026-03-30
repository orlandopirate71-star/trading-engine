#!/usr/bin/env python3
"""
View Strategy Performance - Simple script to view which strategies are performing best.
Usage: python view_strategy_performance.py [days]
"""
import sys
from datetime import datetime, timedelta
from connections import get_db_connection


def view_performance(days=7):
    """Display strategy performance metrics."""
    conn = get_db_connection()
    cur = conn.cursor()
    
    period_end = datetime.utcnow()
    period_start = period_end - timedelta(days=days)
    
    print(f"\n{'='*100}")
    print(f"STRATEGY PERFORMANCE - Last {days} Days")
    print(f"Period: {period_start.strftime('%Y-%m-%d %H:%M')} to {period_end.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*100}\n")
    
    # Get unique strategies from trades
    cur.execute("""
        SELECT DISTINCT strategy_name FROM trades
        WHERE signal_time >= %s
        ORDER BY strategy_name
    """, (period_start,))
    
    strategies = [row[0] for row in cur.fetchall() if row[0]]
    
    if not strategies:
        print("No strategy activity in this period.")
        return
    
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
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "avg_pnl": avg_pnl,
            "max_pnl": max_pnl,
            "min_pnl": min_pnl,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss
        })
    
    # Sort by total PnL
    results.sort(key=lambda x: x["total_pnl"], reverse=True)
    
    # Display results
    print(f"{'Strategy':<30} {'Trades':<8} {'W/L':<10} {'Win%':<7} {'Total PnL':<13} {'Avg PnL':<11} {'P.Factor':<10}")
    print(f"{'-'*30} {'-'*8} {'-'*10} {'-'*7} {'-'*13} {'-'*11} {'-'*10}")
    
    for r in results:
        strategy_name = r["strategy"][:28]
        trades = r["total_trades"]
        wl = f"{r['wins']}/{r['losses']}"
        win_pct = f"{r['win_rate']:.1f}%"
        total_pnl = f"${r['total_pnl']:.2f}"
        avg_pnl = f"${r['avg_pnl']:.2f}"
        pf = f"{r['profit_factor']:.2f}"
        
        # Color code PnL
        pnl_color = ""
        if r["total_pnl"] > 0:
            pnl_color = "\033[92m"  # Green
        elif r["total_pnl"] < 0:
            pnl_color = "\033[91m"  # Red
        reset = "\033[0m"
        
        print(f"{strategy_name:<30} {trades:<8} {wl:<10} {win_pct:<7} {pnl_color}{total_pnl:<13}{reset} {avg_pnl:<11} {pf:<10}")
    
    # Summary
    print(f"\n{'-'*100}")
    total_pnl_all = sum(r["total_pnl"] for r in results)
    total_trades_all = sum(r["total_trades"] for r in results)
    total_wins = sum(r["wins"] for r in results)
    total_losses = sum(r["losses"] for r in results)
    overall_win_rate = (total_wins / total_trades_all * 100) if total_trades_all > 0 else 0
    
    print(f"TOTAL: {len(results)} strategies | {total_trades_all} trades ({total_wins}W/{total_losses}L) | Win Rate: {overall_win_rate:.1f}% | Total PnL: ${total_pnl_all:.2f}")
    print(f"{'='*100}\n")
    
    cur.close()
    conn.close()


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    view_performance(days)
