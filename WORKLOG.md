# WORKLOG

## 2026-07-05

- 修复 APK WebView 本地音频缓存响应：`/api/songs/<name>/audio` 支持 `Range: bytes=start-end`，有效范围返回 `206 Partial Content`，并设置 `Accept-Ranges`、`Content-Range`、`Content-Length`、`Content-Type`。
- 本地音频 Range 响应改为从文件偏移处读取并用限长流返回，避免整首音频读入内存。
- 公共前端 `web_static/app.js` 增加歌词点击 seek 的 ready 保护，音频 metadata/canplay 可用后再跳转并播放。
- 公共前端增强移动端侧栏左右滑，保持手机网页端和 APK 共用同一套手势逻辑。
- 增加无依赖 Node 回归测试 `tests/app_behavior.test.js` 覆盖上述关键行为。
