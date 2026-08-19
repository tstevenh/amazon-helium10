'use client'
/**
 * Notifications.
 *
 * Alerting already existed via a webhook, and eight consecutive failed syncs
 * were still missed for a week — because an unconfigured webhook logs to
 * stderr and nobody reads stderr. So this screen reads notification_log
 * directly: the app can tell you what it noticed even with nothing configured.
 *
 * That is what `logged_only` means, and the banner says so in plain words
 * rather than showing a status code nobody can interpret.
 */
import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/context/AuthContext'
import { api, ApiError } from '@/lib/api'
import type { NotificationEntry, DigestPreview } from '@/lib/types'
import { Notice } from '@/components/ui/Notice'
import { PageHeader } from '@/components/layout/PageHeader'
import { LoadingState } from '@/components/ui/LoadingState'
import { ErrorState } from '@/components/ui/ErrorState'

const STATUS_STYLE: Record<string, string> = {
  delivered:   'bg-ok-tint text-ok',
  failed:      'bg-danger-tint text-danger',
  logged_only: 'bg-warn-tint text-warn',
}

const STATUS_LABEL: Record<string, string> = {
  delivered:   'sent',
  failed:      'send failed',
  logged_only: 'not sent anywhere',
}

const EVENT_LABEL: Record<string, string> = {
  sync_failed:         'Sync problem',
  sync_stale:          'Data is stale',
  suggestions_pending: 'Suggestions waiting',
  execution_failed:    'Change failed',
  dayparting_failed:   'Dayparting problem',
  daily_digest:        'Daily digest',
}

export default function NotificationsPage() {
  const { user, loading: authLoading } = useAuth()
  const router = useRouter()

  const [items, setItems]     = useState<NotificationEntry[]>([])
  const [unread, setUnread]   = useState(0)
  const [hasWebhook, setHasWebhook] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState<string | null>(null)
  const [preview, setPreview] = useState<DigestPreview | null>(null)
  const [toast, setToast]     = useState<string | null>(null)

  useEffect(() => {
    if (!authLoading && !user) router.push('/login')
  }, [authLoading, user, router])

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const page = await api.listNotifications({ limit: 100 })
      setItems(page.items)
      setUnread(page.unread)
      setHasWebhook(page.webhook_configured)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load notifications')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { if (user) load() }, [user, load])

  function notify(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(null), 5000)
  }

  async function markAll() {
    await api.markAllNotificationsRead()
    setItems(list => list.map(i => ({ ...i, read_at: i.read_at ?? new Date().toISOString() })))
    setUnread(0)
  }

  async function markOne(n: NotificationEntry) {
    if (n.read_at) return
    await api.markNotificationRead(n.id)
    setItems(list => list.map(i => i.id === n.id ? { ...i, read_at: new Date().toISOString() } : i))
    setUnread(u => Math.max(0, u - 1))
  }

  async function showPreview() {
    try {
      setPreview(await api.previewDigest())
    } catch (e) {
      notify(e instanceof ApiError ? e.message : 'Could not build preview')
    }
  }

  async function sendNow() {
    try {
      const row = await api.sendTestDigest()
      notify(
        row.delivery_status === 'delivered'
          ? 'Digest sent to your webhook.'
          : 'Digest recorded, but nothing was sent — no webhook is configured.',
      )
      load()
    } catch (e) {
      notify(e instanceof ApiError ? e.message : 'Could not send digest')
    }
  }

  if (authLoading) return <LoadingState message="Loading…" />
  if (!user) return null
  if (error) return <ErrorState message={error} onRetry={load} />

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <PageHeader
          title="Notifications"
          subtitle={
            loading ? 'Loading…'
              : unread > 0 ? `${unread} unread` : 'Everything here has been read'
          }
        />
        <div className="flex gap-2">
          <button onClick={showPreview} className="px-3 py-2 text-sm border border-line rounded-lg hover:bg-surface-sunken">
            Preview digest
          </button>
          <button onClick={sendNow} className="px-3 py-2 text-sm border border-line rounded-lg hover:bg-surface-sunken">
            Send digest now
          </button>
          {unread > 0 && (
            <button onClick={markAll} className="btn-primary">Mark all read</button>
          )}
        </div>
      </div>

      {!hasWebhook && (
        <div className="rounded-xl border border-warn/20 bg-warn-tint p-3 text-sm text-warn">
          <span className="font-medium">No alert channel is set up.</span>{' '}
          The app still records everything it notices here, but nobody is told
          when something breaks. Add a Slack or Discord webhook URL as{' '}
          <code className="text-xs bg-warn-tint px-1 rounded">ALERT_WEBHOOK_URL</code>{' '}
          and restart to change that. It takes about five minutes and is free.
        </div>
      )}

      {toast && (
        <Notice tone="ok">{toast}</Notice>
      )}

      {preview && (
        <div className="card">
          <div className="flex items-start justify-between">
            <h2 className="font-semibold text-ink">What the next digest will say</h2>
            <button onClick={() => setPreview(null)} className="text-ink-subtle hover:text-ink-muted">×</button>
          </div>
          <p className="font-medium text-ink mt-2">{preview.subject}</p>
          <pre className="text-sm text-ink mt-1 whitespace-pre-wrap font-sans">{preview.body}</pre>
        </div>
      )}

      {loading && items.length === 0 ? (
        <div className="card text-center py-12 text-ink-subtle">Loading…</div>
      ) : items.length === 0 ? (
        <div className="card text-center py-14">
          <p className="text-ink-muted mb-1">Nothing yet</p>
          <p className="text-sm text-ink-subtle max-w-md mx-auto">
            Sync failures and the daily digest appear here. The digest runs once
            a day — use &quot;Send digest now&quot; to see one immediately.
          </p>
        </div>
      ) : (
        <div className="card p-0 divide-y divide-hairline">
          {items.map(n => (
            <button
              key={n.id}
              onClick={() => markOne(n)}
              className={`w-full text-left px-4 py-3 hover:bg-surface-sunken transition-colors ${
                n.read_at ? '' : 'bg-accent-weak/40'
              }`}
            >
              <div className="flex items-center gap-2 flex-wrap">
                {!n.read_at && <span className="w-1.5 h-1.5 rounded-full bg-accent-weak0 shrink-0" />}
                <span className="text-xs text-ink-muted">
                  {EVENT_LABEL[n.event_type] ?? n.event_type}
                </span>
                <span className={`text-xs px-2 py-0.5 rounded font-medium ${STATUS_STYLE[n.delivery_status] ?? 'bg-surface-sunken text-ink-muted'}`}>
                  {STATUS_LABEL[n.delivery_status] ?? n.delivery_status}
                </span>
                <span className="text-xs text-ink-subtle ml-auto">
                  {new Date(n.sent_at).toLocaleString('en-US', {
                    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
                  })}
                </span>
              </div>
              {n.subject && (
                <p className={`text-sm mt-1 ${n.read_at ? 'text-ink' : 'font-medium text-ink'}`}>
                  {n.subject}
                </p>
              )}
              {n.body && (
                <pre className="text-xs text-ink-muted mt-1 whitespace-pre-wrap font-sans">{n.body}</pre>
              )}
              {n.error_message && (
                <p className="text-xs text-danger mt-1">{n.error_message}</p>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
