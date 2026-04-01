import React, { useState, useEffect } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  TrendingUp,
  TrendingDown,
  CheckCircle,
  XCircle,
  Clock,
  DollarSign,
  Target,
  AlertTriangle,
  Image,
  Play,
  Square,
  Lock
} from 'lucide-react'
import { format } from 'date-fns'

const InfoRow = ({ label, value, className = '' }) => (
  <div className="flex justify-between py-2 border-b border-gray-700">
    <span className="text-gray-400">{label}</span>
    <span className={`font-medium ${className}`}>{value}</span>
  </div>
)

export default function TradeDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [trade, setTrade] = useState(null)
  const [screenshots, setScreenshots] = useState({ entry: [], exit: [] })
  const [loading, setLoading] = useState(true)
  const [executing, setExecuting] = useState(false)
  const [trailingForm, setTrailingForm] = useState({ trigger: '', lock: '' })
  const [trailingMsg, setTrailingMsg] = useState('')

  useEffect(() => {
    fetchTrade()
    fetchScreenshots()
  }, [id])

  const fetchTrade = async () => {
    try {
      const res = await fetch(`/api/trades/${id}`)
      if (!res.ok) throw new Error('Trade not found')
      setTrade(await res.json())
    } catch (err) {
      console.error('Failed to fetch trade:', err)
    }
    setLoading(false)
  }

  const fetchScreenshots = async () => {
    try {
      const res = await fetch(`/api/screenshots/${id}`)
      setScreenshots(await res.json())
    } catch (err) {
      console.error('Failed to fetch screenshots:', err)
    }
  }

  const executeTrade = async () => {
    setExecuting(true)
    try {
      await fetch(`/api/trades/${id}/execute`, { method: 'POST' })
      fetchTrade()
    } catch (err) {
      console.error('Failed to execute trade:', err)
    }
    setExecuting(false)
  }

  const closeTrade = async () => {
    setExecuting(true)
    try {
      await fetch(`/api/trades/${id}/close`, { method: 'POST' })
      fetchTrade()
    } catch (err) {
      console.error('Failed to close trade:', err)
    }
    setExecuting(false)
  }

  const setTrailingStop = async (e) => {
    e.preventDefault()
    if (!trailingForm.trigger || !trailingForm.lock) return

    setExecuting(true)
    setTrailingMsg('')
    try {
      const res = await fetch(`/api/trades/${id}/trailing-stop-dollar`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          trigger_profit: parseFloat(trailingForm.trigger),
          lock_profit: parseFloat(trailingForm.lock)
        })
      })
      const data = await res.json()
      if (res.ok) {
        setTrailingMsg(data.message)
        fetchTrade()
        setTrailingForm({ trigger: '', lock: '' })
      } else {
        setTrailingMsg(data.detail || 'Failed to set trailing stop')
      }
    } catch (err) {
      setTrailingMsg('Failed to set trailing stop')
    }
    setExecuting(false)
  }

  const clearTrailingStop = async () => {
    setExecuting(true)
    setTrailingMsg('')
    try {
      await fetch(`/api/trades/${id}/trailing-stop`, { method: 'DELETE' })
      fetchTrade()
      setTrailingMsg('Trailing stop cleared')
    } catch (err) {
      setTrailingMsg('Failed to clear trailing stop')
    }
    setExecuting(false)
  }

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center">
        <div className="text-gray-400">Loading...</div>
      </div>
    )
  }

  if (!trade) {
    return (
      <div className="p-6">
        <div className="text-center py-12">
          <AlertTriangle size={48} className="mx-auto text-yellow-500 mb-4" />
          <h2 className="text-xl font-bold mb-2">Trade Not Found</h2>
          <Link to="/trades" className="text-blue-400 hover:text-blue-300">
            ← Back to trades
          </Link>
        </div>
      </div>
    )
  }

  const isLong = trade.direction === 'long'
  const isWin = trade.pnl > 0
  const canExecute = trade.status === 'approved'
  const canClose = trade.status === 'open'

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button 
            onClick={() => navigate(-1)}
            className="p-2 hover:bg-gray-800 rounded-lg transition-colors"
          >
            <ArrowLeft size={20} />
          </button>
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-3">
              {trade.symbol}
              <span className={`flex items-center gap-1 text-lg ${
                isLong ? 'text-green-400' : 'text-red-400'
              }`}>
                {isLong ? <TrendingUp size={20} /> : <TrendingDown size={20} />}
                {trade.direction?.toUpperCase()}
              </span>
            </h1>
            <div className="text-sm text-gray-400">
              Trade #{trade.id} • {trade.strategy_name}
            </div>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex gap-3">
          {canExecute && (
            <button
              onClick={executeTrade}
              disabled={executing}
              className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg font-medium disabled:opacity-50"
            >
              <Play size={18} />
              Execute Trade
            </button>
          )}
          {canClose && (
            <button
              onClick={closeTrade}
              disabled={executing}
              className="flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 rounded-lg font-medium disabled:opacity-50"
            >
              <Square size={18} />
              Close Position
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Trade Details */}
        <div className="lg:col-span-2 space-y-6">
          {/* Status Card */}
          <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
            <h2 className="text-lg font-semibold mb-4">Trade Status</h2>
            <div className="flex items-center gap-4 mb-6">
              <div className={`px-4 py-2 rounded-lg text-lg font-bold ${
                trade.status === 'closed' ? (isWin ? 'bg-green-900 text-green-400' : 'bg-red-900 text-red-400') :
                trade.status === 'open' ? 'bg-purple-900 text-purple-400' :
                trade.status === 'approved' ? 'bg-yellow-900 text-yellow-400' :
                trade.status === 'rejected' ? 'bg-red-900 text-red-400' :
                'bg-gray-700 text-gray-300'
              }`}>
                {trade.status?.toUpperCase()}
              </div>
              {trade.status === 'closed' && (
                <div className={`text-3xl font-bold font-mono ${isWin ? 'text-green-400' : 'text-red-400'}`}>
                  {isWin ? '+' : ''}{trade.pnl?.toFixed(4)}
                  <span className="text-lg ml-2">({trade.pnl_percent?.toFixed(2)}%)</span>
                </div>
              )}
            </div>

            <div className="grid grid-cols-2 gap-6">
              <div>
                <InfoRow label="Entry Price" value={`$${trade.entry_price?.toLocaleString()}`} />
                <InfoRow label="Exit Price" value={trade.exit_price ? `$${trade.exit_price.toLocaleString()}` : '-'} />
                <InfoRow label="Quantity" value={trade.quantity || '-'} />
                <InfoRow label="Fees" value={trade.fees ? `$${trade.fees.toFixed(4)}` : '-'} />
              </div>
              <div>
                <InfoRow 
                  label="Stop Loss" 
                  value={trade.stop_loss ? `$${trade.stop_loss.toLocaleString()}` : 'Not set'} 
                  className={trade.stop_loss ? 'text-red-400' : 'text-gray-500'}
                />
                <InfoRow 
                  label="Take Profit" 
                  value={trade.take_profit ? `$${trade.take_profit.toLocaleString()}` : 'Not set'}
                  className={trade.take_profit ? 'text-green-400' : 'text-gray-500'}
                />
                <InfoRow label="Leverage" value={`${trade.leverage || 1}x`} />
                {(trade.trailing_stop_trigger || trade.trailing_stop_lock) && (
                  <InfoRow
                    label="Trailing Stop"
                    value={trade.trailing_stop_activated
                      ? `🔒 Lock $${trade.trailing_stop_lock} (ACTIVE)`
                      : `Trig $${trade.trailing_stop_trigger} → Lock $${trade.trailing_stop_lock}`
                    }
                    className={trade.trailing_stop_activated ? 'text-green-400' : 'text-yellow-400'}
                  />
                )}
              </div>
            </div>
          </div>

          {/* Trailing Stop Control - Only for open positions */}
          {canClose && (
            <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
              <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <Lock size={20} className="text-yellow-400" />
                Trailing Stop
              </h2>
              <p className="text-sm text-gray-400 mb-4">
                Set a profit trigger and lock amount. When profit reaches trigger, stop loss moves to lock in the specified profit.
              </p>
              <form onSubmit={setTrailingStop} className="flex gap-4 items-end mb-4">
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Trigger at Profit ($)</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={trailingForm.trigger}
                    onChange={(e) => setTrailingForm({ ...trailingForm, trigger: e.target.value })}
                    placeholder="e.g. 400"
                    className="bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white w-32"
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
                    className="bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white w-32"
                  />
                </div>
                <button
                  type="submit"
                  disabled={executing || !trailingForm.trigger || !trailingForm.lock}
                  className="px-4 py-2 bg-yellow-600 hover:bg-yellow-700 disabled:bg-gray-600 disabled:opacity-50 rounded-lg font-medium transition-colors"
                >
                  Set Trailing Stop
                </button>
                {(trade.trailing_stop_trigger || trade.trailing_stop_lock) && (
                  <button
                    type="button"
                    onClick={clearTrailingStop}
                    disabled={executing}
                    className="px-4 py-2 bg-red-600 hover:bg-red-700 disabled:bg-gray-600 disabled:opacity-50 rounded-lg font-medium transition-colors"
                  >
                    Clear
                  </button>
                )}
              </form>
              {trailingMsg && (
                <div className={`text-sm ${trailingMsg.includes('Failed') ? 'text-red-400' : 'text-green-400'}`}>
                  {trailingMsg}
                </div>
              )}
            </div>
          )}

          {/* Timeline */}
          <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
            <h2 className="text-lg font-semibold mb-4">Timeline</h2>
            <div className="space-y-4">
              {trade.signal_time && (
                <div className="flex items-start gap-4">
                  <div className="w-10 h-10 rounded-full bg-blue-900 flex items-center justify-center">
                    <Target size={18} className="text-blue-400" />
                  </div>
                  <div>
                    <div className="font-medium">Signal Generated</div>
                    <div className="text-sm text-gray-400">
                      {format(new Date(trade.signal_time), 'PPpp')}
                    </div>
                  </div>
                </div>
              )}
              {trade.approved_time && (
                <div className="flex items-start gap-4">
                  <div className={`w-10 h-10 rounded-full flex items-center justify-center ${
                    trade.ai_approved ? 'bg-green-900' : 'bg-red-900'
                  }`}>
                    {trade.ai_approved ? 
                      <CheckCircle size={18} className="text-green-400" /> :
                      <XCircle size={18} className="text-red-400" />
                    }
                  </div>
                  <div>
                    <div className="font-medium">
                      AI Validator {trade.ai_approved ? 'Approved' : 'Rejected'}
                    </div>
                    <div className="text-sm text-gray-400">
                      {format(new Date(trade.approved_time), 'PPpp')}
                    </div>
                  </div>
                </div>
              )}
              {trade.entry_time && (
                <div className="flex items-start gap-4">
                  <div className="w-10 h-10 rounded-full bg-purple-900 flex items-center justify-center">
                    <Play size={18} className="text-purple-400" />
                  </div>
                  <div>
                    <div className="font-medium">Position Opened</div>
                    <div className="text-sm text-gray-400">
                      {format(new Date(trade.entry_time), 'PPpp')}
                    </div>
                  </div>
                </div>
              )}
              {trade.exit_time && (
                <div className="flex items-start gap-4">
                  <div className={`w-10 h-10 rounded-full flex items-center justify-center ${
                    isWin ? 'bg-green-900' : 'bg-red-900'
                  }`}>
                    <DollarSign size={18} className={isWin ? 'text-green-400' : 'text-red-400'} />
                  </div>
                  <div>
                    <div className="font-medium">Position Closed</div>
                    <div className="text-sm text-gray-400">
                      {format(new Date(trade.exit_time), 'PPpp')}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Screenshots */}
          {(screenshots.entry.length > 0 || screenshots.exit.length > 0 || trade.entry_screenshot || trade.exit_screenshot) && (
            <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
              <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <Image size={20} />
                Screenshots
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {(trade.entry_screenshot || screenshots.entry.length > 0) && (
                  <div>
                    <div className="text-sm text-gray-400 mb-2">Entry</div>
                    {trade.entry_screenshot?.endsWith('.png') ? (
                      <img 
                        src={`/screenshots/${trade.entry_screenshot.split('/').pop()}`}
                        alt="Entry screenshot"
                        className="rounded-lg border border-gray-700 w-full"
                      />
                    ) : (
                      <div className="bg-gray-900 rounded-lg p-4 text-sm text-gray-500">
                        Screenshot placeholder
                      </div>
                    )}
                  </div>
                )}
                {(trade.exit_screenshot || screenshots.exit.length > 0) && (
                  <div>
                    <div className="text-sm text-gray-400 mb-2">Exit</div>
                    {trade.exit_screenshot?.endsWith('.png') ? (
                      <img 
                        src={`/screenshots/${trade.exit_screenshot.split('/').pop()}`}
                        alt="Exit screenshot"
                        className="rounded-lg border border-gray-700 w-full"
                      />
                    ) : (
                      <div className="bg-gray-900 rounded-lg p-4 text-sm text-gray-500">
                        Screenshot placeholder
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* AI Validator Analysis */}
        <div className="space-y-6">
          <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
            <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
              {trade.ai_approved ? 
                <CheckCircle className="text-green-400" /> :
                <XCircle className="text-red-400" />
              }
              AI Validator Analysis
            </h2>
            
            <div className="space-y-4">
              <div>
                <div className="text-sm text-gray-400 mb-1">Decision</div>
                <div className={`text-lg font-bold ${
                  trade.ai_approved ? 'text-green-400' : 'text-red-400'
                }`}>
                  {trade.ai_approved ? 'APPROVED' : 'REJECTED'}
                </div>
              </div>

              <div>
                <div className="text-sm text-gray-400 mb-1">Confidence</div>
                <div className="flex items-center gap-3">
                  <div className="flex-1 bg-gray-700 rounded-full h-2">
                    <div 
                      className={`h-2 rounded-full ${
                        trade.ai_confidence >= 0.7 ? 'bg-green-500' :
                        trade.ai_confidence >= 0.4 ? 'bg-yellow-500' : 'bg-red-500'
                      }`}
                      style={{ width: `${(trade.ai_confidence || 0) * 100}%` }}
                    />
                  </div>
                  <span className="font-mono">
                    {((trade.ai_confidence || 0) * 100).toFixed(0)}%
                  </span>
                </div>
              </div>

              <div>
                <div className="text-sm text-gray-400 mb-1">Analysis</div>
                <div className="text-sm bg-gray-900 rounded-lg p-4">
                  {trade.ai_analysis || 'No analysis available'}
                </div>
              </div>
            </div>
          </div>

          {/* Metadata */}
          {trade.metadata && Object.keys(trade.metadata).length > 0 && (
            <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
              <h2 className="text-lg font-semibold mb-4">Metadata</h2>
              <pre className="text-xs bg-gray-900 rounded-lg p-4 overflow-auto">
                {JSON.stringify(trade.metadata, null, 2)}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
