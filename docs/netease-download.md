# 网易云搜索与离线下载

UtaPractice 的歌库页可以通过本地桥接服务搜索网易云，并把选中的音频直接保存到 `songs/`。下载完成后歌曲按普通本地歌曲处理，断网仍可播放。

默认 Docker Compose 会启动两个附加服务：

- `ncm-api`：基于仍在维护的 `NeteaseCloudMusicApiEnhanced/api-enhanced`，只在 Docker 内网暴露 3000。
- `netease-bridge`：在宿主机暴露 8503，负责保存登录 Cookie、搜索、下载和写入歌库。

首次使用时在歌库页点“扫码登录”，用网易云音乐确认。登录 Cookie 保存在 `data/netease/session.json`，不会写进 Git 仓库，也不会返回给前端。

默认下载音质是 `exhigh`（极高 / 320 kbps）。可切换无损或 Hi-Res；实际可用音质取决于账号权益和歌曲版权。下载时优先调用网易云客户端的 `/song/download/url/v1` 接口取得真实音频地址，再把音频写入本地歌库；勾选“同时保存 LRC”时，如果歌库里还没有同名歌词，会一并保存网易云原文 LRC。

桥接服务默认地址是当前网页主机的 `8503` 端口。如果网页通过 HTTPS 打开，浏览器会阻止直接访问 HTTP 的 8503；这种情况下需要给桥接服务配置 HTTPS 入口，并在“连接设置”里填对应地址。

`netease-bridge` 没有内置公网身份验证。它适合局域网/本机使用；不要把 8503 直接暴露到公网。
