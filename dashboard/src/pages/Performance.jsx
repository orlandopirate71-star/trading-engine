import React, { useState, useEffect } from 'react'
import {
  TrendingUp,
  TrendingDown,
  Target,
  DollarSign,
  BarChart3,
  Calendar
} from 'lucide-react'
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Cell
} from 'recharts'

const StatCard = ({ title, value, icon: Icon, color, subtext }) => (
  <div className="bg-gray-800 rounded-xl p-3 border border-gray-700">
    <div className="flex items-center justify-between mb-1">
      <span className="text-gray-400 text-xs">{title}</span>
      <Icon className={color} size={14} />
    </div>
    <div className="text-lg font-bold">{value}</div>
    {subtext && <div className="text-xs text-gray-500">{subtext}</div>}
  </div>
)

export default function Performance() {
  const [performance, setPerformance] = useState(null)
  const [strategyPerformance, setStrategyPerformance] = useState(null)
  const [days, setDays] = useState(30)
  const [loading, setLoading] = useState(true)
  const [brokerMode, setBrokerMode] = useState(null)

  useEffect(() => {
    fetchPerformance()
    fetchStrategyPerformance()
  }, [days])

  const fetchPerformance = async () => {
    setLoading(true)
    try {
      // Check broker mode
      const brokerRes = await fetch('/api/broker')
      const broker = await brokerRes.json()
      setBrokerMode(broker)

      if (broker.mode === 'oanda' && broker.oanda_available) {
        // Fetch OANDA performance
        const res = await fetch(`/api/oanda/performance?days=${days}`)
        const data = await res.json()
        setPerformance(data)
      } else {
        // Fetch paper trading performance
        const res = await fetch(`/api/performance?days=${days}`)
        const data = await res.json()
        // Transform paper performance to match expected format
        setPerformance({
          stats: data.stats || {},
          daily_pnl: data.daily_pnl || [],
          cumulative_pnl: data.cumulative_pnl || [],
          by_symbol: []
        })
      }
    } catch (err) {
      console.error('Failed to fetch performance:', err)
    }
    setLoading(false)
  }

  const fetchStrategyPerformance = async () => {
    try {
      const res = await fetch(`/api/strategy-performance?days=${days}`)
      const data = await res.json()
      setStrategyPerformance(data)
    } catch (err) {
      console.error('Failed to fetch strategy performance:', err)
    }
  }

  const stats = performance?.stats || {}

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h1 className="text-lg font-bold">Performance</h1>
          {brokerMode?.mode === 'oanda' && (
            <span className="px-2 py-0.5 bg-blue-900 text-blue-300 text-xs rounded-full">
              OANDA Demo
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Calendar size={14} className="text-gray-400" />
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs"
          >
            <option value={7}>7D</option>
            <option value={30}>30D</option>
            <option value={90}>90D</option>
          </select>
        </div>
      </div>

      {loading ? (
        <div className="text-center py-8 text-gray-400">Loading...</div>
      ) : (
        <>
          {/* Stats Grid */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
            <StatCard
              title="Total P&L"
              value={`${stats.total_pnl >= 0 ? '+' : ''}$${stats.total_pnl?.toFixed(2) || '0.00'}`}
              icon={DollarSign}
              color={stats.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}
              subtext={`${stats.total_trades || 0} trades`}
            />
            <StatCard
              title="Win Rate"
              value={`${stats.win_rate?.toFixed(1) || 0}%`}
              icon={Target}
              color="text-blue-400"
              subtext={`${stats.winning_trades || 0}W / ${stats.losing_trades || 0}L`}
            />
            <StatCard
              title="Avg Win"
              value={`+$${stats.avg_win?.toFixed(2) || '0.00'}`}
              icon={TrendingUp}
              color="text-green-400"
            />
            <StatCard
              title="Avg Loss"
              value={`-$${Math.abs(stats.avg_loss || 0).toFixed(2)}`}
              icon={TrendingDown}
              color="text-red-400"
            />
          </div>

          {/* Additional Stats */}
          <div className="grid grid-cols-3 gap-2">
            <div className="bg-gray-800 rounded-xl p-3 border border-gray-700">
              <div className="text-gray-400 text-xs mb-1">Profit Factor</div>
              <div className="text-xl font-bold">
                {stats.profit_factor?.toFixed(2) || '0.00'}
              </div>
              <div className="text-xs text-gray-500">
                {stats.profit_factor >= 1.5 ? 'Good' : stats.profit_factor >= 1 ? 'Break-even' : 'Needs work'}
              </div>
            </div>
            <div className="bg-gray-800 rounded-xl p-3 border border-gray-700">
              <div className="text-gray-400 text-xs mb-1">Avg P&L %</div>
              <div className={`text-xl font-bold ${stats.avg_pnl_percent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {stats.avg_pnl_percent >= 0 ? '+' : ''}{stats.avg_pnl_percent?.toFixed(2) || '0.00'}%
              </div>
            </div>
            <div className="bg-gray-800 rounded-xl p-3 border border-gray-700">
              <div className="text-gray-400 text-xs mb-1">Breakeven</div>
              <div className="text-xl font-bold">
                {stats.breakeven_trades || 0}
              </div>
            </div>
          </div>

          {/* Cumulative P&L Chart */}
          <div className="bg-gray-800 rounded-xl p-3 border border-gray-700">
            <h2 className="text-sm font-semibold mb-2">Cumulative P&L</h2>
            {performance?.cumulative_pnl?.length > 0 ? (
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={performance.cumulative_pnl}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis
                      dataKey="date"
                      stroke="#6b7280"
                      tickFormatter={(val) => new Date(val).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                    />
                    <YAxis stroke="#6b7280" />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151' }}
                      labelStyle={{ color: '#9ca3af' }}
                      formatter={(value) => [`$${value.toFixed(2)}`, 'Cumulative P&L']}
                    />
                    <Line
                      type="monotone"
                      dataKey="cumulative_pnl"
                      stroke="#10b981"
                      strokeWidth={2}
                      dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="h-48 flex items-center justify-center text-gray-500 text-xs">
                No data
              </div>
            )}
          </div>

          {/* Daily P&L Chart */}
          <div className="bg-gray-800 rounded-xl p-3 border border-gray-700">
            <h2 className="text-sm font-semibold mb-2">Daily P&L</h2>
            {performance?.daily_pnl?.length > 0 ? (
              <div className="h-40">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={performance.daily_pnl}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis
                      dataKey="date"
                      stroke="#6b7280"
                      tickFormatter={(val) => new Date(val).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                    />
                    <YAxis stroke="#6b7280" />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151' }}
                      labelStyle={{ color: '#9ca3af' }}
                      formatter={(value) => [`$${value.toFixed(2)}`, 'P&L']}
                    />
                    <Bar dataKey="pnl">
                      {performance.daily_pnl.map((entry, index) => (
                        <Cell
                          key={`cell-${index}`}
                          fill={entry.pnl >= 0 ? '#10b981' : '#ef4444'}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="h-40 flex items-center justify-center text-gray-500 text-xs">
                No data
              </div>
            )}
          </div>

          {/* Performance by Symbol */}
          {performance?.by_symbol?.length > 0 && (
            <div className="bg-gray-800 rounded-xl p-3 border border-gray-700">
              <h2 className="text-sm font-semibold mb-2 flex items-center gap-2">
                <BarChart3 size={14} />
                By Symbol
              </h2>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-gray-700">
                      <th className="px-2 py-2 text-left text-gray-400 uppercase">Symbol</th>
                      <th className="px-2 py-2 text-right text-gray-400 uppercase">Trades</th>
                      <th className="px-2 py-2 text-right text-gray-400 uppercase">Win Rate</th>
                      <th className="px-2 py-2 text-right text-gray-400 uppercase">P&L</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-700">
                    {performance.by_symbol.map((sym) => (
                      <tr key={sym.symbol} className="hover:bg-gray-750">
                        <td className="px-2 py-2 font-medium">{sym.symbol}</td>
                        <td className="px-2 py-2 text-right">{sym.total_trades}</td>
                        <td className="px-2 py-2 text-right">
                          <span className={sym.win_rate >= 50 ? 'text-green-400' : 'text-red-400'}>
                            {sym.win_rate.toFixed(1)}%
                          </span>
                        </td>
                        <td className="px-2 py-2 text-right">
                          <span className={`font-mono ${sym.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                            {sym.total_pnl >= 0 ? '+' : ''}${sym.total_pnl.toFixed(2)}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Strategy Performance */}
          {strategyPerformance?.strategies?.length > 0 && (
            <div className="bg-gray-800 rounded-xl p-3 border border-gray-700">
              <h2 className="text-sm font-semibold mb-2 flex items-center gap-2">
                <BarChart3 size={14} />
                Strategy Performance
              </h2>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-gray-700">
                      <th className="px-2 py-2 text-left text-gray-400 uppercase">Strategy</th>
                      <th className="px-2 py-2 text-right text-gray-400 uppercase">Trades</th>
                      <th className="px-2 py-2 text-right text-gray-400 uppercase">W/L</th>
                      <th className="px-2 py-2 text-right text-gray-400 uppercase">Win%</th>
                      <th className="px-2 py-2 text-right text-gray-400 uppercase">Total P&L</th>
                      <th className="px-2 py-2 text-right text-gray-400 uppercase">Avg P&L</th>
                      <th className="px-2 py-2 text-right text-gray-400 uppercase">P.Factor</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-700">
                    {strategyPerformance.strategies.map((strat) => (
                      <tr key={strat.strategy} className="hover:bg-gray-750">
                        <td className="px-2 py-2 font-medium">{strat.strategy}</td>
                        <td className="px-2 py-2 text-right">{strat.total_trades}</td>
                        <td className="px-2 py-2 text-right text-gray-400">
                          {strat.winning_trades}/{strat.losing_trades}
                        </td>
                        <td className="px-2 py-2 text-right">
                          <span className={strat.win_rate >= 50 ? 'text-green-400' : 'text-red-400'}>
                            {strat.win_rate.toFixed(1)}%
                          </span>
                        </td>
                        <td className="px-2 py-2 text-right">
                          <span className={`font-mono font-semibold ${strat.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                            {strat.total_pnl >= 0 ? '+' : ''}${strat.total_pnl.toFixed(2)}
                          </span>
                        </td>
                        <td className="px-2 py-2 text-right">
                          <span className={`font-mono ${strat.avg_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                            {strat.avg_pnl >= 0 ? '+' : ''}${strat.avg_pnl.toFixed(2)}
                          </span>
                        </td>
                        <td className="px-2 py-2 text-right">
                          <span className={strat.profit_factor >= 1.5 ? 'text-green-400' : strat.profit_factor >= 1 ? 'text-yellow-400' : 'text-red-400'}>
                            {strat.profit_factor.toFixed(2)}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="mt-2 pt-2 border-t border-gray-700 text-xs text-gray-400">
                <div className="flex justify-between">
                  <span>Total: {strategyPerformance.total_strategies} strategies</span>
                  <span>Period: {days} days</span>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
