# UtaPractice 练歌房

本地优先的练歌工具。Web 与 Android APK 共用一套界面和 API 合约，支持本地歌库、歌词编辑、升降调、A-B 循环、在线搜索、网易云下载和 AI 注音生成。

## 产品流程

1. 从网易云下载歌曲，或在歌库中导入本地音频。
2. 下载、导入或粘贴的歌词统一保存为 `songs/<存储键>.json`；文件内同时保存歌名、歌手、专辑、来源和歌词。
3. 需要注音时，在“歌词制作”中选择歌词版本并点击“生成并应用”。
4. AI 任务完成后直接更新同一个正式 JSON，播放器自动读取最新结果。

`.lrc`、`.zh.lrc` 和 `.roma.lrc` 只用于读取旧歌库；新数据不会再写成这些格式。

## 正式组件

- `web_app.py`：Flask API、歌库存储、歌词搜索与 AI 任务。
- `netease_bridge.py`：网易云登录、搜索、音频和歌词下载桥接。
- `templates/index.html`、`web_static/`：Web 与 APK 共用界面。
- `android/`：本地优先 Android 壳和 APK 内置 API 实现。
- `tests/`：后端行为测试与共享界面回归测试。

项目只有一个正式 Web 界面：`/`。手机浏览器使用同一个响应式页面，不维护第二套轻量前端。

## Docker 运行

```bash
docker compose up --build
```

打开 <http://localhost:8502>。Compose 会启动主应用、网易云桥接和它依赖的 NCM API。

持久化数据位于 `data/`：

```text
data/songs/                 音频与正式歌词 JSON
data/songs_archived/        归档歌曲
data/song_db.json           练习状态与备注
data/lyrics_jobs.json       AI 任务记录
data/settings.local.json    AI 服务设置（包含 API Key，不要提交）
data/netease/session.json   网易云会话（不要提交）
```

## 本地开发

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
PORT=8501 .venv/bin/python web_app.py
```

Windows PowerShell：

```powershell
py -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
$env:PORT = "8501"
.\.venv\Scripts\python.exe web_app.py
```

只启动主应用时，网易云功能需要另行运行桥接服务，或设置 `NETEASE_BRIDGE_BASE` 指向已有桥接地址。

## 歌曲文档 JSON

正式歌曲文件是一个统一的 SongDocument。`name` 只作为 API 和文件存储键，展示用的歌名、歌手不再从文件名猜测：

```json
{
  "schema_version": 1,
  "title": "歌曲名",
  "artists": ["歌手名"],
  "album": "专辑名",
  "source": {"provider": "netease", "song_id": "123"},
  "lyrics": [
    {
      "time": 12.34,
      "original_html": "<ruby>歌<rt>うた</rt></ruby>",
      "translation": "歌词翻译",
      "roman": "uta"
    }
  ]
}
```

服务端会校验时间和注音标签；前端渲染时只保留安全的 ruby 标签。旧的“歌词数组 JSON”仍可读取，下一次保存时会转成该格式。

APK 同步先读取 `/api/sync/manifest` 的版本索引，只下载发生变化的歌曲 JSON；音频按版本增量下载并发执行，未变化的音频不会重复传输。

## 配置

常用环境变量：

| 变量 | 默认值 | 用途 |
|---|---:|---|
| `PORT` | `8501` | 主应用端口 |
| `DATA_DIR` | 项目根目录 | 歌库、归档、设置和任务记录的统一数据目录 |
| `NETEASE_BRIDGE_BASE` | `http://127.0.0.1:8503` | 网易云桥接地址 |
| `NETEASE_PROXY_TIMEOUT` | `130` | 网易云代理超时秒数 |
| `MAX_UPLOAD_BYTES` | `1073741824` | 单次上传上限 |
| `CORS_ALLOW_ORIGIN` | 空 | 需要跨域调用 API 时显式设置 |

## 验证

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
node --test tests/app_behavior.test.js
node --check web_static/app.js
node --check web_static/netease.js
cd android && ANDROID_HOME=/home/er/android-sdk ./gradlew assembleDebug
```

APK 输出：`android/app/build/outputs/apk/debug/app-debug.apk`。

## 安全边界

本项目面向本机或可信局域网。网易云桥接没有公网身份认证，不应直接暴露到互联网。AI 与网易云凭据只保存在本地数据目录或 APK 私有目录。

更详细的架构约束见 `docs/architecture.md`，APK 合约见 `docs/apk-local-backend.md`。
