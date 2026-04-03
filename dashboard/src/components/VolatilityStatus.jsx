import React, { useState, useEffect } from 'react'
import {
  Thermometer,
  AlertTriangle,
  CheckCircle,
  XCircle,
  RefreshCw,
  Settings,
  Power
} from 'lucide-react'

const VolatilityStatus = () => {
  const [volatility, setVolatility] = useState(null)
  const [loading, setLoading] = useState(true)
  const [showSettings, setShowSettings] = useState(false)
  const [overriding, setOverriding] = useState(false)

  const fetchVolatility = async () => {
    try {
      const res = await fetch('/api/volatility')
      const data = await res.json()
      setVolatility(data)
    } catch (err) {
      console.error('Failed to fetch volatility:', err)
    }
    setLoading(false)
  }

  useEffect(() => {
    fetchVolatility()
    const interval = setInterval(fetchVolatility, 30000) // Refresh every 30 seconds
    return () => clearInterval(interval)
  }, [])

  const handleOverride = async (enable) => {
    setOverriding(true)
    try {
      await fetch('/api/volatility/override', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: enable })
      })
      fetchVolatility()
    } catch (err) {
      console.error('Failed to override:', err)
    }
    setOverriding(false)
  }

  const handleClearOverride = async () => {
    try {
      await fetch('/api/volatility/clear-override', { method: 'POST' })
      fetchVolatility()
    } catch (err) {
      console.error('Failed to clear override:', err)
    }
  }

  if (loading) {
    return (
      <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
        <div className="animate-pulse flex items-center gap-2">
          <div className="h-4 w-4 bg-gray-700 rounded"></div>
          <div className="h-4 bg-gray-700 rounded w-32"></div>
        </div>
      </div>
    )
  }

  if (!volatility) {
    return (
      <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
        <div className="text-red-400 text-sm">Failed to load volatility data</div>
      </div>
    )
  }

  const { status, trading_allowed, symbols_allowed, symbols_blocked, total_symbols, symbols, manual_override } = volatility

  // Get status color and label
  const getStatusDisplay = () => {
    if (manual_override) {
      return { color: 'text-yellow-400', bg: 'bg-yellow-900/30', border: 'border-yellow-700' }
    }
    if (status === 'sufficient' || status === 'high') {
      return { color: 'text-green-400', bg: 'bg-green-900/30', border: 'border-green-700' }
    }
    if (status === 'mostly_low' || status === 'all_low') {
      return { color: 'text-red-400', bg: 'bg-red-900/30', border: 'border-red-700' }
    }
    return { color: 'text-yellow-400', bg: 'bg-yellow-900/30', border: 'border-yellow-700' }
  }

  const statusDisplay = getStatusDisplay()

  // Count symbol statuses
  const symbolStatuses = Object.entries(symbols || {}).reduce((acc, [sym, data]) => {
    if (data.status === 'low') acc.low++
    else if (data.status === 'caution') acc.caution++
    else if (data.status === 'high') acc.high++
    return acc
  }, { low: 0, caution: 0, high: 0 })

  return (
    <div className={`rounded-xl p-4 border ${statusDisplay.border} ${statusDisplay.bg}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Thermometer size={18} className={statusDisplay.color} />
          <div>
            <div className={`font-medium ${statusDisplay.color}`}>
              {manual_override ? 'Manual Override' : 'Market Volatility'}
            </div>
            <div className="text-xs text-gray-400">
              {symbols_blocked === 0 ? 'All symbols tradeable' : `${symbols_blocked}/${total_symbols} symbols blocked`}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={fetchVolatility}
            className="p-1.5 hover:bg-gray-700 rounded transition-colors"
            title="Refresh"
          >
            <RefreshCw size={14} className="text-gray-400" />
          </button>
          <button
            onClick={() => setShowSettings(!showSettings)}
            className={`p-1.5 rounded transition-colors ${showSettings ? 'bg-gray-600' : 'hover:bg-gray-700'}`}
            title="Settings"
          >
            <Settings size={14} className="text-gray-400" />
          </button>
        </div>
      </div>

      {/* Status Banner */}
      <div className={`flex items-center justify-between p-2 rounded-lg mb-3 ${
        trading_allowed ? 'bg-green-900/50' : 'bg-red-900/50'
      }`}>
        <div className="flex items-center gap-2">
          {trading_allowed ? (
            <CheckCircle size={16} className="text-green-400" />
          ) : (
            <XCircle size={16} className="text-red-400" />
          )}
          <span className={`font-medium ${trading_allowed ? 'text-green-400' : 'text-red-400'}`}>
            {trading_allowed ? 'Trading ENABLED' : 'Trading DISABLED'}
          </span>
        </div>
        <div className="flex items-center gap-1">
          {!manual_override && (
            <>
              <button
                onClick={() => handleOverride(true)}
                disabled={overriding}
                className="px-2 py-1 text-xs bg-green-700 hover:bg-green-600 rounded transition-colors disabled:opacity-50"
              >
                Enable
              </button>
              <button
                onClick={() => handleOverride(false)}
                disabled={overriding}
                className="px-2 py-1 text-xs bg-red-700 hover:bg-red-600 rounded transition-colors disabled:opacity-50"
              >
                Disable
              </button>
            </>
          )}
          {manual_override && (
            <button
              onClick={handleClearOverride}
              className="px-2 py-1 text-xs bg-gray-600 hover:bg-gray-500 rounded transition-colors"
            >
              Clear Override
            </button>
          )}
        </div>
      </div>

      {/* Per-Symbol Grid */}
      <div className="grid grid-cols-4 gap-2 mb-3">
        {Object.entries(symbols || {}).map(([symbol, data]) => (
          <div
            key={symbol}
            className={`p-2 rounded text-xs ${
              data.status === 'low' ? 'bg-red-900/40 border border-red-800' :
              data.status === 'caution' ? 'bg-yellow-900/40 border border-yellow-800' :
              'bg-green-900/40 border border-green-800'
            }`}
          >
            <div className="flex items-center justify-between mb-1">
              <span className="font-medium">{symbol}</span>
              {data.status === 'low' ? (
                <XCircle size={12} className="text-red-400" />
              ) : data.status === 'caution' ? (
                <AlertTriangle size={12} className="text-yellow-400" />
              ) : (
                <CheckCircle size={12} className="text-green-400" />
              )}
            </div>
            <div className="text-[10px] text-gray-400">
              ATR: {data.atr_percent?.toFixed(4)}%
            </div>
            <div className="text-[10px] text-gray-500">
              Thr: {data.thresholds?.low?.toFixed(3)} / {data.thresholds?.high?.toFixed(3)}
            </div>
          </div>
        ))}
      </div>

      {/* Summary Bar */}
      <div className="flex items-center gap-4 text-xs text-gray-400">
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 rounded-full bg-green-500"></div>
          <span>High: {symbolStatuses.high}</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 rounded-full bg-yellow-500"></div>
          <span>Caution: {symbolStatuses.caution}</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 rounded-full bg-red-500"></div>
          <span>Low: {symbolStatuses.low}</span>
        </div>
        {volatility.volatility_enabled === false && (
          <span className="text-red-400 ml-auto">Volatility filter DISABLED</span>
        )}
      </div>

      {/* Settings Panel */}
      {showSettings && (
        <div className="mt-3 pt-3 border-t border-gray-700">
          <div className="text-xs text-gray-400 mb-2">Volatility filter is always active. Adjust thresholds per symbol in the API.</div>
        </div>
      )}
    </div>
  )
}

export default VolatilityStatus
