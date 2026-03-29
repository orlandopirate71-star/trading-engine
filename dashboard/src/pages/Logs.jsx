import React, { useState, useEffect } from 'react'
import {
  FileText,
  RefreshCw,
  Download,
  Trash2,
  Clock
} from 'lucide-react'

const LogViewer = ({ logName, title }) => {
  const [lines, setLines] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [lastUpdate, setLastUpdate] = useState(null)

  const fetchLog = async () => {
    setLoading(true)
    try {
      const res = await fetch(`/api/logs/${logName}?lines=200`)
      const data = await res.json()
      if (data.error) {
        setError(data.error)
        setLines([])
      } else {
        setLines(data.lines || [])
        setError(null)
      }
      setLastUpdate(new Date())
    } catch (err) {
      setError('Failed to load log')
      setLines([])
    }
    setLoading(false)
  }

  useEffect(() => {
    fetchLog()
    const interval = setInterval(fetchLog, 5000) // Auto-refresh every 5s
    return () => clearInterval(interval)
  }, [logName])

  const downloadLog = () => {
    const content = lines.join('\n')
    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = logName
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700">
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-700">
        <div className="flex items-center gap-2">
          <FileText size={14} className="text-gray-400" />
          <h3 className="font-medium text-xs">{title}</h3>
          <span className="text-xs text-gray-500">({lines.length})</span>
        </div>
        <div className="flex items-center gap-1">
          {lastUpdate && (
            <span className="text-xs text-gray-500 flex items-center gap-1">
              <Clock size={10} />
              {lastUpdate.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={fetchLog}
            className="p-1.5 hover:bg-gray-700 rounded transition-colors"
            title="Refresh"
          >
            <RefreshCw size={12} className="text-gray-400" />
          </button>
          <button
            onClick={downloadLog}
            className="p-1.5 hover:bg-gray-700 rounded transition-colors"
            title="Download"
          >
            <Download size={12} className="text-gray-400" />
          </button>
        </div>
      </div>

      <div className="h-64 overflow-auto">
        {loading && lines.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="animate-pulse text-gray-500">Loading...</div>
          </div>
        ) : error ? (
          <div className="flex items-center justify-center h-full text-red-400 text-xs">
            {error}
          </div>
        ) : lines.length === 0 ? (
          <div className="flex items-center justify-center h-full text-gray-500 text-xs">
            No log data
          </div>
        ) : (
          <pre className="p-2 text-xs font-mono text-gray-300 leading-relaxed whitespace-pre-wrap">
            {lines.map((line, i) => (
              <div
                key={i}
                className={
                  line.includes('ERROR') ? 'text-red-400' :
                  line.includes('WARNING') || line.includes('WARN') ? 'text-yellow-400' :
                  line.includes('ENGINE') ? 'text-blue-400' :
                  line.includes('OANDA') ? 'text-green-400' :
                  line.includes('SCREENSHOT') ? 'text-purple-400' :
                  'text-gray-400'
                }
              >
                {line}
              </div>
            ))}
          </pre>
        )}
      </div>
    </div>
  )
}

const Logs = () => {
  const [activeTab, setActiveTab] = useState('api.log')

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-bold">System Logs</h1>
      </div>

      {/* Log Selection Tabs */}
      <div className="flex gap-1 text-xs">
        <button
          onClick={() => setActiveTab('api.log')}
          className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
            activeTab === 'api.log'
              ? 'bg-blue-600 text-white'
              : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
          }`}
        >
          API
        </button>
        <button
          onClick={() => setActiveTab('feeds.log')}
          className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
            activeTab === 'feeds.log'
              ? 'bg-blue-600 text-white'
              : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
          }`}
        >
          Feeds
        </button>
        <button
          onClick={() => setActiveTab('dashboard.log')}
          className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
            activeTab === 'dashboard.log'
              ? 'bg-blue-600 text-white'
              : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
          }`}
        >
          Dashboard
        </button>
      </div>

      {/* Log Viewer */}
      {activeTab === 'api.log' && (
        <LogViewer logName="api.log" title="API Server Log" />
      )}
      {activeTab === 'feeds.log' && (
        <LogViewer logName="feeds.log" title="Data Feeds Log" />
      )}
      {activeTab === 'dashboard.log' && (
        <LogViewer logName="dashboard.log" title="Dashboard Log" />
      )}

      {/* Log Legend */}
      <div className="bg-gray-800 rounded-lg p-3 border border-gray-700">
        <h3 className="text-xs font-medium mb-2">Color Legend</h3>
        <div className="flex flex-wrap gap-3 text-xs">
          <span className="text-red-400">ERROR</span>
          <span className="text-yellow-400">WARNING</span>
          <span className="text-blue-400">ENGINE</span>
          <span className="text-green-400">OANDA</span>
          <span className="text-purple-400">SCREENSHOT</span>
        </div>
      </div>
    </div>
  )
}

export default Logs
