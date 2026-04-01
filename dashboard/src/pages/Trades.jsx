import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { 
  TrendingUp, 
  TrendingDown, 
  Filter,
  Search,
  ChevronLeft,
  ChevronRight,
  CheckCircle,
  XCircle,
  Clock,
  Activity,
  Eye
} from 'lucide-react'
import { format } from 'date-fns'

const StatusBadge = ({ status }) => {
  const styles = {
    pending: 'bg-gray-700 text-gray-300',
    approved: 'bg-yellow-900 text-yellow-400',
    rejected: 'bg-red-900 text-red-400',
    executed: 'bg-blue-900 text-blue-400',
    open: 'bg-purple-900 text-purple-400',
    closed: 'bg-green-900 text-green-400',
    failed: 'bg-red-900 text-red-400'
  }

  return (
    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${styles[status] || styles.pending}`}>
      {status?.toUpperCase()}
    </span>
  )
}

const formatPrice = (price, symbol) => {
  if (price == null) return '-'
  // Forex pairs (EURUSD, GBPUSD, etc.) need 5 decimal places
  // Metals (XAUUSD, XAGUSD) need 2 decimal places
  const isForex = symbol && !symbol.startsWith('XAU') && !symbol.startsWith('XAG')
  const decimals = isForex ? 5 : 2
  return price.toFixed(decimals)
}

export default function Trades() {
  const [trades, setTrades] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState({
    status: '',
    strategy: '',
    symbol: ''
  })
  const [strategies, setStrategies] = useState([])
  const [brokerInfo, setBrokerInfo] = useState(null)
  const limit = 20

  useEffect(() => {
    fetchTrades()
  }, [page, filters])

  useEffect(() => {
    fetchTrades()
    fetchBrokerInfo()
  }, [])

  useEffect(() => {
    fetchStrategies()
  }, [])

  const fetchBrokerInfo = async () => {
    try {
      const res = await fetch('/api/broker')
      setBrokerInfo(await res.json())
    } catch (err) {
      console.error('Failed to fetch broker info:', err)
    }
  }

  const fetchStrategies = async () => {
    try {
      const res = await fetch('/api/strategies')
      setStrategies(await res.json())
    } catch (err) {
      console.error('Failed to fetch strategies:', err)
    }
  }

  const fetchTrades = async () => {
    setLoading(true)
    try {
      // Check if in OANDA mode
      const brokerRes = await fetch('/api/broker')
      const broker = await brokerRes.json()
      
      if (broker.mode === 'oanda' && broker.oanda_available) {
        // Fetch OANDA trade history
        const res = await fetch('/api/oanda/trade-history?limit=50')
        const data = await res.json()
        // Transform OANDA trades to match expected format
        // Sort by time descending (most recent first)
        const sortedOandaTrades = [...data.trades].sort((a, b) => new Date(b.time) - new Date(a.time))
        const oandaTrades = sortedOandaTrades.map(t => {
          // These are ORDER_FILL transactions from OANDA - they're all closed trades
          const isClosed = true
          const isWin = t.realized_pnl > 0
          // Calculate P&L percentage based on notional value
          const notional = t.entry_price * t.units
          const pnlPercent = notional > 0 ? (t.realized_pnl / notional) * 100 : 0

          // Determine exit reason for display
          let exitReason = ''
          if (t.reason.includes('TAKE_PROFIT')) exitReason = ' (TP)'
          else if (t.reason.includes('STOP_LOSS')) exitReason = ' (SL)'
          else if (t.reason.includes('MARKET_ORDER_TRADE_CLOSE')) exitReason = ' (Closed)'
          else exitReason = t.reason ? ` (${t.reason})` : ' (Closed)'

          return {
            id: t.id,
            symbol: t.symbol,
            strategy_name: 'OANDA',
            direction: t.direction,
            entry_price: t.entry_price,
            exit_price: t.exit_price || t.entry_price,
            status: 'closed',
            quantity: t.units,
            pnl: t.realized_pnl,
            pnl_percent: pnlPercent,
            is_win: isWin,
            exit_reason: exitReason,
            ai_approved: true,
            signal_time: t.time,
            entry_time: t.time,
            exit_time: t.time,
            broker: 'oanda'
          }
        })
        setTrades(oandaTrades)
        setTotal(oandaTrades.length)
      } else {
        // Fetch trades from database
        const params = new URLSearchParams({
          limit: limit.toString(),
          offset: ((page - 1) * limit).toString()
        })
        
        if (filters.status) params.append('status', filters.status)
        if (filters.strategy) params.append('strategy', filters.strategy)
        if (filters.symbol) params.append('symbol', filters.symbol)

        const res = await fetch(`/api/trades?${params}`)
        const data = await res.json()
        // Sort by ID descending (most recent first)
        const sortedTrades = [...data.trades].sort((a, b) => b.id - a.id)
        setTrades(sortedTrades)
        setTotal(data.total)
      }
    } catch (err) {
      console.error('Failed to fetch trades:', err)
    }
    setLoading(false)
  }

  const totalPages = Math.ceil(total / limit)

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-bold">Trade History</h1>
        <div className="text-xs text-gray-400">
          {total} trades
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 bg-gray-800 p-3 rounded-lg border border-gray-700 text-xs">
        <div className="flex items-center gap-1">
          <Filter size={12} className="text-gray-400" />
          <span className="text-gray-400">Filters:</span>
        </div>

        <select
          value={filters.status}
          onChange={(e) => { setFilters({...filters, status: e.target.value}); setPage(1) }}
          className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs text-white cursor-pointer"
        >
          <option value="" className="bg-gray-700 text-white">All</option>
          <option value="pending" className="bg-gray-700 text-white">Pending</option>
          <option value="approved" className="bg-gray-700 text-white">Approved</option>
          <option value="rejected" className="bg-gray-700 text-white">Rejected</option>
          <option value="open" className="bg-gray-700 text-white">Open</option>
          <option value="closed" className="bg-gray-700 text-white">Closed</option>
          <option value="failed" className="bg-gray-700 text-white">Failed</option>
        </select>

        <select
          value={filters.strategy}
          onChange={(e) => { setFilters({...filters, strategy: e.target.value}); setPage(1) }}
          className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs text-white cursor-pointer"
        >
          <option value="" className="bg-gray-700 text-white">All Strategies</option>
          {strategies.map(s => (
            <option key={s.name} value={s.name} className="bg-gray-700 text-white">{s.name}</option>
          ))}
        </select>

        <input
          type="text"
          placeholder="Symbol..."
          value={filters.symbol}
          onChange={(e) => { setFilters({...filters, symbol: e.target.value.toUpperCase()}); setPage(1) }}
          className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs w-20"
        />

        {(filters.status || filters.strategy || filters.symbol) && (
          <button
            onClick={() => { setFilters({ status: '', strategy: '', symbol: '' }); setPage(1) }}
            className="text-xs text-blue-400 hover:text-blue-300"
          >
            Clear
          </button>
        )}
      </div>

      {/* Trades Table */}
      <div className="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-gray-900">
            <tr>
              <th className="px-2 py-2 text-left text-gray-400 uppercase">Time</th>
              <th className="px-2 py-2 text-left text-gray-400 uppercase">Symbol</th>
              <th className="px-2 py-2 text-left text-gray-400 uppercase">Strategy</th>
              <th className="px-2 py-2 text-left text-gray-400 uppercase">Dir</th>
              <th className="px-2 py-2 text-left text-gray-400 uppercase">Entry</th>
              <th className="px-2 py-2 text-left text-gray-400 uppercase">Closed</th>
              <th className="px-2 py-2 text-left text-gray-400 uppercase">P&L</th>
              <th className="px-2 py-2 text-left text-gray-400 uppercase">Status</th>
              <th className="px-2 py-2 text-left text-gray-400 uppercase"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-700">
            {loading ? (
              <tr>
                <td colSpan="9" className="px-4 py-8 text-center text-gray-500">
                  Loading...
                </td>
              </tr>
            ) : trades.length === 0 ? (
              <tr>
                <td colSpan="9" className="px-4 py-8 text-center text-gray-500">
                  No trades
                </td>
              </tr>
            ) : (
              trades.map((trade) => (
                <tr key={trade.id} className="hover:bg-gray-750">
                  <td className="px-2 py-2">
                    {trade.signal_time && format(new Date(trade.signal_time), 'MMM d, HH:mm')}
                  </td>
                  <td className="px-2 py-2 font-medium">{trade.symbol}</td>
                  <td className="px-2 py-2 text-gray-400">{trade.strategy_name}</td>
                  <td className="px-2 py-2">
                    <span className={trade.direction === 'long' ? 'text-green-400' : 'text-red-400'}>
                      {trade.direction?.toUpperCase()}
                    </span>
                  </td>
                  <td className="px-2 py-2 font-mono">
                    {formatPrice(trade.entry_price, trade.symbol)}
                  </td>
                  <td className="px-2 py-2 font-mono">
                    {trade.status === 'open' ? (
                      <span className="text-blue-400">Open</span>
                    ) : (
                      <span className={trade.is_win ? 'text-green-400' : 'text-red-400'}>
                        {trade.exit_reason || '-'}
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    {trade.pnl !== null && trade.pnl !== 0 ? (
                      <span className={`font-mono ${trade.is_win ? 'text-green-400' : 'text-red-400'}`}>
                        {trade.is_win ? '+' : ''}{trade.pnl?.toFixed(2)}
                      </span>
                    ) : (
                      <span className="text-gray-500">-</span>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    <StatusBadge status={trade.status} />
                  </td>
                  <td className="px-2 py-2">
                    <Link
                      to={`/trades/${trade.id}`}
                      className="p-1 hover:bg-gray-700 rounded inline-block"
                    >
                      <Eye size={12} className="text-gray-400" />
                    </Link>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-3 py-2 border-t border-gray-700 text-xs">
            <div className="text-gray-400">
              {((page - 1) * limit) + 1}-{Math.min(page * limit, total)} of {total}
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="p-1 rounded hover:bg-gray-700 disabled:opacity-50"
              >
                <ChevronLeft size={14} />
              </button>
              <span>
                {page}/{totalPages}
              </span>
              <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="p-1 rounded hover:bg-gray-700 disabled:opacity-50"
              >
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
