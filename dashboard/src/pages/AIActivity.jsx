import React, { useState, useEffect } from 'react'
import {
  Brain,
  Activity,
  TrendingUp,
  TrendingDown,
  CheckCircle,
  XCircle,
  Clock,
  AlertTriangle,
  Zap,
  Shield,
  Eye,
  Trash2
} from 'lucide-react'

const ValidationResult = ({ event }) => {
  const isApproved = event.data?.approved || event.approved
  return (
    <div className={`p-2 rounded border text-xs ${
      isApproved ? 'bg-green-900/20 border-green-700' : 'bg-red-900/20 border-red-700'
    }`}>
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-1">
          <Brain size={12} className="text-purple-400" />
          <span className="font-medium">
            {event.data?.symbol || event.symbol} {event.data?.direction || event.direction}
          </span>
        </div>
        {isApproved ? (
          <span className="flex items-center gap-0.5 text-green-400">
            <CheckCircle size={10} />
            APPROVED
          </span>
        ) : (
          <span className="flex items-center gap-0.5 text-red-400">
            <XCircle size={10} />
            REJECTED
          </span>
        )}
      </div>
      <div className="flex items-center gap-4 text-xs mb-1">
        <div>
          <span className="text-gray-500">Conf: </span>
          <span className="font-mono">{((event.data?.confidence || 0) * 100).toFixed(0)}%</span>
        </div>
        <div>
          <span className="text-gray-500">Risk: </span>
          <span className="font-mono">{((event.data?.risk_score || 0) * 100).toFixed(0)}%</span>
        </div>
        <div>
          <span className="text-gray-500">Latency: </span>
          <span className="font-mono">{event.data?.latency_ms || event.latency_ms || 0}ms</span>
        </div>
      </div>
      <div className="text-gray-500 text-xs line-clamp-1">
        {event.data?.reasoning || event.reasoning || 'N/A'}
      </div>
    </div>
  )
}

const MonitorResult = ({ event }) => {
  const action = event.data?.action || event.action
  const urgency = event.data?.urgency || event.urgency

  const actionColors = {
    HOLD: 'text-gray-400',
    CLOSE: 'text-red-400',
    EXTEND: 'text-green-400',
    TRAIL_STOP: 'text-yellow-400',
    ADJUST_TP: 'text-blue-400'
  }

  return (
    <div className={`p-2 rounded border border-gray-700 bg-gray-900/50 text-xs`}>
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-1">
          <Eye size={12} className="text-blue-400" />
          <span className="font-medium">
            {event.data?.symbol || event.symbol}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <span className={`font-bold ${actionColors[action] || 'text-gray-400'}`}>
            {action}
          </span>
          {urgency === 'high' && (
            <AlertTriangle size={10} className="text-red-400" />
          )}
        </div>
      </div>
      <div className="flex items-center gap-4 text-xs mb-1">
        <div>
          <span className="text-gray-500">Conf: </span>
          <span className="font-mono">{((event.data?.confidence || 0) * 100).toFixed(0)}%</span>
        </div>
        <div>
          <span className="text-gray-500">Urgency: </span>
          <span className={`font-mono ${
            urgency === 'high' ? 'text-red-400' :
            urgency === 'medium' ? 'text-yellow-400' : 'text-green-400'
          }`}>
            {urgency?.toUpperCase() || 'LOW'}
          </span>
        </div>
        {event.data?.new_stop_loss && (
          <div>
            <span className="text-gray-500">New SL: </span>
            <span className="font-mono text-yellow-400">{event.data.new_stop_loss}</span>
          </div>
        )}
      </div>
      <div className="text-gray-500 text-xs line-clamp-1">
        {event.data?.reasoning || event.reasoning || 'N/A'}
      </div>
    </div>
  )
}

export default function AIActivity() {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')

  const fetchActivity = async () => {
    try {
      const res = await fetch('/api/ai-activity?limit=50')
      const data = await res.json()
      setEvents(data.events || [])
    } catch (err) {
      console.error('Failed to fetch AI activity:', err)
    }
    setLoading(false)
  }

  const clearActivity = async () => {
    if (!confirm('Clear all AI activity logs?')) return
    try {
      await fetch('/api/ai-activity', { method: 'DELETE' })
      setEvents([])
    } catch (err) {
      console.error('Failed to clear AI activity:', err)
    }
  }

  useEffect(() => {
    fetchActivity()
    const interval = setInterval(fetchActivity, 5000)
    return () => clearInterval(interval)
  }, [])

  const filteredEvents = events.filter(event => {
    if (filter === 'all') return true
    if (filter === 'approved') return event.data?.approved || event.approved === true
    if (filter === 'rejected') return event.data?.approved === false || event.approved === false
    if (filter === 'monitor') return event.type === 'position_monitor'
    if (filter === 'validation') return event.type === 'signal_validation'
    return true
  })

  const approvedCount = events.filter(e => e.data?.approved || e.approved === true).length
  const rejectedCount = events.filter(e => e.data?.approved === false || e.approved === false).length
  const avgConf = events.length > 0
    ? ((events.reduce((sum, e) => sum + (e.data?.confidence || e.confidence || 0), 0) / events.length) * 100).toFixed(0)
    : 0

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain size={20} className="text-purple-400" />
          <h1 className="text-lg font-bold">AI Activity</h1>
        </div>
        <div className="flex items-center gap-1 text-xs text-gray-400">
          <Activity size={12} />
          Live
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-2">
        <div className="bg-gray-800 rounded-lg p-2 border border-gray-700 text-xs">
          <div className="text-gray-400">Total</div>
          <div className="text-lg font-bold">{events.length}</div>
        </div>
        <div className="bg-gray-800 rounded-lg p-2 border border-gray-700 text-xs">
          <div className="text-gray-400">Approved</div>
          <div className="text-lg font-bold text-green-400">{approvedCount}</div>
        </div>
        <div className="bg-gray-800 rounded-lg p-2 border border-gray-700 text-xs">
          <div className="text-gray-400">Rejected</div>
          <div className="text-lg font-bold text-red-400">{rejectedCount}</div>
        </div>
        <div className="bg-gray-800 rounded-lg p-2 border border-gray-700 text-xs">
          <div className="text-gray-400">Avg Conf</div>
          <div className="text-lg font-bold">{avgConf}%</div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-1 items-center">
        <button
          onClick={clearActivity}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-red-900/50 text-red-400 hover:bg-red-900 border border-red-700"
        >
          <Trash2 size={10} />
          Clear
        </button>
        <div className="flex-1"/>
        {['all', 'validation', 'monitor', 'approved', 'rejected'].map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-2 py-1 rounded text-xs ${
              filter === f
                ? 'bg-purple-600 text-white'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      {/* Event Feed */}
      {loading ? (
        <div className="text-center py-8 text-gray-500 text-xs">
          Loading...
        </div>
      ) : filteredEvents.length === 0 ? (
        <div className="text-center py-8 text-gray-500 text-xs">
          No AI activity
        </div>
      ) : (
        <div className="space-y-2">
          {filteredEvents.map((event, i) => (
            <div key={i}>
              {event.type === 'signal_validation' || event.symbol ? (
                <ValidationResult event={event} />
              ) : (
                <MonitorResult event={event} />
              )}
              <div className="text-xs text-gray-600 mt-0.5 ml-1">
                {new Date(event.timestamp || event.data?.timestamp || Date.now()).toLocaleTimeString()}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
