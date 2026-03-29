import React, { useState, useEffect } from 'react'
import {
  Target,
  RefreshCw,
  CheckCircle,
  XCircle,
  AlertTriangle,
  ToggleLeft,
  ToggleRight,
  FileCode,
  Clock,
  Info,
  X,
  TrendingUp,
  TrendingDown
} from 'lucide-react'
import { format } from 'date-fns'

const StrategyModal = ({ strategy, onClose }) => {
  if (!strategy) return null

  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4">
      <div className="bg-gray-800 rounded-xl border border-gray-700 max-w-2xl w-full max-h-[80vh] overflow-auto">
        <div className="sticky top-0 bg-gray-800 border-b border-gray-700 p-3 flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
              strategy.enabled ? 'bg-green-900' : 'bg-gray-700'
            }`}>
              {strategy.enabled ? (
                <CheckCircle className="text-green-400" size={16} />
              ) : (
                <XCircle className="text-gray-400" size={16} />
              )}
            </div>
            <div>
              <h2 className="text-sm font-bold">{strategy.name}</h2>
              <div className="text-xs text-gray-500">{strategy.file?.split('/').pop()}</div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 hover:bg-gray-700 rounded transition-colors"
          >
            <X size={14} className="text-gray-400" />
          </button>
        </div>

        <div className="p-3 space-y-4">
          {strategy.description && (
            <div>
              <h3 className="text-xs font-medium text-gray-400 mb-1">Description</h3>
              <p className="text-gray-300 text-xs whitespace-pre-wrap">{strategy.description}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-2">
            <div className="bg-gray-900 rounded-lg p-3">
              <div className="text-xs text-gray-400 mb-1">Status</div>
              <div className={`font-medium text-xs ${strategy.enabled ? 'text-green-400' : 'text-gray-500'}`}>
                {strategy.enabled ? '● Active' : '○ Inactive'}
              </div>
            </div>
            <div className="bg-gray-900 rounded-lg p-3">
              <div className="text-xs text-gray-400 mb-1">Max Positions</div>
              <div className="font-medium text-xs">{strategy.max_positions || 'Unlimited'}</div>
            </div>
            <div className="bg-gray-900 rounded-lg p-3">
              <div className="text-xs text-gray-400 mb-1">Per Symbol</div>
              <div className="font-medium text-xs">{strategy.max_positions_per_symbol || 1}</div>
            </div>
            <div className="bg-gray-900 rounded-lg p-3">
              <div className="text-xs text-gray-400 mb-1">Last Modified</div>
              <div className="font-medium text-xs">
                {strategy.last_modified ? format(new Date(strategy.last_modified), 'MMM d, yyyy HH:mm') : 'Unknown'}
              </div>
            </div>
          </div>

          <div>
            <h3 className="text-xs font-medium text-gray-400 mb-2">Trading Symbols</h3>
            <div className="flex flex-wrap gap-1">
              {strategy.symbols && strategy.symbols.length > 0 ? (
                strategy.symbols.map((symbol) => (
                  <span
                    key={symbol}
                    className="px-2 py-0.5 bg-gray-900 rounded text-xs font-mono"
                  >
                    {symbol}
                  </span>
                ))
              ) : (
                <span className="text-gray-500 text-xs">All active symbols</span>
              )}
            </div>
          </div>

          {strategy.error && (
            <div className="bg-red-900/30 border border-red-800 rounded-lg p-3">
              <div className="text-xs text-red-400 font-medium mb-1">Error</div>
              <div className="text-xs text-red-300 font-mono break-all">{strategy.error}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function Strategies() {
  const [strategies, setStrategies] = useState([])
  const [loading, setLoading] = useState(true)
  const [reloading, setReloading] = useState(false)
  const [selectedStrategy, setSelectedStrategy] = useState(null)

  useEffect(() => {
    fetchStrategies()
  }, [])

  const fetchStrategies = async () => {
    try {
      const res = await fetch('/api/strategies')
      setStrategies(await res.json())
    } catch (err) {
      console.error('Failed to fetch strategies:', err)
    }
    setLoading(false)
  }

  const toggleStrategy = async (name, enabled) => {
    try {
      await fetch(`/api/strategies/${name}/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !enabled })
      })
      fetchStrategies()
    } catch (err) {
      console.error('Failed to toggle strategy:', err)
    }
  }

  const reloadAll = async () => {
    setReloading(true)
    try {
      await fetch('/api/strategies/reload', { method: 'POST' })
      await fetchStrategies()
    } catch (err) {
      console.error('Failed to reload strategies:', err)
    }
    setReloading(false)
  }

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-bold">Strategies</h1>
        <button
          onClick={reloadAll}
          disabled={reloading}
          className="flex items-center gap-1 px-2 py-1 bg-blue-600 hover:bg-blue-700 rounded text-xs font-medium disabled:opacity-50"
        >
          <RefreshCw size={12} className={reloading ? 'animate-spin' : ''} />
          Reload
        </button>
      </div>

      {/* Info Box */}
      <div className="bg-blue-900/30 border border-blue-700 rounded-lg p-3">
        <div className="flex items-start gap-2">
          <Target className="text-blue-400 mt-0.5" size={14} />
          <div>
            <div className="font-medium text-blue-300 text-xs">Hot Reload Enabled</div>
            <div className="text-xs text-blue-400/80 mt-0.5">
              Strategies auto-reload on file changes. Create .py file with <code className="bg-blue-900/50 px-1 rounded">name</code> and <code className="bg-blue-900/50 px-1 rounded">on_tick()</code>.
            </div>
          </div>
        </div>
      </div>

      {/* Strategies Grid */}
      {loading ? (
        <div className="text-center py-12 text-gray-400">Loading strategies...</div>
      ) : strategies.length === 0 ? (
        <div className="bg-gray-800 rounded-xl p-12 border border-gray-700 text-center">
          <FileCode size={48} className="mx-auto text-gray-600 mb-4" />
          <h2 className="text-xl font-bold mb-2">No Strategies Found</h2>
          <p className="text-gray-400 mb-4">
            Add Python strategy files to the <code className="bg-gray-700 px-2 py-1 rounded">strategies/</code> folder to get started.
          </p>
          <div className="bg-gray-900 rounded-lg p-4 text-left max-w-md mx-auto">
            <div className="text-sm text-gray-400 mb-2">Example: strategies/my_strategy.py</div>
            <pre className="text-xs text-green-400 overflow-auto">{`from strategy_loader import BaseStrategy

class MyStrategy(BaseStrategy):
    name = "MyStrategy"
    
    def on_tick(self, symbol, price, timestamp):
        # Your logic here
        if should_buy:
            return self.create_signal(
                symbol=symbol,
                direction="LONG",
                entry_price=price,
                stop_loss=price * 0.98,
                take_profit=price * 1.04,
                confidence=0.7,
                reason="My buy reason"
            )
        return None`}</pre>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {strategies.map((strategy) => (
            <div
              key={strategy.name}
              onClick={() => setSelectedStrategy(strategy)}
              className={`bg-gray-800 rounded-lg p-4 border transition-all cursor-pointer hover:border-blue-500 hover:bg-gray-750 text-xs ${
                strategy.enabled
                  ? 'border-green-700'
                  : strategy.error
                    ? 'border-red-700'
                    : 'border-gray-700'
              }`}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-2">
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                    strategy.enabled ? 'bg-green-900' :
                    strategy.error ? 'bg-red-900' : 'bg-gray-700'
                  }`}>
                    {strategy.error ? (
                      <AlertTriangle className="text-red-400" size={14} />
                    ) : strategy.enabled ? (
                      <CheckCircle className="text-green-400" size={14} />
                    ) : (
                      <XCircle className="text-gray-400" size={14} />
                    )}
                  </div>
                  <div>
                    <h3 className="font-bold text-sm">{strategy.name}</h3>
                    <div className="text-xs text-gray-500 truncate max-w-[120px]">
                      {strategy.file?.split('/').pop()}
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-1">
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      setSelectedStrategy(strategy)
                    }}
                    className="p-1.5 rounded hover:bg-gray-700 transition-colors text-gray-400 hover:text-blue-400"
                    title="View Details"
                  >
                    <Info size={14} />
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      toggleStrategy(strategy.name, strategy.enabled)
                    }}
                    disabled={!!strategy.error}
                    className={`p-1 rounded transition-colors ${
                      strategy.error ? 'opacity-50 cursor-not-allowed' : 'hover:bg-gray-700'
                    }`}
                  >
                    {strategy.enabled ? (
                      <ToggleRight size={22} className="text-green-400" />
                    ) : (
                      <ToggleLeft size={22} className="text-gray-500" />
                    )}
                  </button>
                </div>
              </div>

              {strategy.error && (
                <div className="bg-red-900/30 border border-red-800 rounded-lg p-2 mb-3">
                  <div className="text-xs text-red-400 font-mono break-all">
                    {strategy.error}
                  </div>
                </div>
              )}

              <div className="flex items-center gap-2 text-xs text-gray-400">
                <Clock size={12} />
                <span>
                  {strategy.last_modified ?
                    format(new Date(strategy.last_modified), 'MMM d, HH:mm') :
                    'Unknown'
                  }
                </span>
              </div>

              <div className={`mt-3 pt-3 border-t border-gray-700 text-xs ${
                strategy.enabled ? 'text-green-400' : 'text-gray-500'
              }`}>
                {strategy.enabled ? '● Active' : '○ Inactive'}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Strategy Template */}
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
        <h2 className="text-sm font-semibold mb-2">Strategy Template</h2>
        <p className="text-gray-400 text-xs mb-3">
          Copy this template to create a new strategy. Save it as a .py file in the strategies folder.
        </p>
        <pre className="bg-gray-900 rounded-lg p-3 text-xs overflow-auto">{`from strategy_loader import BaseStrategy
from models import TradeSignal, TradeDirection
from datetime import datetime

class MyCustomStrategy(BaseStrategy):
    name = "MyCustomStrategy"
    symbols = ["BTCUSDT"]

    def on_tick(self, symbol: str, price: float, timestamp: datetime):
        self.prices.append(price)
        if len(self.prices) > self.lookback:
            self.prices.pop(0)
        if len(self.prices) < self.lookback:
            return None
        avg = sum(self.prices) / len(self.prices)
        if price > avg * 1.01 and self.prices[-2] <= avg:
            return self.create_signal(
                symbol=symbol, direction="LONG", entry_price=price,
                stop_loss=price * 0.98, take_profit=price * 1.04,
                confidence=0.7, reason=f"MA crossover"
            )
        return None`}</pre>
      </div>

      {/* Strategy Detail Modal */}
      <StrategyModal
        strategy={selectedStrategy}
        onClose={() => setSelectedStrategy(null)}
      />
    </div>
  )
}
