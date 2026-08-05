/**
 * Long-running sync proxy route handler.
 *
 * WHY http.request() INSTEAD OF fetch()
 * --------------------------------------
 * Node.js 18's built-in fetch() is backed by undici, which enforces a
 * headersTimeout of 30 s by default. When the Amazon targets sync takes
 * several minutes (e.g. CA profile with 9 000+ keywords), undici fires the
 * timeout and throws "fetch failed" — even though our AbortController is set
 * to 10 minutes and the backend eventually succeeds.
 *
 * Node.js http.request() has NO built-in timeout. We attach our own manual
 * timeout via req.setTimeout() so runaway requests still get cleaned up.
 *
 * WHY A SINGLE ROUTE HANDLER (not three browser fetches)
 * -------------------------------------------------------
 * The frontend now calls /api/proxy-sync/accounts/{id}/sync-all once.
 * http.request() runs entirely in Node.js (server side) — it continues even
 * if the browser tab is closed or the user navigates away. The DB write
 * completes; the user sees updated timestamps on next page load.
 *
 * Usage (api.ts syncRequest helper):
 *   POST /api/proxy-sync/accounts/{id}/campaigns/sync    (kept for direct use)
 *   POST /api/proxy-sync/accounts/{id}/ad-groups/sync   (kept for direct use)
 *   POST /api/proxy-sync/accounts/{id}/targets/sync     (kept for direct use)
 *   POST /api/proxy-sync/accounts/{id}/sync-all         ← main entry point
 *
 * The backend URL is taken from the server-side API_URL env var
 * (http://api:8000 inside Docker; falls back to http://localhost:8000).
 */
import { NextRequest, NextResponse } from 'next/server'
import http from 'node:http'
import https from 'node:https'

const BACKEND = process.env.API_URL ?? 'http://localhost:8000'
const TIMEOUT_MS = 1_200_000 // 20-minute safety net (US accounts can have 50k+ keywords)

/** POST via Node.js http.request() — no undici headersTimeout. */
function nodePost(
  url: string,
  headers: Record<string, string>,
): Promise<{ status: number; body: string }> {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url)
    const isHttps = parsed.protocol === 'https:'
    const lib = isHttps ? https : http
    const options: http.RequestOptions = {
      hostname: parsed.hostname,
      port: parsed.port ? parseInt(parsed.port, 10) : isHttps ? 443 : 80,
      path: parsed.pathname + parsed.search,
      method: 'POST',
      headers,
    }

    const req = lib.request(options, (res) => {
      const chunks: Buffer[] = []
      res.on('data', (chunk: Buffer) => chunks.push(chunk))
      res.on('end', () =>
        resolve({ status: res.statusCode ?? 500, body: Buffer.concat(chunks).toString('utf8') }),
      )
      res.on('error', reject)
    })

    req.on('error', reject)

    // Manual timeout — destroys the socket if the backend never responds.
    req.setTimeout(TIMEOUT_MS, () => {
      req.destroy(new Error(`sync proxy timeout after ${TIMEOUT_MS / 1000}s`))
    })

    req.end() // POST with no body (all params are in the URL path)
  })
}

export async function POST(
  req: NextRequest,
  { params }: { params: { path: string[] } },
) {
  const path = (params.path ?? []).join('/')
  const url = `${BACKEND}/${path}`

  const auth = req.headers.get('authorization')
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (auth) headers['Authorization'] = auth

  try {
    const upstream = await nodePost(url, headers)
    const data = JSON.parse(upstream.body)
    return NextResponse.json(data, { status: upstream.status })
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'proxy error'
    return NextResponse.json({ detail: `Sync proxy error: ${msg}` }, { status: 500 })
  }
}
