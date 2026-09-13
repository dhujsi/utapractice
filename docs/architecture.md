# 架构说明

## 目标

UtaPractice 是本地优先应用。Web 和 APK 应表现为同一个产品，而不是两套功能相近的实现。

## 分层

```text
共享界面（HTML / CSS / JavaScript）
           │ /api/*
     ┌─────┴─────┐
 Flask Web API   Android 本地 API
     │                 │
 文件歌库 / AI任务    APK 私有目录
     │
 网易云同源代理 ── netease_bridge ── NCM API
```

共享界面负责展示、交互和播放器状态。Flask 与 Android 分别实现相同的核心 API。Android Bridge 仅承接文件选择、WebView 无法读取请求体的本地写入以及本地音频播放等平台能力。

## 数据约束

- 一首歌以规范化存储键为主键；存储键不是展示名称。
- 正式歌曲文件只有一种写入格式：`<存储键>.json` SongDocument，包含 `schema_version`、`title`、`artists`、`album`、`source` 和 `lyrics`。
- API 保留 `name` 作为文件键兼容字段，UI 始终优先展示文档内的 `title` 与 `artists`。
- 音频和歌词同名即属于同一首歌。
- AI 草稿位于 `<歌名>.lyrics_source.json`，只保存编辑状态和任务历史，不是第二份正式歌词。
- AI 成功后原子替换正式 JSON；失败时保留上一版正式歌词。
- `.lrc` 及其翻译、罗马音伴侣文件仅作为旧数据读取入口。
- 旧的歌词数组 JSON 读取时自动兼容；旧的 `artist - title` 文件名只在缺少元数据时做一次兜底推断，不再作为长期数据协议。
- 删除歌曲使用可恢复归档；任务记录删除不影响已生成歌词。

## API 约束

- JSON 写接口必须校验输入并返回明确的 4xx；外部服务失败返回 502/503。
- Web 和 APK 对同一操作返回相同的核心字段。
- `/api/sync/manifest` 只返回歌曲摘要与 `document_version`、`audio_version`，APK 依据版本跳过未变化数据。
- 新功能必须先确定 API 合约，再分别实现 Flask 和 Android。
- 任何用户凭据都不能进入公开响应、日志、仓库或 APK 静态资源。

## 运行约束

- Docker 正式入口是 `web_app:app`，由 Gunicorn 单进程多线程运行。
- 当前任务队列和锁是进程内实现，因此不能开启多个 Gunicorn worker。
- 服务重启时，运行中的任务会标记为失败，用户可以重试。
- 项目面向可信局域网；需要公网部署时必须在反向代理层增加认证和 TLS。

## UI 约束

- 桌面、手机网页和 APK 共用同一页面。
- 用户界面使用“歌词草稿”“生成并应用”等产品语言，内部格式名只在编辑器等必要位置出现。
- 异步操作必须有进行中、成功、失败状态；危险操作必须使用应用内确认对话框。
- 所有功能必须可用键盘操作，并提供可辨识的焦点状态和无障碍名称。
