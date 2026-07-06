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
- 修复公共网页端 safe-area 空隙：默认安全区为 0，仅 APK 桥接环境启用 `env(safe-area-inset-*)`。
- 调整移动端侧栏横滑逻辑，允许从生成页输入框、文本域、按钮等控件区域发起水平滑动。
- 歌库上传改为“选择文件 + 明确上传”流程，音频/歌词上传均显示状态和错误信息。
- 音频上传新增“关联已有歌词”目标选择，可把任意文件名的单个音频绑定到已有歌词但无音频的条目。
- 后端 `/api/upload/audio` 支持 `target_song`，并拒绝多文件绑定、不存在目标、无歌词目标和已有音频目标。
- 歌词入库新增直接输入 LRC/JSON 功能，可保存为新歌词条目或关联到已有音频但无歌词的歌曲。
- 歌词文件上传新增“关联已有歌曲”和新歌名字段，支持把任意文件名歌词匹配到已有歌曲。
- 移动端侧栏切换“练习/歌库/生成歌词”不再自动收回，仅“载入练习”这种明确进入主播放区的动作会收回。
- 已构建包含本次 Web UI 的调试 APK：`dist/utapractice-lyrics-input-debug.apk`。

## 2026-07-06

- 明确 APK 架构方向：APK 是本地完备应用，和 Web 端共用同一套 UI；服务器同步是附加能力，不是可用前提。
- 新增 `docs/apk-local-backend.md`，记录后续维护约束：共享 Web UI、Flask 与 Android 实现同一 `/api/...` 合约、Android Bridge 只处理平台能力和 JSON 写入桥接。
- 新增 APK 本地 JSON 写入桥：共享前端在 APK 环境下通过 `window.UtaPracticeAndroid.apiRequest()` 提交非 GET JSON 请求。
- Android 本地后端支持保存学习状态、音域备注、默认 Key、JSON 歌词编辑结果、粘贴 LRC/JSON 歌词和本地删除歌曲。
- APK 本地歌库从空库可用：`/api/songs` 无服务器时返回本机列表或 `[]`，不再隐式依赖默认服务器。
- APK 新增 Android 文件选择导入桥：`chooseAudioForSong()` 和 `chooseLyricsForSong()` 可把音频/歌词复制到 App 私有目录并更新本地歌库。
- 共享前端在 APK 环境下把“上传音频/歌词”切换为“导入到本机”，导入完成后刷新歌库。
- 修复 APK 接口设置漏走同步服务器的问题：`/api/settings` 改为本地读写，`/api/settings/test` 改为用本机保存的 OpenAI 兼容配置直接测试，不再连接默认 `192.168.68.200`。
