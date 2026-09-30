"""Web 服务器：REST API + 完整前端页面（零依赖，标准库 http.server）。

前端包含三个视图（单页切换）：
  * 仪表盘：海报卡片式展示订阅与进度
  * 订阅管理：添加/删除订阅
  * 设置：TG/TMDB/Emby 配置 + 通知模板编辑

API 路由：
  GET    /                  → 前端页面
  GET    /healthz           → 健康检查
  GET    /api/dashboard     → 仪表盘数据
  GET    /api/subscriptions → 订阅列表
  POST   /api/subscriptions → 添加订阅
  DELETE /api/subscriptions → 删除订阅（?id= 或 body {"id"})
  GET    /api/templates     → 通知模板
  POST   /api/templates     → 保存通知模板
  GET    /api/config        → 配置（脱敏）
  POST   /api/config        → 保存配置
  POST   /api/check         → 手动触发入库比对
  GET    /api/poster        → 代理 TMDB 海报（?id=tmdb_id）
"""

from __future__ import annotations

import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import httpx

from .config import Config
from .hub import Hub
from .log import log
from .templates import save_templates


HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RSS-TV 追更中心</title>
<style>
  :root { --bg:#0f1117; --card:#1a1d27; --text:#e6e8ee; --muted:#8b90a0; --accent:#7c5cff; --ok:#3ddc84; --warn:#ffb02e; --border:#2a2f40; }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif; background:var(--bg); color:var(--text); min-height:100vh; }
  nav { display:flex; gap:4px; padding:16px 24px 0; }
  nav button { background:transparent; border:none; color:var(--muted); padding:8px 16px; font-size:14px; cursor:pointer; border-radius:8px 8px 0 0; }
  nav button.active { color:var(--text); background:var(--card); font-weight:600; }
  main { padding:24px; }
  .view { display:none; }
  .view.active { display:block; }
  header { display:flex; align-items:baseline; gap:16px; margin-bottom:8px; flex-wrap:wrap; }
  h1 { font-size:22px; font-weight:700; }
  h2 { font-size:18px; font-weight:600; margin-bottom:16px; }
  .sub { color:var(--muted); font-size:13px; }
  .stats { display:flex; gap:12px; margin:20px 0; flex-wrap:wrap; }
  .stat { background:var(--card); border-radius:12px; padding:16px 20px; min-width:120px; }
  .stat .n { font-size:26px; font-weight:700; }
  .stat .l { color:var(--muted); font-size:12px; margin-top:4px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:16px; }
  .card { background:var(--card); border-radius:14px; overflow:hidden; position:relative; transition:transform .15s; }
  .card:hover { transform:translateY(-3px); }
  .poster { width:100%; aspect-ratio:2/3; background:#242838; display:flex; align-items:center; justify-content:center; color:var(--muted); font-size:30px; overflow:hidden; position:relative; }
  .poster img { width:100%; height:100%; object-fit:cover; }
  .info { padding:12px; }
  .name { font-size:13px; font-weight:600; line-height:1.4; height:36px; overflow:hidden; }
  .meta { color:var(--muted); font-size:11px; margin:6px 0; }
  .bar { height:6px; background:#2a2f40; border-radius:3px; overflow:hidden; margin:8px 0 4px; }
  .bar > div { height:100%; background:linear-gradient(90deg,var(--accent),var(--ok)); border-radius:3px; transition:width .4s; }
  .pct { font-size:11px; color:var(--muted); }
  .badge { position:absolute; top:8px; right:8px; font-size:10px; padding:3px 7px; border-radius:10px; background:rgba(0,0,0,.6); }
  .badge.rss { color:var(--warn); }
  .badge.done { color:var(--ok); }
  .del-btn { position:absolute; bottom:8px; right:8px; background:rgba(0,0,0,.5); color:#ff6b6b; border:none; border-radius:6px; padding:2px 8px; font-size:11px; cursor:pointer; opacity:0; transition:opacity .15s; }
  .card:hover .del-btn { opacity:1; }
  .empty { color:var(--muted); text-align:center; padding:60px 0; }
  /* 表单 */
  form { display:flex; flex-direction:column; gap:12px; max-width:560px; }
  .field { display:flex; flex-direction:column; gap:6px; }
  .field label { font-size:13px; color:var(--muted); }
  .field input, .field select, .field textarea { background:var(--card); border:1px solid var(--border); color:var(--text); border-radius:8px; padding:10px 12px; font-size:14px; }
  .field textarea { min-height:120px; font-family:monospace; resize:vertical; }
  .field input:focus, .field textarea:focus { outline:none; border-color:var(--accent); }
  .row { display:flex; gap:12px; }
  .row .field { flex:1; }
  button.primary { background:var(--accent); color:#fff; border:none; border-radius:8px; padding:10px 20px; font-size:14px; cursor:pointer; }
  button.primary:hover { opacity:.9; }
  button.ghost { background:var(--card); color:var(--text); border:1px solid var(--border); border-radius:8px; padding:10px 20px; font-size:14px; cursor:pointer; }
  .section { background:var(--card); border-radius:14px; padding:20px; margin-bottom:20px; }
  .section h3 { font-size:15px; margin-bottom:16px; }
  .msg { font-size:13px; padding:8px 12px; border-radius:8px; margin-top:12px; display:none; }
  .msg.ok { background:rgba(61,220,132,.15); color:var(--ok); display:block; }
  .msg.err { background:rgba(255,107,107,.15); color:#ff6b6b; display:block; }
  .tpl-row { margin-bottom:16px; }
  .tpl-row label { display:block; font-size:13px; color:var(--muted); margin-bottom:6px; }
  .tpl-row textarea { width:100%; min-height:70px; background:var(--card); border:1px solid var(--border); color:var(--text); border-radius:8px; padding:10px; font-family:monospace; font-size:13px; }
</style>
</head>
<body>
<nav>
  <button class="active" data-view="dash">📡 仪表盘</button>
  <button data-view="subs">➕ 订阅管理</button>
  <button data-view="settings">⚙️ 设置</button>
</nav>
<main>
  <!-- 仪表盘 -->
  <div class="view active" id="view-dash">
    <header><h1>RSS-TV 追更中心</h1><span class="sub">电视剧 / 动画 订阅追更 · 只推送不接管下载器</span></header>
    <div class="stats">
      <div class="stat"><div class="n" id="s-total">0</div><div class="l">我的订阅</div></div>
      <div class="stat"><div class="n" id="s-catching">0</div><div class="l">追更中</div></div>
      <div class="stat"><div class="n" id="s-done">0</div><div class="l">已完结</div></div>
    </div>
    <div class="grid" id="grid"></div>
    <div class="empty" id="empty" style="display:none">暂无订阅，去「订阅管理」添加第一条吧</div>
  </div>

  <!-- 订阅管理 -->
  <div class="view" id="view-subs">
    <h2>添加订阅</h2>
    <form id="add-form">
      <div class="row">
        <div class="field"><label>名称（剧名，可用中文/英文/日文）</label><input name="name" required placeholder="无职转生"></div>
        <div class="field"><label>TMDB ID（可选，留空自动搜索）</label><input name="tmdb_id" type="number" placeholder="111110"></div>
      </div>
      <div class="field"><label>RSS 地址（带 passkey）</label><input name="rss" required placeholder="https://pt.example/rss?passkey=xxx"></div>
      <div class="row">
        <div class="field"><label>画质白名单（逗号分隔，留空=不限）</label><input name="quality" placeholder="1080p,2160p"></div>
        <div class="field"><label>排除正则</label><input name="exclude" placeholder="预告|花絮|OST"></div>
      </div>
      <div><button type="submit" class="primary">添加订阅</button></div>
      <div class="msg" id="add-msg"></div>
    </form>

    <h2 style="margin-top:28px">现有订阅</h2>
    <div id="sub-list" class="empty">加载中...</div>
  </div>

  <!-- 设置 -->
  <div class="view" id="view-settings">
    <h2>配置</h2>
    <div class="section">
      <h3>Telegram</h3>
      <form id="cfg-form"></form>
    </div>
    <div class="section">
      <h3>通知模板（Jinja2，对齐 MoviePilot）</h3>
      <div id="tpl-form"></div>
      <button class="primary" onclick="saveTemplates()">保存模板</button>
      <div class="msg" id="tpl-msg"></div>
    </div>
  </div>
</main>

<script>
let token = new URLSearchParams(location.search).get('token') || '';
function authSuffix(){ return token ? '&token='+token : ''; }

// ---- 视图切换 ----
document.querySelectorAll('nav button').forEach(b => {
  b.onclick = () => {
    document.querySelectorAll('nav button').forEach(x=>x.classList.remove('active'));
    document.querySelectorAll('.view').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');
    document.getElementById('view-'+b.dataset.view).classList.add('active');
    if (b.dataset.view==='dash') loadDash();
    if (b.dataset.view==='subs') loadSubs();
    if (b.dataset.view==='settings') loadSettings();
  };
});

// ---- 仪表盘 ----
async function loadDash(){
  const d = await (await fetch('/api/dashboard'+authSuffix())).json();
  document.getElementById('s-total').textContent = d.total;
  document.getElementById('s-catching').textContent = d.catching;
  document.getElementById('s-done').textContent = d.done;
  const grid = document.getElementById('grid');
  grid.innerHTML = '';
  if (!d.subscriptions.length){ document.getElementById('empty').style.display='block'; return; }
  document.getElementById('empty').style.display='none';
  for (const c of d.subscriptions){
    const el = document.createElement('div'); el.className='card';
    const posterHtml = c.poster ? `<img src="/api/poster?id=${encodeURIComponent(c.tmdb_id)}${authSuffix()}" onerror="this.parentNode.textContent='🎬'">` : '🎬';
    const done = c.total>0 && c.done>=c.total;
    el.innerHTML = `
      <div class="poster">${posterHtml}<span class="badge ${done?'done':'rss'}">${done?'✅ 完结':'📡 订阅'}</span></div>
      <button class="del-btn" onclick="delSub('${c.id}')">删除</button>
      <div class="info">
        <div class="name">${esc(c.name||c.id)}</div>
        <div class="meta">${c.mode==='show'?(c.total?c.done+'/'+c.total+' 集':'追更中'):'全量转发'}</div>
        <div class="bar"><div style="width:${c.pct}%"></div></div>
        <div class="pct">${c.pct}%</div>
      </div>`;
    grid.appendChild(el);
  }
}
function esc(s){return (s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

// ---- 订阅管理 ----
async function loadSubs(){
  const r = await fetch('/api/subscriptions'+authSuffix());
  const d = await r.json();
  const list = document.getElementById('sub-list');
  if (!d.subscriptions.length){ list.textContent='暂无订阅'; return; }
  list.innerHTML = '';
  for (const s of d.subscriptions){
    const div = document.createElement('div');
    div.style.cssText = 'display:flex;justify-content:space-between;align-items:center;background:var(--card);border-radius:8px;padding:12px 16px;margin-bottom:8px';
    div.innerHTML = `<div><div style="font-size:14px">${esc(s.name||s.id)}</div><div style="font-size:11px;color:var(--muted);margin-top:4px">${esc(s.rss||'')}</div></div>
      <button class="ghost" onclick="delSub('${s.id}')">删除</button>`;
    list.appendChild(div);
  }
}
async function delSub(id){
  if (!confirm('确认删除订阅 '+id+' ?')) return;
  await fetch('/api/subscriptions?id='+encodeURIComponent(id)+authSuffix(), {method:'DELETE'});
  loadDash(); loadSubs();
}
document.getElementById('add-form').onsubmit = async (e) => {
  e.preventDefault();
  const f = e.target;
  const body = {
    name: f.name.value, tmdb_id: f.tmdb_id.value?parseInt(f.tmdb_id.value):null,
    rss: f.rss.value, quality: f.quality.value?f.quality.value.split(',').map(s=>s.trim()).filter(Boolean):[],
    exclude_filter: f.exclude.value, mode: 'show', remove_when_done: true,
  };
  const r = await fetch('/api/subscriptions'+authSuffix(), {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const d = await r.json();
  const msg = document.getElementById('add-msg');
  msg.className = 'msg ' + (d.ok?'ok':'err');
  msg.textContent = d.ok ? '已添加订阅 '+d.id : (d.error||'添加失败');
  if (d.ok) f.reset();
};

// ---- 设置 ----
const CFG_LABELS = {telegram:'Telegram', tmdb:'TMDB', emby:'Emby/Jellyfin', app:'应用'};
async function loadSettings(){
  // 配置表单
  const cfg = await (await fetch('/api/config'+authSuffix())).json();
  const form = document.getElementById('cfg-form');
  form.innerHTML = '';
  for (const [section, fields] of Object.entries(cfg)){
    const sec = document.createElement('div'); sec.className='field';
    sec.innerHTML = `<label style="font-weight:600;color:var(--text)">${CFG_LABELS[section]||section}</label>`;
    for (const [k,v] of Object.entries(fields)){
      const f = document.createElement('div'); f.className='field';
      f.innerHTML = `<label>${esc(k)}</label><input name="${section}.${k}" value="${esc(String(v))}">`;
      sec.appendChild(f);
    }
    form.appendChild(sec);
  }
  form.innerHTML += '<div style="margin-top:12px"><button class="primary" onclick="saveConfig()">保存配置</button></div><div class="msg" id="cfg-msg"></div>';
  // 模板表单
  const tpl = await (await fetch('/api/templates'+authSuffix())).json();
  const tf = document.getElementById('tpl-form');
  tf.innerHTML = '';
  for (const [event, content] of Object.entries(tpl.templates||{})){
    const row = document.createElement('div'); row.className='tpl-row';
    row.innerHTML = `<label>${esc(event)}</label><textarea name="${esc(event)}">${esc(content)}</textarea>`;
    tf.appendChild(row);
  }
}
async function saveConfig(){
  const form = document.getElementById('cfg-form');
  const body = {};
  for (const input of form.querySelectorAll('input')){
    const [section, key] = input.name.split('.');
    if (!body[section]) body[section] = {};
    body[section][key] = input.value;
  }
  const r = await fetch('/api/config'+authSuffix(), {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const d = await r.json();
  const msg = document.getElementById('cfg-msg');
  msg.className = 'msg ' + (d.ok?'ok':'err');
  msg.textContent = d.ok ? '已保存（密钥需重启后完全生效）' : '保存失败';
}
async function saveTemplates(){
  const tf = document.getElementById('tpl-form');
  const templates = {};
  for (const ta of tf.querySelectorAll('textarea')) templates[ta.name] = ta.value;
  const r = await fetch('/api/templates'+authSuffix(), {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({templates})});
  const d = await r.json();
  const msg = document.getElementById('tpl-msg');
  msg.className = 'msg ' + (d.ok?'ok':'err');
  msg.textContent = d.ok ? '模板已保存' : '保存失败';
}

loadDash();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "RSS-TV/1.0"

    @property
    def ctx(self):
        return self.server.ctx  # type: ignore

    def _auth_ok(self) -> bool:
        token = self.ctx.config.app.web_token
        if not token:
            return True
        q = parse_qs(urlparse(self.path).query)
        return q.get("token", [""])[0] == token

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text, status=200, ctype="text/plain; charset=utf-8"):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return {}

    def _run(self, coro):
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)

    def do_GET(self):
        if not self._auth_ok():
            return self._send_json({"error": "unauthorized"}, 401)
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._send_text(HTML, ctype="text/html; charset=utf-8")
        if path == "/healthz":
            return self._send_json({"status": "ok"})
        if path == "/api/dashboard":
            return self._send_json(self._run(self.ctx.hub.dashboard_data()))
        if path == "/api/subscriptions":
            return self._send_json({"subscriptions": self.ctx.hub.db.list_subscriptions()})
        if path == "/api/templates":
            return self._send_json({"templates": self.ctx.hub._templates})
        if path == "/api/config":
            return self._send_json(self.ctx.config.as_dict(redact=True))
        if path == "/api/poster":
            q = parse_qs(urlparse(self.path).query)
            return self._run(self._serve_poster(q.get("id", [""])[0]))
        return self._send_json({"error": "not found"}, 404)

    async def _serve_poster(self, tmdb_id: str):
        try:
            raw = await self.ctx.hub.tmdb.resolve(None, tmdb_id=int(tmdb_id))
            path = raw.get("poster_path") or ""
            if not path:
                return self._send_json({"error": "no poster"}, 404)
            url = f"https://image.tmdb.org/t/p/w500{path}"
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.get(url)
            if r.status_code != 200:
                return self._send_json({"error": "poster fetch failed"}, 502)
            self.send_response(200)
            self.send_header("Content-Type", r.headers.get("content-type", "image/jpeg"))
            self.send_header("Content-Length", str(len(r.content)))
            self.end_headers()
            self.wfile.write(r.content)
        except Exception as e:
            log.warning("海报代理失败：%s", e)
            return self._send_json({"error": "poster fetch failed"}, 502)

    def do_POST(self):
        if not self._auth_ok():
            return self._send_json({"error": "unauthorized"}, 401)
        path = urlparse(self.path).path
        body = self._read_body()
        if path == "/api/subscriptions":
            return self._run(self._add_subscription(body))
        if path == "/api/templates":
            return self._run(self._save_templates(body))
        if path == "/api/config":
            return self._save_config(body)
        if path == "/api/check":
            return self._run(self._manual_check(body))
        return self._send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        if not self._auth_ok():
            return self._send_json({"error": "unauthorized"}, 401)
        path = urlparse(self.path).path
        if path == "/api/subscriptions":
            body = self._read_body()
            sub_id = body.get("id") or parse_qs(urlparse(self.path).query).get("id", [""])[0]
            self.ctx.hub.db.remove_subscription(sub_id)
            return self._send_json({"ok": True})
        return self._send_json({"error": "not found"}, 404)

    async def _add_subscription(self, body: dict):
        sub = dict(body)
        if not sub.get("id"):
            sub["id"] = sub.get("name") or f"sub-{len(self.ctx.hub.db.list_subscriptions()) + 1}"
        # 没填 tmdb_id 时按名称自动搜 TMDB 补
        if not sub.get("tmdb_id") and sub.get("name"):
            try:
                raw = await self.ctx.hub.tmdb.resolve(sub["name"])
                sub["tmdb_id"] = int(raw.get("id") or 0)
                sub["tmdb_name"] = raw.get("name") or sub["name"]
            except Exception:
                sub["mode"] = "feed"
        self.ctx.hub.db.add_subscription(sub)
        asyncio.create_task(self.ctx.hub.announce_subscribe(sub))
        return {"ok": True, "id": sub["id"]}

    async def _save_templates(self, body: dict):
        templates = body.get("templates") or {}
        self.ctx.hub._templates = dict(templates)
        save_templates(self.ctx.hub.templates_path, self.ctx.hub._templates)
        return {"ok": True}

    def _save_config(self, body: dict):
        cfg = self.ctx.config
        for section, fields in body.items():
            if section not in cfg.UI_EDITABLE:
                continue
            obj = {"telegram": cfg.tg, "tmdb": cfg.tmdb, "emby": cfg.emby, "app": cfg.app}[section]
            for k, v in fields.items():
                if k in cfg.SECRET_FIELDS and v in ("", "******", None):
                    continue
                if hasattr(obj, k):
                    # 布尔/整数类型转换
                    cur = getattr(obj, k)
                    if isinstance(cur, bool):
                        setattr(obj, k, str(v).lower() in ("true", "1", "yes", "on"))
                    elif isinstance(cur, int):
                        try:
                            setattr(obj, k, int(v))
                        except ValueError:
                            pass
                    else:
                        setattr(obj, k, v)
        return {"ok": True}

    async def _manual_check(self, body: dict):
        subs = self.ctx.hub.db.list_subscriptions()
        for sub in subs:
            if sub.get("mode") == "show" and sub.get("tmdb_id"):
                try:
                    await self.ctx.hub.check_and_push(sub)
                except Exception as e:
                    log.warning("手动比对失败 %s：%s", sub["id"], e)
        return {"ok": True}

    def log_message(self, format, *args):
        pass


class ServerContext:
    def __init__(self, config: Config, hub: Hub):
        self.config = config
        self.hub = hub


def start_server(config: Config, hub: Hub, host: str = "0.0.0.0", port: int = 18080) -> ThreadingHTTPServer:
    ctx = ServerContext(config, hub)
    server = ThreadingHTTPServer((host, port), Handler)
    server.ctx = ctx  # type: ignore
    return server
