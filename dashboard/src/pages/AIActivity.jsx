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
  Eye
} from 'lucide-react'

const EventIcon = ({ type }) => {
  switch (type) {
    case 'signal_validation':
      return <Brain size={16} className="text-purple-400" />
    case 'position_monitor':
      return <Eye size={16} className="text-blue-400" />
    case 'action':
      return <Zap size={16} className="text-yellow-400" />
    default:
      return <Activity size={16} className="text-gray-400" />
  }
}

const ValidationResult = ({ event }) => {
  const isApproved = event.data?.approved || event.approved
  return (
    <div className={`p-4 rounded-lg border ${
      isApproved ? 'bg-green-900/20 border-green-700' : 'bg-red-900/20 border-red-700'
    }`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Brain size={16} className="text-purple-400" />
          <span className="font-medium">
            {event.data?.symbol || event.symbol} {event.data?.direction || event.direction}
          </span>
        </div>
        {isApproved ? (
          <span className="flex items-center gap-1 text-green-400 text-sm">
            <CheckCircle size={14} />
            APPROVED
          </span>
        ) : (
          <span className="flex items-center gap-1 text-red-400 text-sm">
            <XCircle size={14} />
            REJECTED
          </span>
        )}
      </div>
      <div className="grid grid-cols-3 gap-4 text-sm mb-3">
        <div>
          <div className="text-gray-400">Confidence</div>
          <div className="font-mono">{((event.data?.confidence || 0) * 100).toFixed(0)}%</div>
        </div>
        <div>
          <div className="text-gray-400">Risk Score</div>
          <div className="font-mono">{((event.data?.risk_score || 0) * 100).toFixed(0)}%</div>
        </div>
        <div>
          <div className="text-gray-400">Latency</div>
          <div className="font-mono">{event.data?.latency_ms || event.latency_ms || 0}ms</div>
        </div>
      </div>
      <div className="text-xs text-gray-400 mb-2">
        Reasoning: {event.data?.reasoning || event.reasoning || 'N/A'}
      </div>
      {event.data?.recommendations?.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {event.data.recommendations.map((rec, i) => (
            <span key={i} className="text-xs px-2 py-0.5 bg-gray-800 rounded text-gray-300">
              {rec}
            </span>
          ))}
        </div>
      )}
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
    <div className={`p-4 rounded-lg border border-gray-700 bg-gray-900/50`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Eye size={16} className="text-blue-400" />
          <span className="font-medium">
            {event.data?.symbol || event.symbol}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className={`font-bold ${actionColors[action] || 'text-gray-400'}`}>
            {action}
          </span>
          {urgency === 'high' && (
            <AlertTriangle size={14} className="text-red-400" />
          )}
        </div>
      </div>
      <div className="grid grid-cols-3 gap-4 text-sm mb-3">
        <div>
          <div className="text-gray-400">Confidence</div>
          <div className="font-mono">{((event.data?.confidence || 0) * 100).toFixed(0)}%</div>
        </div>
        <div>
          <div className="text-gray-400">Urgency</div>
          <div className={`font-mono ${
            urgency === 'high' ? 'text-red-400' :
            urgency === 'medium' ? 'text-yellow-400' : 'text-green-400'
          }`}>
            {urgency?.toUpperCase() || 'LOW'}
          </div>
        </div>
        {event.data?.new_stop_loss && (
          <div>
            <div className="text-gray-400">New SL</div>
            <div className="font-mono text-yellow-400">
              {event.data.new_stop_loss}
            </div>
          </div>
        )}
      </div>
      <div className="text-xs text-gray-400">
        {event.data?.reasoning || event.reasoning || 'N/A'}
      </div>
      {event.data?.warnings?.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {event.data.warnings.map((warn, i) => (
            <span key={i} className="text-xs px-2 py-0.5 bg-red-900/50 rounded text-red-300">
              {warn}
            </span>
          ))}
        </div>
      )}
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

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Brain size={28} className="text-purple-400" />
          <h1 className="text-2xl font-bold">AI Activity</h1>
        </div>
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <Activity size={16} />
          Live updates every 5s
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="text-gray-400 text-sm">Total Validations</div>
          <div className="text-2xl font-bold">{events.length}</div>
        </div>
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="text-gray-400 text-sm">Approved</div>
          <div className="text-2xl font-bold text-green-400">
            {events.filter(e => e.data?.approved || e.approved === true).length}
          </div>
        </div>
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="text-gray-400 text-sm">Rejected</div>
          <div className="text-2xl font-bold text-red-400">
            {events.filter(e => e.data?.approved === false || e.approved === false).length}
          </div>
        </div>
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
          <div className="text-gray-400 text-sm">Avg Confidence</div>
          <div className="text-2xl font-bold">
            {events.length > 0
              ? ((events.reduce((sum, e) => sum + (e.data?.confidence || e.confidence || 0), 0) / events.length) * 100).toFixed(0)
              : 0}%
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2">
        {['all', 'validation', 'monitor', 'approved', 'rejected'].map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
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
        <div className="text-center py-12 text-gray-500">
          Loading AI activity...
        </div>
      ) : filteredEvents.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          No AI activity yet
        </div>
      ) : (
        <div className="space-y-4">
          {filteredEvents.map((event, i) => (
            <div key={i}>
              {event.type === 'signal_validation' || event.symbol ? (
                <ValidationResult event={event} />
              ) : (
                <MonitorResult event={event} />
              )}
              <div className="text-xs text-gray-500 mt-1">
                {new Date(event.timestamp || event.data?.timestamp || Date.now()).toLocaleString()}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
