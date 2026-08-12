'use client'
/**
 * Users — admin only.
 *
 * Before this screen existed the only way to add a teammate was running the
 * seed script or writing an INSERT, so in practice the whole team shared
 * admin@example.com and every audit row said "Admin User" regardless of who
 * actually approved the change.
 *
 * There is no email delivery in this app, so an admin sets the initial
 * password and hands it over directly.
 */
import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/context/AuthContext'
import { api, ApiError } from '@/lib/api'
import type { ManagedUser } from '@/lib/types'
import { PageHeader } from '@/components/layout/PageHeader'
import { LoadingState } from '@/components/ui/LoadingState'
import { ErrorState } from '@/components/ui/ErrorState'

const MIN_PASSWORD = 12

function fmtDate(s: string) {
  return new Date(s).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function UsersPage() {
  const { user, loading: authLoading } = useAuth()
  const router = useRouter()

  const [users, setUsers]     = useState<ManagedUser[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState<string | null>(null)
  const [toast, setToast]     = useState<string | null>(null)
  const [toastErr, setToastErr] = useState<string | null>(null)

  const [showCreate, setShowCreate] = useState(false)
  const [pwFor, setPwFor] = useState<ManagedUser | null>(null)

  useEffect(() => {
    if (!authLoading && !user) router.push('/login')
  }, [authLoading, user, router])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setUsers(await api.listUsers())
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load users')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { if (user?.role === 'admin') load() }, [user, load])

  function notify(msg: string, isErr = false) {
    if (isErr) { setToastErr(msg); setTimeout(() => setToastErr(null), 5000) }
    else       { setToast(msg);    setTimeout(() => setToast(null), 5000) }
  }

  async function patch(u: ManagedUser, body: { role?: string; is_active?: boolean }, label: string) {
    try {
      const updated = await api.updateUser(u.id, body)
      setUsers(list => list.map(x => (x.id === updated.id ? updated : x)))
      notify(`${u.email}: ${label}`)
    } catch (e) {
      // The API refuses self-lockout and last-admin removal; surface its
      // reason rather than a generic failure, because the reason is the
      // useful part.
      notify(e instanceof ApiError ? e.message : `Could not update ${u.email}`, true)
    }
  }

  if (authLoading) return <LoadingState message="Loading…" />
  if (!user) return null

  if (user.role !== 'admin') {
    return (
      <div>
        <PageHeader title="Users" subtitle="Admin only" />
        <div className="card text-center py-12 text-gray-500">
          Only admins can manage users. Ask an admin if you need an account changed.
        </div>
      </div>
    )
  }

  if (error) return <ErrorState message={error} onRetry={load} />

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <PageHeader
          title="Users"
          subtitle={loading ? 'Loading…' : `${users.length} account${users.length !== 1 ? 's' : ''}`}
        />
        <button className="btn-primary" onClick={() => setShowCreate(true)}>+ Add User</button>
      </div>

      {toast && (
        <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-2 text-sm text-green-700">✓ {toast}</div>
      )}
      {toastErr && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-2 text-sm text-red-700">✗ {toastErr}</div>
      )}

      <div className="card p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50">
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600">Name</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600">Email</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 w-28">Role</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 w-24">Status</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 w-32">Added</th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-gray-600 w-64">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr><td colSpan={6} className="px-4 py-12 text-center text-gray-400">Loading…</td></tr>
            ) : users.map(u => {
              const isSelf = u.id === user.id
              return (
                <tr key={u.id} className={u.is_active ? 'hover:bg-gray-50' : 'bg-gray-50/60 text-gray-400'}>
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {u.name}
                    {isSelf && <span className="ml-2 text-xs text-gray-400">(you)</span>}
                  </td>
                  <td className="px-4 py-3 text-gray-600">{u.email}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                      u.role === 'admin' ? 'bg-purple-100 text-purple-700' : 'bg-gray-100 text-gray-600'
                    }`}>{u.role}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                      u.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-200 text-gray-600'
                    }`}>{u.is_active ? 'active' : 'disabled'}</span>
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{fmtDate(u.created_at)}</td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2 justify-end flex-wrap">
                      <button
                        onClick={() => setPwFor(u)}
                        className="text-xs px-2.5 py-1 bg-white border border-gray-300 rounded hover:bg-gray-50"
                      >
                        Set password
                      </button>
                      <button
                        onClick={() => patch(u, { role: u.role === 'admin' ? 'user' : 'admin' },
                                             u.role === 'admin' ? 'now a standard user' : 'now an admin')}
                        disabled={isSelf}
                        title={isSelf ? 'You cannot change your own role' : undefined}
                        className="text-xs px-2.5 py-1 bg-white border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        {u.role === 'admin' ? 'Make user' : 'Make admin'}
                      </button>
                      <button
                        onClick={() => patch(u, { is_active: !u.is_active },
                                             u.is_active ? 'disabled' : 're-enabled')}
                        disabled={isSelf}
                        title={isSelf ? 'You cannot disable your own account' : undefined}
                        className={`text-xs px-2.5 py-1 rounded border disabled:opacity-40 disabled:cursor-not-allowed ${
                          u.is_active
                            ? 'bg-white border-red-200 text-red-600 hover:bg-red-50'
                            : 'bg-white border-green-200 text-green-700 hover:bg-green-50'
                        }`}
                      >
                        {u.is_active ? 'Disable' : 'Enable'}
                      </button>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-gray-400">
        Disabling an account blocks sign-in immediately but keeps that person&apos;s
        name on everything they approved. Accounts are never deleted, so the audit
        trail stays readable.
      </p>

      {showCreate && (
        <CreateUserModal
          onClose={() => setShowCreate(false)}
          onCreated={u => { setUsers(list => [...list, u]); setShowCreate(false); notify(`${u.email} created`) }}
        />
      )}
      {pwFor && (
        <PasswordModal
          user={pwFor}
          onClose={() => setPwFor(null)}
          onDone={() => { notify(`Password updated for ${pwFor.email}`); setPwFor(null) }}
        />
      )}
    </div>
  )
}

// ── Modals ────────────────────────────────────────────────────────────────

function CreateUserModal({
  onClose, onCreated,
}: { onClose: () => void; onCreated: (u: ManagedUser) => void }) {
  const [email, setEmail]       = useState('')
  const [name, setName]         = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole]         = useState('user')
  const [saving, setSaving]     = useState(false)
  const [error, setError]       = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true); setError(null)
    try {
      onCreated(await api.createUser({ email, name, password, role }))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create user')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="font-semibold text-gray-900">Add User</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>
        <form onSubmit={submit} className="px-6 py-5 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Name <span className="text-red-500">*</span></label>
            <input className="input w-full" value={name} onChange={e => setName(e.target.value)} required />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Email <span className="text-red-500">*</span></label>
            <input type="email" className="input w-full" value={email} onChange={e => setEmail(e.target.value)} required />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Initial password <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              className="input w-full font-mono"
              value={password}
              onChange={e => setPassword(e.target.value)}
              minLength={MIN_PASSWORD}
              required
            />
            <p className="text-xs text-gray-400 mt-1">
              At least {MIN_PASSWORD} characters. Shown in plain text because you have to
              pass it to them — this app cannot send email. Ask them to change it after
              first sign-in.
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
            <select className="input w-full" value={role} onChange={e => setRole(e.target.value)}>
              <option value="user">User — approve and apply suggestions</option>
              <option value="admin">Admin — also manages accounts and users</option>
            </select>
          </div>
          {error && <div className="bg-red-50 border border-red-200 rounded px-3 py-2 text-sm text-red-700">{error}</div>}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50">Cancel</button>
            <button type="submit" disabled={saving} className="btn-primary disabled:opacity-50">
              {saving ? 'Creating…' : 'Create User'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function PasswordModal({
  user, onClose, onDone,
}: { user: ManagedUser; onClose: () => void; onDone: () => void }) {
  const [password, setPassword] = useState('')
  const [saving, setSaving]     = useState(false)
  const [error, setError]       = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true); setError(null)
    try {
      await api.resetUserPassword(user.id, password)
      onDone()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not set password')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="font-semibold text-gray-900">Set password</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>
        <form onSubmit={submit} className="px-6 py-5 space-y-4">
          <p className="text-sm text-gray-600">
            New password for <span className="font-medium text-gray-900">{user.email}</span>.
            Their existing sessions stay valid until the token expires.
          </p>
          <input
            type="text"
            className="input w-full font-mono"
            value={password}
            onChange={e => setPassword(e.target.value)}
            minLength={MIN_PASSWORD}
            placeholder={`At least ${MIN_PASSWORD} characters`}
            required
            autoFocus
          />
          {error && <div className="bg-red-50 border border-red-200 rounded px-3 py-2 text-sm text-red-700">{error}</div>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50">Cancel</button>
            <button type="submit" disabled={saving} className="btn-primary disabled:opacity-50">
              {saving ? 'Saving…' : 'Set password'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
