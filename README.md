# utapractice 练歌房

一个本地练歌 Web App。支持歌曲入库、歌词显示、升降调、A-B 循环、歌词 JSON 编辑，以及使用 OpenAI 兼容接口把 LRC + 注音文本转换成带 `<ruby>` 注音的 JSON 歌词。

## 功能

- 单页播放器：左侧管理歌曲，右侧练歌。
- 音频和歌词可分开入库：
  - 只上传音频：可以播放，没有歌词。
  - 只上传 LRC/JSON：可以显示歌词，没有音频时不会自动滚动。
  - 音频和歌词同名时会自动合并为同一首歌。
- 支持 MP3/WAV/FLAC/M4A。
- 支持 LRC 和 JSON 歌词。
- 支持实时升降调。
- 支持 A-B 重复播放。
- 支持备注、已学会标记、默认 Key。
- 内置歌词生成页：输入 OpenAI 兼容 Base URL、API Key、模型、LRC 和注音文本，生成 ruby JSON 并加入歌库。

## Docker 运行

```powershell
cd C:\Users\leaf\Documents\gits\utapractice
docker compose up --build
```

打开：

```text
http://localhost:8502
```

`docker-compose.yml` 默认把容器内的 `8501` 映射到本机 `8502`。

## 本地运行

先安装依赖：

```powershell
cd C:\Users\leaf\Documents\gits\utapractice
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

启动：

```powershell
.\.venv\Scripts\python.exe web_app.py
```

打开：

```text
http://localhost:8501
```

如果 `8501` 被占用，可以换端口：

```powershell
$env:PORT=8510
.\.venv\Scripts\python.exe web_app.py
```

## 数据目录

应用默认读取：

```text
songs/              音频和歌词文件
songs_archived/     删除后的归档文件
song_db.json        歌曲备注、默认 Key、已学会状态
generated/          升降调后生成的临时音频
settings.local.json OpenAI 兼容接口设置
```

Docker 运行时，`docker-compose.yml` 会把这些路径挂载到 `data/` 下：

```text
data/songs
data/songs_archived
data/song_db.json
```

## 歌词 JSON 格式

每一行歌词是一个对象：

```json
[
  {
    "time": 12.34,
    "original_html": "<ruby>歌<rt>うた</rt></ruby>",
    "translation": "歌词翻译"
  }
]
```

`original_html` 可以包含 `<ruby>` 和 `<rt>`，用于假名、粤拼等注音。

## 歌词生成

在侧栏进入 `生成歌词`：

1. 填 OpenAI 兼容 `Base URL`，例如 `https://api.openai.com/v1`。
2. 填 API Key。
3. 填模型名。
4. 输入歌曲名。
5. 粘贴 LRC。
6. 粘贴带假名/粤拼注音的文本。
7. 点击生成。

生成结果会保存为：

```text
songs/<歌曲名>.json
```

如果已有同名音频，会自动合并显示。

## APK / 手机使用

当前版本是移动端友好的 Web App。手机浏览器访问服务地址即可使用，也可以后续用 WebView/TWA 包成 APK。

## Cloudflare Pages

这个 Flask 版本不能直接部署到 Cloudflare Pages。Pages 更适合静态前端，动态后端需要 Pages Functions/Workers；而本项目依赖 Flask、文件系统写入、音频处理和 Docker 环境。

推荐部署方式：

- 自己的 Docker 主机、NAS、VPS。
- 需要公网访问时，用 Cloudflare Tunnel 暴露本地 Docker 服务。
