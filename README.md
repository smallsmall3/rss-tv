# RSS-TV

> 全新项目：PT 站 RSS 订阅器 → 自动比对 Emby/Jellyfin → Telegram 推送入库进度 → 追完自动退订。**只推送，不接管下载器**，专注电视剧 / 动画。

一句话流程：

```
PT 站 RSS ──轮询──► 过滤电视/动画新种 ──► 解析标题（片名/季/集/年份）
                        │
                        ├─► TMDB 拿中文名/海报/总集数（分母）
                        ├─► Emby  拿已入库集数（分子）
                        ├─► Telegram 推送「入库 3/24（12%）｜待入库 S03E04」
                        └─► 分子=分母 → 推送完成 + 自动退订
```

## 特性

| 能力 | 说明 |
|---|---|
| 专注电视/动画 | 电影类标题自动过滤，只追电视剧和动画 |
| 标题识别 | 季号/集号/年份/绝对集/合集/片源标签全识别，含日番平台标签（CR/B-Global/Baha/AT-X） |
| TMDB 匹配 | 搜中文名 + 海报 + 各季总集数，支持反向/正向代理 |
| Emby 比对 | API 取真实已入库集数，不猜文件名 |
| Telegram 推送 | 海报图 + 文字（Jinja2 模板，对齐 MoviePilot 语法） |
| 追完退订 | 分子=分母 自动退订（可关） |
| Web UI | 三视图：海报卡片仪表盘 + 订阅管理 + 设置/模板编辑 |
| 多渠道抽象 | Message 统一结构 + Channel 接口，预留微信等扩展 |
| 停机恢复 | 重启后自动补推停机期间入库的集 |
| 不刷屏 | 首次启动只登记历史条目，不推几百条 |
| 零依赖运维 | 单容器、SQLite、/healthz 健康检查 |

## 快速开始

### 1. 准备三样

1. **Telegram 机器人**：[@BotFather](https://t.me/BotFather) `/newbot` 拿 Token；[@userinfobot](https://t.me/userinfobot) 拿 chat id。
2. **TMDB API Key**：<https://www.themoviedb.org/settings/api> 用 API Key (v3 auth)。
3. **Emby/Jellyfin API 密钥**：后台 → API 密钥。

### 2. 起容器

```bash
git clone <本项目> rss-tv && cd rss-tv
cp .env.example .env
vim .env           # 填 TG / TMDB / Emby 三组密钥
docker compose up -d --build
docker compose logs -f
```

### 3. 添加订阅

Web 仪表盘 `http://<NAS-IP>:18080` 的「订阅管理」，或命令行：

```bash
# 已知 TMDB ID（推荐）
python -m app add --name "无职转生" --tmdb-id 111110 --rss "https://pt.example/rss?passkey=xxx"

# 只填名字，自动搜 TMDB 补 id
python -m app add --name "无职转生 第三季" --rss "https://pt.example/rss?passkey=xxx"
```

### 4. 验证

```bash
python -m app list          # 看订阅与进度
python -m app check         # 立即做一次入库比对
python -m app test-notify   # 发测试消息
curl http://127.0.0.1:18080/healthz
```

## 配置

密钥优先读 `.env`，其次 `config/config.yaml`。全部环境变量见 `.env.example`。

### 通知模板（Jinja2，对齐 MoviePilot）

`config/notify_templates.txt`，用 `=== 事件名 ===` 分段，段内是字典字面量：

```
=== show_new ===
{"text": "📺 {{ title }} 更新：已入库 {{ done }}/{{ total }} 集（{{ pct }}%）{% if missing %}｜待入库 {{ missing }}{% endif %}", "image": "{{ image }}", "image_caption": "{{ title }} {{ done }}/{{ total }}"}
```

支持事件：`feed_new` / `show_new` / `library_update` / `done` / `sub_added`。
可用变量：`title` / `year` / `season` / `episode` / `done` / `total` / `missing` / `pct` / `image` / `link`。
支持完整 Jinja2 语法（`{% if %}` / `{% for %}` / 过滤器等），与 MoviePilot 同款。

## 目录结构

```
rss-tv/
├── app/
│   ├── titleparse.py   # 标题解析（片名/季/集/年份/片源标签/点号片名）
│   ├── tmdb.py         # TMDB 搜索与匹配
│   ├── emby.py         # Emby/Jellyfin 入库比对
│   ├── rss.py          # RSS 抓取与过滤
│   ├── notify.py       # 推送层（Message + Channel 多渠道抽象）
│   ├── templates.py    # Jinja2 通知模板
│   ├── hub.py          # 核心编排器
│   ├── webui.py        # Web 服务器 + 完整前端（三视图）
│   ├── db.py           # SQLite 状态存储
│   ├── config.py       # 配置加载
│   ├── cli.py          # 命令行
│   └── main.py         # 主入口
├── tests/              # 29 个单元测试
├── config/             # 配置文件
├── Dockerfile
└── docker-compose.yml
```

## 运行测试

```bash
pip install pytest
python -m pytest tests/ -q
```

## 不做什么

* 不接管下载器（qBittorrent/Transmission 自行配 RSS 自动下载）
* 不下载、不转码、不刮削元数据
* 只负责「通知 + 记账 + 退订」
