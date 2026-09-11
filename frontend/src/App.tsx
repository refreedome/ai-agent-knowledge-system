import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import './App.css'

/**
 * 一轮模型输出。ReAct 会多轮：前几轮是「思考 + 调工具」，最后一轮才是答案。
 * 后端通过 {"type":"tool","turn":N} 事件告诉我们第 N 轮其实在思考，于是把它归入折叠区。
 */
type Turn = { text: string; thinking: boolean }
type Msg = {
  role: 'user' | 'assistant'
  content: string
  at?: number
  turns?: Turn[]
  tools?: string[]
}
type SessionInfo = { session_id: string; user_id?: string; message_count: number; last_active?: string }
type UserInfo = {
  user_id: string
  display_name: string
  role: string
  permissions: string[]
  session_count?: number
}

const SUGGESTIONS = [
  { icon: '🏠', text: '小户型适合哪些扫地机器人？' },
  { icon: '🔋', text: '扫地机器人电池续航一般多久？' },
  { icon: '🚪', text: '机器人卡在门槛上不去怎么办？' },
  { icon: '🧹', text: '滚刷上的毛发怎么清理？' },
]

const K_SESSION = 'kb_session_id'
const K_USER = 'kb_user'

function App() {
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [user, setUser] = useState(() => localStorage.getItem(K_USER) || 'guest')
  const [users, setUsers] = useState<UserInfo[]>([])
  const [sessionId, setSessionId] = useState<string | null>(() => localStorage.getItem(K_SESSION))
  const [streaming, setStreaming] = useState(false)
  const [sessions, setSessions] = useState<SessionInfo[]>([])
  const [upload, setUpload] = useState<{ kind: 'idle' | 'busy' | 'ok' | 'err'; text: string }>({ kind: 'idle', text: '' })
  const [dragOver, setDragOver] = useState(false)
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null)
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    refreshSessions(user)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user])

  useEffect(() => {
    fetchUsers()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, streaming])

  const stats = useMemo(() => {
    const rounds = Math.floor(messages.length / 2)
    return { rounds, sessions: sessions.length }
  }, [messages, sessions])

  // 当前用户与权限（admin 才能上传文档）
  const currentUser = users.find(u => u.user_id === user)
  const role = currentUser?.role ?? 'user'
  const canUpload = role === 'admin'

  async function fetchUsers() {
    try {
      const res = await fetch('/api/users', { headers: { 'X-User-Id': user } })
      const data = await res.json()
      setUsers(data.users ?? [])
    } catch {
      /* 后端未启动时静默 */
    }
  }

  async function refreshSessions(u: string) {
    try {
      const res = await fetch(`/api/sessions?user_id=${encodeURIComponent(u)}`, {
        headers: { 'X-User-Id': u },
      })
      const data = await res.json()
      setSessions(data.sessions ?? [])
    } catch {
      /* 后端未启动时静默 */
    }
  }

  async function loadHistory(sid: string) {
    setMessages([])
    try {
      const res = await fetch(`/api/sessions/${sid}/messages`, { headers: { 'X-User-Id': user } })
      const data = await res.json()
      const msgs: Msg[] = (data.messages ?? [])
        .filter((m: { role: string }) => m.role === 'user' || m.role === 'assistant')
        .map((m: { role: 'user' | 'assistant'; content: string; timestamp?: string }) => ({
          role: m.role,
          content: m.content,
          at: m.timestamp ? Date.parse(m.timestamp) : undefined,
        }))
      setMessages(msgs)
    } catch {
      /* 忽略 */
    }
  }

  function switchSession(sid: string) {
    if (sid === sessionId) return
    setSessionId(sid)
    localStorage.setItem(K_SESSION, sid)
    loadHistory(sid)
  }

  function newSession() {
    localStorage.removeItem(K_SESSION)
    setSessionId(null)
    setMessages([])
  }

  function switchUser(uid: string) {
    if (uid === user) return
    localStorage.setItem(K_USER, uid)
    setUser(uid)
    newSession()
  }

  function guardUpload(f: File) {
    if (!canUpload) {
      setUpload({ kind: 'err', text: `当前用户（${role === 'admin' ? '管理员' : '普通用户'}）无上传权限，请切换到管理员` })
      setTimeout(() => setUpload({ kind: 'idle', text: '' }), 4000)
      return
    }
    uploadFile(f)
  }

  async function send(text?: string) {
    const q = (text ?? input).trim()
    if (!q || streaming) return
    setInput('')
    setStreaming(true)

    const sid = sessionId ?? crypto.randomUUID().slice(0, 8)
    if (!sessionId) {
      setSessionId(sid)
      localStorage.setItem(K_SESSION, sid)
    }

    setMessages(prev => [
      ...prev,
      { role: 'user', content: q, at: Date.now() },
      { role: 'assistant', content: '', turns: [], tools: [], at: Date.now() },
    ])

    type StreamEvent = { type: string; content?: string; turn?: number; name?: string }
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-User-Id': user },
        body: JSON.stringify({ query: q, session_id: sid, user_id: user }),
      })
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          let data: StreamEvent
          try {
            data = JSON.parse(line.slice(6))
          } catch {
            continue
          }
          if (data.type === 'token' && data.content) {
            const idx = data.turn ?? 0
            setMessages(prev => {
              const next = [...prev]
              const last = next[next.length - 1]
              const turns = [...(last.turns ?? [])]
              while (turns.length <= idx) turns.push({ text: '', thinking: false })
              turns[idx] = { ...turns[idx], text: turns[idx].text + data.content }
              next[next.length - 1] = { ...last, turns }
              return next
            })
          } else if (data.type === 'tool') {
            // 第 idx 轮调用了工具 → 这一轮的文本是「思考」，移到折叠区
            const idx = data.turn ?? 0
            setMessages(prev => {
              const next = [...prev]
              const last = next[next.length - 1]
              const turns = [...(last.turns ?? [])]
              while (turns.length <= idx) turns.push({ text: '', thinking: false })
              turns[idx] = { ...turns[idx], thinking: true }
              next[next.length - 1] = {
                ...last,
                turns,
                tools: [...(last.tools ?? []), data.name ?? 'tool'],
              }
              return next
            })
          }
        }
      }
    } catch (e) {
      setMessages(prev => {
        const next = [...prev]
        next[next.length - 1] = {
          role: 'assistant',
          content: `请求失败：${e instanceof Error ? e.message : String(e)}`,
          at: Date.now(),
        }
        return next
      })
    } finally {
      setStreaming(false)
      refreshSessions(user)
    }
  }

  function regenerate(idx: number) {
    // 找到这条回答对应的用户问题，重新提问
    for (let i = idx; i >= 0; i--) {
      if (messages[i].role === 'user') {
        send(messages[i].content)
        return
      }
    }
  }

  async function copyMessage(content: string, idx: number) {
    try {
      await navigator.clipboard.writeText(content)
      setCopiedIdx(idx)
      setTimeout(() => setCopiedIdx(null), 1500)
    } catch {
      /* 忽略 */
    }
  }

  async function uploadFile(f: File) {
    setUpload({ kind: 'busy', text: `正在上传并解析 ${f.name} …` })
    const fd = new FormData()
    fd.append('file', f)
    try {
      const res = await fetch('/api/upload/file', {
        method: 'POST',
        headers: { 'X-User-Id': user },
        body: fd,
      })
      const data = await res.json()
      if (data.success) {
        setUpload({ kind: 'ok', text: `已入库 ${data.filename}（${data.chunks} 个分块）` })
      } else {
        setUpload({ kind: 'err', text: data.error ?? '上传失败' })
      }
    } catch (e) {
      setUpload({ kind: 'err', text: `上传失败：${e instanceof Error ? e.message : e}` })
    }
    setTimeout(() => setUpload({ kind: 'idle', text: '' }), 6000)
  }

  const initial = (user || 'G').trim().charAt(0).toUpperCase()

  return (
    <div className="stage">
      <div
        className={`console ${dragOver ? 'dragging' : ''}`}
        onDragOver={e => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={e => {
          e.preventDefault()
          setDragOver(false)
          const f = e.dataTransfer.files?.[0]
          if (f) guardUpload(f)
        }}
      >
        {/* ───── 侧栏 ───── */}
        <aside className="rail">
          <div className="mark">
            <span className="mark-glyph">智</span>
            <div className="mark-words">
              <span className="mark-name">智扫通</span>
              <span className="mark-sub">Knowledge Console</span>
            </div>
          </div>

          <button className="btn-new" onClick={newSession}>
            <span>＋</span> 开启新对话
          </button>

          <div className="user-box">
            <label>切换用户（会话与权限隔离）</label>
            <div className="user-list">
              {users.length === 0 && <div className="user-empty">加载用户中…</div>}
              {users.map(u => (
                <button
                  key={u.user_id}
                  className={`user-chip ${u.user_id === user ? 'on' : ''}`}
                  onClick={() => switchUser(u.user_id)}
                  title={`权限：${u.permissions.join('、') || 'chat'}`}
                >
                  <span className="user-chip-avatar">{u.display_name.charAt(0)}</span>
                  <span className="user-chip-name">{u.display_name}</span>
                  {u.role === 'admin' && <span className="user-chip-role">管理员</span>}
                </button>
              ))}
            </div>
            <div className="user-hint">
              当前角色：<b>{role === 'admin' ? '管理员（可上传文档）' : '普通用户（仅对话）'}</b>
            </div>
          </div>

          <div className="rail-title">
            我的会话 <span>{stats.sessions}</span>
          </div>
          <div className="rail-list">
            {sessions.length === 0 && <div className="rail-empty">该用户暂无会话</div>}
            {sessions.map(s => (
              <button
                key={s.session_id}
                className={`rail-item ${s.session_id === sessionId ? 'on' : ''}`}
                onClick={() => switchSession(s.session_id)}
              >
                <span className="rail-item-name">#{s.session_id}</span>
                <span className="rail-item-meta">{s.message_count} 条</span>
              </button>
            ))}
          </div>

          <div className="rail-foot">
            <div>LangGraph ReAct</div>
            <div>BM25 · 向量 · RRF</div>
          </div>
        </aside>

        {/* ───── 主区 ───── */}
        <main className="panel">
          <header className="panel-head">
            <div>
              <h1>智能知识库客服</h1>
              <p>产品选购 · 故障排查 · 维护保养</p>
            </div>
            <div className="panel-stats">
              <div className="stat">
                <b>{stats.rounds}</b>
                <span>本次轮次</span>
              </div>
              <div className={`live ${streaming ? 'busy' : ''}`}>
                <i />
                {streaming ? '推理中' : '就绪'}
              </div>
            </div>
          </header>

          <div className="stream" ref={listRef}>
            {messages.length === 0 && (
              <section className="hero">
                <div className="hero-kicker">RAG · AGENT · FASTAPI</div>
                <h2>
                  有问题，
                  <em>直接问</em>
                  知识库
                </h2>
                <p>答案来自产品文档检索 + 大模型推理，每一步都可追溯</p>
                <div className="hero-grid">
                  {SUGGESTIONS.map(s => (
                    <button key={s.text} className="hero-card" onClick={() => send(s.text)} disabled={streaming}>
                      <span className="hero-card-icon">{s.icon}</span>
                      <span>{s.text}</span>
                    </button>
                  ))}
                </div>
              </section>
            )}

            {messages.map((m, i) => {
              const turns = m.turns ?? []
              const thinking = turns.filter(t => t.thinking).map(t => t.text).join('').trim()
              const answer = (turns.filter(t => !t.thinking).map(t => t.text).join('') || m.content || '').trim()
              const live = streaming && i === messages.length - 1
              return (
                <article key={i} className={`turn ${m.role}`}>
                  <div className="turn-avatar">{m.role === 'user' ? initial : '智'}</div>
                  <div className="turn-body">
                    <div className="turn-bubble">
                      {m.role === 'user' ? (
                        m.content
                      ) : (
                        <>
                          {thinking && (
                            <details className="thinkbox" open={live}>
                              <summary>
                                <span className="think-label">深度思考</span>
                                {(m.tools ?? []).length > 0 && (
                                  <span className="think-tools">
                                    {(m.tools ?? []).map(t => `已调用 ${t}`).join(' · ')}
                                  </span>
                                )}
                              </summary>
                              <div className="think-text">{thinking}</div>
                            </details>
                          )}
                          <div className="answer">
                            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
                              {answer + (live && answer ? '<span class="stream-caret"></span>' : '')}
                            </ReactMarkdown>
                            {live && !answer && <span className="stream-caret" />}
                          </div>
                        </>
                      )}
                    </div>
                    <div className="turn-tools">
                      <span className="turn-time">
                        {m.at ? new Date(m.at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : ''}
                      </span>
                      {m.role === 'assistant' && answer && !live && (
                        <>
                          <button onClick={() => copyMessage(answer, i)}>
                            {copiedIdx === i ? '已复制' : '复制'}
                          </button>
                          <button onClick={() => regenerate(i)}>重新生成</button>
                        </>
                      )}
                    </div>
                  </div>
                </article>
              )
            })}
          </div>

          <footer className="composer">
            {upload.kind !== 'idle' && <div className={`tip ${upload.kind}`}>{upload.text}</div>}
            {dragOver && (
              <div className="tip drop">
                {canUpload ? '松开鼠标，上传文档到知识库' : '当前用户无上传权限（需切换到管理员）'}
              </div>
            )}
            <div className="composer-row">
              <label
                className={`attach ${canUpload ? '' : 'locked'}`}
                title={canUpload ? '上传文档（txt / pdf / docx / csv / 图片）' : '当前用户无上传权限（需管理员）'}
              >
                <span>{canUpload ? '＋' : '🔒'}</span>
                <input
                  type="file"
                  hidden
                  accept=".txt,.pdf,.docx,.csv,.jpg,.jpeg,.png"
                  onChange={e => {
                    const f = e.target.files?.[0]
                    if (f) guardUpload(f)
                    e.target.value = ''
                  }}
                />
              </label>
              <textarea
                rows={1}
                value={input}
                disabled={streaming}
                placeholder="输入问题，Enter 发送，Shift + Enter 换行"
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    send()
                  }
                }}
              />
              <button className="submit" onClick={() => send()} disabled={streaming || !input.trim()}>
                {streaming ? '···' : '发送'}
              </button>
            </div>
            <div className="composer-note">回答由 AI 基于知识库生成 · 关键指标可在 /api/metrics 查看</div>
          </footer>
        </main>
      </div>
    </div>
  )
}

export default App
