import React, { useState, useEffect } from 'react'
import {
  TrendingUp,
  TrendingDown,
  X,
  Target,
  Shield,
  Activity,
  ChevronDown,
  ChevronUp,
  AlertTriangle,
  CheckCircle,
  Plus,
  Trash2,
  Folder,
  DollarSign,
  Zap,
  Camera,
  Lock
} from 'lucide-react'

const API_BASE = ''

export default function Positions() {
  const [positions, setPositions] = useState([])
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [selectedPosition, setSelectedPosition] = useState(null)
  const [actionModal, setActionModal] = useState(null)
  const [actionValue, setActionValue] = useState('')
  const [buckets, setBuckets] = useState([])
  const [newBucketName, setNewBucketName] = useState('')
  const [selectedBucket, setSelectedBucket] = useState(null)
  const [showBucketPanel, setShowBucketPanel] = useState(false)
  const [trailingModal, setTrailingModal] = useState(null) // { tradeId, symbol, current }
  const [trailingForm, setTrailingForm] = useState({ trigger: '', lock: '' })
  const [trailingMsg, setTrailingMsg] = useState('')

  const fetchPositions = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/positions`)
      const data = await res.json()
      setPositions(data.positions || [])
      setSummary(data.summary || null)
    } catch (err) {
      console.error('Failed to fetch positions:', err)
    } finally {
      setLoading(false)
    }
  }

  const fetchBuckets = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/buckets`)
      const data = await res.json()
      setBuckets(Array.isArray(data) ? data : [])
    } catch (err) {
      console.error('Failed to fetch buckets:', err)
    }
  }

  useEffect(() => {
    fetchPositions()
    fetchBuckets()
    const interval = setInterval(() => {
      fetchPositions()
      fetchBuckets()
    }, 2000)
    return () => clearInterval(interval)
  }, [])

  const closeTrade = async (tradeId) => {
    if (!confirm('Close this position?')) return
    try {
      if (typeof tradeId === 'string' && tradeId.startsWith('oanda_trade_')) {
        const oandaTradeId = tradeId.replace('oanda_trade_', '')
        await fetch(`${API_BASE}/api/oanda/close-trade/${oandaTradeId}`, {
          method: 'POST'
        })
      } else if (typeof tradeId === 'string' && tradeId.startsWith('oanda_')) {
        const oandaTradeId = tradeId.replace('oanda_', '')
        await fetch(`${API_BASE}/api/oanda/close-trade/${oandaTradeId}`, {
          method: 'POST'
        })
      } else {
        await fetch(`${API_BASE}/api/trades/${tradeId}/close`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reason: 'Manual close from dashboard' })
        })
      }
      fetchPositions()
      fetchBuckets()
    } catch (err) {
      alert('Failed to close trade: ' + err.message)
    }
  }

  const openTrailingModal = (pos) => {
    setTrailingModal(pos)
    setTrailingForm({
      trigger: pos.trailing_stop_trigger || '',
      lock: pos.trailing_stop_lock || ''
    })
    setTrailingMsg('')
  }

  const setTrailingStop = async (e) => {
    e.preventDefault()
    if (!trailingForm.trigger || !trailingForm.lock) return
    setTrailingMsg('')
    try {
      const res = await fetch(`${API_BASE}/api/trades/${trailingModal.trade_id}/trailing-stop-dollar`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          trigger_profit: parseFloat(trailingForm.trigger),
          lock_profit: parseFloat(trailingForm.lock)
        })
      })
      const data = await res.json()
      if (res.ok) {
        setTrailingMsg(data.message || 'Trailing stop set')
        fetchPositions()
      } else {
        setTrailingMsg(data.detail || 'Failed to set trailing stop')
      }
    } catch (err) {
      setTrailingMsg('Failed to set trailing stop')
    }
  }

  const clearTrailingStop = async () => {
    try {
      await fetch(`${API_BASE}/api/trades/${trailingModal.trade_id}/trailing-stop`, { method: 'DELETE' })
      setTrailingMsg('Trailing stop cleared')
      fetchPositions()
    } catch (err) {
      setTrailingMsg('Failed to clear trailing stop')
    }
  }

  const closeAllTrades = async (symbol = null) => {
    const msg = symbol ? `Close all ${symbol} positions?` : 'Close ALL positions?'
    if (!confirm(msg)) return
    try {
      await fetch(`${API_BASE}/api/trades/close-all`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, reason: 'Close all from dashboard' })
      })
      fetchPositions()
      fetchBuckets()
    } catch (err) {
      alert('Failed to close trades: ' + err.message)
    }
  }

  const captureScreenshot = async (pos, eventType = 'entry') => {
    try {
      const tradeId = typeof pos.trade_id === 'string' ? pos.trade_id.replace('oanda_trade_', '').replace('oanda_', '') : pos.trade_id
      const response = await fetch(`${API_BASE}/api/screenshots/capture`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: pos.symbol,
          trade_id: typeof pos.trade_id === 'string' ? tradeId : pos.trade_id,
          event_type: eventType,
          source: 'screen'
        })
      })
      const data = await response.json()
      if (data.success) {
        alert(`Screenshot captured for ${pos.symbol} ${eventType}`)
        // Open screenshots folder or show the captured image
        if (data.screenshots?.screen) {
          window.open(data.screenshots.screen, '_blank')
        }
      } else {
        alert('Screenshot capture failed')
      }
    } catch (err) {
      alert('Screenshot capture failed: ' + err.message)
    }
  }

  const moveStopLoss = async (tradeId, newStop) => {
    try {
      await fetch(`${API_BASE}/api/trades/${tradeId}/move-stop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_stop: parseFloat(newStop) })
      })
      fetchPositions()
      setActionModal(null)
    } catch (err) {
      alert('Failed to move stop: ' + err.message)
    }
  }

  const formatPrice = (price, symbol) => {
    if (!price) return '-'
    const isJpy = symbol?.includes('JPY')
    const isGold = symbol?.includes('XAU')
    const isSilver = symbol?.includes('XAG')
    const decimals = isJpy ? 3 : (isGold || isSilver) ? 2 : 5
    return price.toFixed(decimals)
  }

  const formatPnl = (pnl) => {
    if (pnl === null || pnl === undefined) return '-'
    const sign = pnl >= 0 ? '+' : ''
    return `${sign}$${pnl.toFixed(2)}`
  }

  // Bucket management
  const createBucket = async () => {
    if (!newBucketName.trim()) return
    try {
      await fetch(`${API_BASE}/api/buckets/${newBucketName}`, { method: 'POST' })
      setNewBucketName('')
      fetchBuckets()
    } catch (err) {
      alert('Failed to create bucket: ' + err.message)
    }
  }

  const deleteBucket = async (name) => {
    if (!confirm(`Delete bucket "${name}"? Trades will not be closed.`)) return
    try {
      await fetch(`${API_BASE}/api/buckets/${name}`, { method: 'DELETE' })
      fetchBuckets()
    } catch (err) {
      alert('Failed to delete bucket: ' + err.message)
    }
  }

  const addToBucket = async (bucketName, tradeId) => {
    try {
      await fetch(`${API_BASE}/api/buckets/${bucketName}/add/${tradeId}`, { method: 'POST' })
      fetchBuckets()
    } catch (err) {
      alert('Failed to add to bucket: ' + err.message)
    }
  }

  const removeFromBucket = async (bucketName, tradeId) => {
    try {
      await fetch(`${API_BASE}/api/buckets/${bucketName}/remove/${tradeId}`, { method: 'POST' })
      fetchBuckets()
    } catch (err) {
      alert('Failed to remove from bucket: ' + err.message)
    }
  }

  const closeBucket = async (name) => {
    if (!confirm(`Close all trades in bucket "${name}"?`)) return
    try {
      await fetch(`${API_BASE}/api/buckets/${name}/close`, { method: 'POST' })
      fetchPositions()
      fetchBuckets()
    } catch (err) {
      alert('Failed to close bucket: ' + err.message)
    }
  }

  const closeBucketIfProfit = async (name) => {
    try {
      const res = await fetch(`${API_BASE}/api/buckets/${name}/close-if-profit`, { method: 'POST' })
      const data = await res.json()
      if (!data.success) {
        alert(`Bucket not closed: ${data.error || data.reason}`)
      } else if (data.skipped) {
        alert(`Bucket P&L: ${formatPnl(data.pnl)} - Not in profit, trades kept open`)
      } else {
        alert(`Bucket closed! P&L: ${formatPnl(data.bucket_pnl)}`)
      }
      fetchPositions()
      fetchBuckets()
    } catch (err) {
      alert('Failed to close bucket: ' + err.message)
    }
  }

  const getTradeBucket = (tradeId) => {
    for (const bucket of buckets) {
      if (bucket.positions?.some(p => p.trade_id === tradeId)) {
        return bucket.name
      }
    }
    return null
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Activity className="animate-spin text-blue-500" size={32} />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Trade Manager</h1>
          <p className="text-gray-400">Manage positions and buckets</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowBucketPanel(!showBucketPanel)}
            className={`px-4 py-2 rounded-lg flex items-center gap-2 ${
              showBucketPanel ? 'bg-blue-600 text-white' : 'bg-gray-700 hover:bg-gray-600'
            }`}
          >
            <Folder size={16} />
            Buckets
          </button>
          {positions.length > 0 && (
            <button
              onClick={() => closeAllTrades()}
              className="px-4 py-2 bg-red-600 hover:bg-red-700 rounded-lg flex items-center gap-2"
            >
              <X size={16} />
              Close All
            </button>
          )}
        </div>
      </div>

      {/* Buckets Panel */}
      {showBucketPanel && (
        <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
          <h3 className="text-lg font-medium mb-4 flex items-center gap-2">
            <Folder size={20} className="text-blue-400" />
            Trade Buckets
          </h3>

          {/* Create bucket */}
          <div className="flex gap-2 mb-4">
            <input
              type="text"
              value={newBucketName}
              onChange={(e) => setNewBucketName(e.target.value)}
              placeholder="New bucket name..."
              className="flex-1 px-3 py-2 bg-gray-900 border border-gray-700 rounded focus:outline-none focus:border-blue-500"
              onKeyPress={(e) => e.key === 'Enter' && createBucket()}
            />
            <button
              onClick={createBucket}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded flex items-center gap-2"
            >
              <Plus size={16} />
              Create
            </button>
          </div>

          {/* Buckets list */}
          {buckets.length === 0 ? (
            <div className="text-gray-500 text-center py-4">
              No buckets yet. Create one to group trades.
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {buckets.map((bucket) => (
                <div
                  key={bucket.name}
                  className={`p-4 rounded-lg border ${
                    bucket.in_profit ? 'bg-green-900/30 border-green-700' : 'bg-gray-900/50 border-gray-700'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-medium">{bucket.name}</span>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => closeBucketIfProfit(bucket.name)}
                        className="p-1 hover:bg-gray-700 rounded text-green-400"
                        title="Close if in profit"
                      >
                        <Zap size={14} />
                      </button>
                      <button
                        onClick={() => closeBucket(bucket.name)}
                        className="p-1 hover:bg-gray-700 rounded text-red-400"
                        title="Close all"
                      >
                        <X size={14} />
                      </button>
                      <button
                        onClick={() => deleteBucket(bucket.name)}
                        className="p-1 hover:bg-gray-700 rounded text-gray-400"
                        title="Delete bucket"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                  <div className="text-2xl font-bold mb-1">
                    <span className={bucket.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}>
                      {formatPnl(bucket.total_pnl)}
                    </span>
                  </div>
                  <div className="text-sm text-gray-400">
                    {bucket.count} trade{bucket.count !== 1 ? 's' : ''}
                    {bucket.in_profit ? ' • In profit' : ''}
                  </div>
                  {bucket.positions?.length > 0 && (
                    <div className="mt-2 pt-2 border-t border-gray-700">
                      <div className="flex flex-wrap gap-1">
                        {bucket.positions.map((p) => (
                          <span
                            key={p.trade_id}
                            className="inline-flex items-center gap-1 px-2 py-0.5 bg-gray-800 rounded text-xs"
                          >
                            {p.symbol}
                            <button
                              onClick={() => removeFromBucket(bucket.name, p.trade_id)}
                              className="text-gray-500 hover:text-red-400"
                            >
                              <X size={10} />
                            </button>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Trailing Stop Modal */}
      {trailingModal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-xl p-6 w-96 border border-yellow-600 shadow-xl">
            <h3 className="text-lg font-semibold mb-4 flex items-center gap-2 text-white">
              <Shield size={20} className="text-yellow-400" />
              Trailing Stop - {trailingModal.symbol}
            </h3>
            <p className="text-sm text-gray-400 mb-4">
              When profit reaches trigger amount, stop loss moves to lock in the specified profit.
            </p>
            <form onSubmit={setTrailingStop} className="space-y-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Trigger at Profit ($)</label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={trailingForm.trigger}
                  onChange={(e) => setTrailingForm({ ...trailingForm, trigger: e.target.value })}
                  placeholder="e.g. 400"
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">Lock Profit ($)</label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={trailingForm.lock}
                  onChange={(e) => setTrailingForm({ ...trailingForm, lock: e.target.value })}
                  placeholder="e.g. 200"
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white"
                />
              </div>
              {trailingMsg && (
                <div className={`text-sm ${trailingMsg.includes('Failed') ? 'text-red-400' : 'text-green-400'}`}>
                  {trailingMsg}
                </div>
              )}
              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={!trailingForm.trigger || !trailingForm.lock}
                  className="flex-1 px-4 py-2 bg-yellow-600 hover:bg-yellow-700 disabled:bg-gray-600 disabled:opacity-50 rounded-lg font-medium text-white"
                >
                  Set
                </button>
                {(trailingModal.trailing_stop_trigger != null || trailingModal.trailing_stop_lock != null) && (
                  <button
                    type="button"
                    onClick={clearTrailingStop}
                    className="px-4 py-2 bg-red-600 hover:bg-red-700 rounded-lg font-medium text-white"
                  >
                    Clear
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setTrailingModal(null)}
                  className="px-4 py-2 bg-gray-600 hover:bg-gray-500 rounded-lg font-medium text-white"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-4 gap-4">
          <div className="bg-gray-800 rounded-lg p-4">
            <div className="text-gray-400 text-sm">Total Positions</div>
            <div className="text-2xl font-bold">{summary.total_positions}</div>
          </div>
          <div className="bg-gray-800 rounded-lg p-4">
            <div className="text-gray-400 text-sm">Unrealized P&L</div>
            <div className={`text-2xl font-bold ${summary.total_unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {formatPnl(summary.total_unrealized_pnl)}
            </div>
          </div>
          <div className="bg-gray-800 rounded-lg p-4">
            <div className="text-gray-400 text-sm">Winning</div>
            <div className="text-2xl font-bold text-green-400">{summary.winning_positions}</div>
          </div>
          <div className="bg-gray-800 rounded-lg p-4">
            <div className="text-gray-400 text-sm">Losing</div>
            <div className="text-2xl font-bold text-red-400">{summary.losing_positions}</div>
          </div>
        </div>
      )}

      {/* Positions Table */}
      {positions.length === 0 ? (
        <div className="bg-gray-800 rounded-lg p-8 text-center">
          <Activity className="mx-auto text-gray-600 mb-4" size={48} />
          <p className="text-gray-400">No open positions</p>
        </div>
      ) : (
        <div className="bg-gray-800 rounded-lg overflow-hidden">
          <table className="w-full">
            <thead className="bg-gray-900">
              <tr>
                <th className="px-4 py-3 text-left text-xs text-gray-400 uppercase">Symbol</th>
                <th className="px-4 py-3 text-left text-xs text-gray-400 uppercase">Bucket</th>
                <th className="px-4 py-3 text-left text-xs text-gray-400 uppercase">Direction</th>
                <th className="px-4 py-3 text-right text-xs text-gray-400 uppercase">Entry</th>
                <th className="px-4 py-3 text-right text-xs text-gray-400 uppercase">Current</th>
                <th className="px-4 py-3 text-right text-xs text-gray-400 uppercase">P&L</th>
                <th className="px-4 py-3 text-right text-xs text-gray-400 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-700">
              {positions.map((pos) => {
                const bucket = getTradeBucket(pos.trade_id)
                return (
                  <tr key={pos.trade_id} className="hover:bg-gray-750">
                    <td className="px-4 py-3">
                      <div className="font-medium">{pos.symbol}</div>
                      <div className="text-xs text-gray-500">{pos.strategy_name} • {pos.broker?.toUpperCase()}</div>
                    </td>
                    <td className="px-4 py-3">
                      {bucket ? (
                        <span className="inline-flex items-center gap-1 px-2 py-1 bg-blue-900/50 text-blue-400 rounded text-xs">
                          <Folder size={10} />
                          {bucket}
                        </span>
                      ) : (
                        <select
                          className="bg-gray-700 text-xs rounded px-2 py-1"
                          onChange={(e) => e.target.value && addToBucket(e.target.value, pos.trade_id)}
                          value=""
                        >
                          <option value="">+ Add to bucket</option>
                          {buckets.map((b) => (
                            <option key={b.name} value={b.name}>{b.name}</option>
                          ))}
                        </select>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium ${
                        pos.direction === 'long'
                          ? 'bg-green-900/50 text-green-400'
                          : 'bg-red-900/50 text-red-400'
                      }`}>
                        {pos.direction === 'long' ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
                        {pos.direction.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      {formatPrice(pos.entry_price, pos.symbol)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      {formatPrice(pos.current_price, pos.symbol)}
                    </td>
                    <td className={`px-4 py-3 text-right font-mono font-medium ${
                      pos.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'
                    }`}>
                      {formatPnl(pos.unrealized_pnl)}
                      <div className="text-xs text-gray-500">
                        {pos.unrealized_pnl_pct?.toFixed(2)}%
                      </div>
                      {(pos.trailing_stop_trigger || pos.trailing_stop_lock) && (
                        <div className="flex items-center justify-end gap-1 mt-1">
                          <Lock size={10} className={pos.trailing_stop_activated ? 'text-green-400' : 'text-yellow-400'} />
                          <span className={`text-xs ${pos.trailing_stop_activated ? 'text-green-400' : 'text-yellow-400'}`}>
                            TS: ${pos.trailing_stop_trigger}/→${pos.trailing_stop_lock}
                          </span>
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => captureScreenshot(pos, 'entry')}
                        className="p-1.5 hover:bg-gray-700 rounded text-blue-400 mr-1"
                        title="Capture Screenshot"
                      >
                        <Camera size={14} />
                      </button>
                      <button
                        onClick={() => openTrailingModal(pos)}
                        className="p-1.5 hover:bg-gray-700 rounded text-yellow-400 mr-1"
                        title="Set Trailing Stop"
                      >
                        <Shield size={14} />
                      </button>
                      <button
                        onClick={() => closeTrade(pos.trade_id)}
                        className="p-1.5 hover:bg-gray-700 rounded text-red-400"
                        title="Close Position"
                      >
                        <X size={14} />
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* By Symbol Summary */}
      {summary?.by_symbol && Object.keys(summary.by_symbol).length > 0 && (
        <div className="bg-gray-800 rounded-lg p-4">
          <h3 className="text-lg font-medium mb-3">By Symbol</h3>
          <div className="grid grid-cols-4 gap-3">
            {Object.entries(summary.by_symbol).map(([symbol, data]) => (
              <div key={symbol} className="bg-gray-900 rounded p-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-medium">{symbol}</span>
                  <button
                    onClick={() => closeAllTrades(symbol)}
                    className="text-xs text-red-400 hover:text-red-300"
                  >
                    Close All
                  </button>
                </div>
                <div className="text-sm text-gray-400">
                  {data.count} position{data.count !== 1 ? 's' : ''} ({data.long}L / {data.short}S)
                </div>
                <div className={`text-sm font-medium ${data.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {formatPnl(data.pnl)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
