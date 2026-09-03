# 网易云搜索与离线下载

UtaPractice 的歌库页可以通过本地桥接服务搜索网易云，并把选中的音频直接保存到 `songs/`。下载完成后歌曲按普通本地歌曲处理，断网仍可播放。

默认 Docker Compose 会启动两个附加服务：

- `ncm-api`：基于仍在维护的 `NeteaseCloudMusicApiEnhanced/api-enhanced`，只在 Docker 内网暴露 3000。
- `netease-bridge`：在宿主机暴露 8503，负责保存登录 Cookie、搜索、下载和写入歌库。

首次使用时需要登录网易云。歌库页的“网易云下载”面板提供三种登录方式：

- **扫码登录**：桌面端使用，生成二维码后用网易云音乐 App 扫码确认。
- **手机验证码登录（推荐移动端）**：展开“免扫码登录”，填手机号 → 发送验证码 → 验证码登录。免扫码、免密码，也适用于手机/APK 场景。
- **粘贴 Cookie 登录（最稳）**：在官方网页 `music.163.com` 用任意方式登录后，复制 Cookie（含 `MUSIC_U` 等），粘贴进“粘贴 Cookie 登录”输入框保存。这是 `NeteaseCloudMusicApiEnhanced` 维护者官方推荐的兜底方案（见其 Issue #4）。

登录 Cookie 保存在 `data/netease/session.json`，不会写进 Git 仓库，也不会返回给前端。

前端请求默认走**同源代理**：`/api/netease/*` 由 Flask 主应用（8502）转发给 `netease-bridge`（8503），因此不依赖浏览器直连 8503，规避了 HTTPS 混合内容拦截、CORS 和手机端 8503 端口不可达导致的 `Failed to fetch`。若仍想直连桥接，可在“连接设置”里手动填 `http://host:8503`。

默认下载音质是 `exhigh`（极高 / 320 kbps）。可切换无损或 Hi-Res；实际可用音质取决于账号权益和歌曲版权。下载时优先调用网易云客户端的 `/song/download/url/v1` 接口取得真实音频地址，再把音频写入本地歌库。

网易云下载区只负责音频，不再同时保存 LRC。歌词统一从“生成歌词”工作页搜索、预览和生成；该工作页默认使用网易云歌词来源。

本地非 Docker 运行时，`web_app.py` 默认把 `/api/netease/*` 代理到 `http://127.0.0.1:8503`；如需指向其它地址，设置环境变量 `NETEASE_BRIDGE_BASE`。Docker 模式下 compose 已自动设为 `http://netease-bridge:8503`。

`netease-bridge` 没有内置公网身份验证。它适合局域网/本机使用；不要把 8503 直接暴露到公网。
