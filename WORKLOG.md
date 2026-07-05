# WORKLOG

## 2026-07-05

- 公共前端任务列表新增工作页 ruby 生成任务操作：任务完成后可重新打开工作源、恢复生成结果预览，并发布为正式歌词。
- 旧版歌词转换任务在任务列表中明确提示已直接写入正式歌词，不再误导用户寻找“转正”步骤。
- 交接文档改为说明 APK 打包共享 Web UI，避免误解为独立旧版前端。
- 修复 APK WebView 本地音频缓存响应：`/api/songs/<name>/audio` 支持 `Range: bytes=start-end`，有效范围返回 `206 Partial Content`，并设置 `Accept-Ranges`、`Content-Range`、`Content-Length`、`Content-Type`。
- 本地音频 Range 响应改为从文件偏移处读取并用限长流返回，避免整首音频读入内存。
- 公共前端 `web_static/app.js` 增加歌词点击 seek 的 ready 保护，音频 metadata/canplay 可用后再跳转并播放。
- 公共前端增强移动端侧栏左右滑，保持手机网页端和 APK 共用同一套手势逻辑。
- 增加无依赖 Node 回归测试 `tests/app_behavior.test.js` 覆盖上述关键行为。
