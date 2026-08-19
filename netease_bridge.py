#!/usr/bin/env python3
import json
import mimetypes
import os
import re
import tempfile
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

NCM_API_BASE = os.environ.get("NCM_API_BASE", "http://ncm-api:3000").rstrip("/")
SONG_DIR = Path(os.environ.get("SONG_DIR", "/data/songs"))
STATE_PATH = Path(os.environ.get("STATE_PATH", "/data/state/session.json"))
PORT = int(os.environ.get("PORT", "8503"))
CORS_ALLOW_ORIGIN = os.environ.get("CORS_ALLOW_ORIGIN", "*")
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "20"))
DOWNLOAD_TIMEOUT = float(os.environ.get("DOWNLOAD_TIMEOUT", "120"))
MAX_DOWNLOAD_BYTES = int(os.environ.get("MAX_DOWNLOAD_BYTES", str(500 * 1024 * 1024)))
AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".wav"}

SONG_DIR.mkdir(parents=True, exist_ok=True)
STATE_PATH.parent.mkdir(parents=True, exist_ok=True)


def json_load(path, default):
    try:
        with path.open("r", encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else default
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def json_save(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_cookie():
    return str(json_load(STATE_PATH, {}).get("cookie") or "").strip()


def save_cookie(cookie):
    state = json_load(STATE_PATH, {})
    state["cookie"] = cookie
    state["updated_at"] = int(time.time())
    json_save(STATE_PATH, state)


def clear_cookie():
    try:
        STATE_PATH.unlink()
    except FileNotFoundError:
        pass


def safe_name(value):
    text = re.sub(r'[\\/*?:"<>|]', "_", str(value or "")).strip().strip(".")
    return text[:160] or "未命名歌曲"


def ncm_request(path, params=None, method="GET"):
    params = dict(params or {})
    params.setdefault("timestamp", str(int(time.time() * 1000)))
    cookie = load_cookie()
    if cookie:
        params.setdefault("cookie", cookie)

    url = f"{NCM_API_BASE}{path}"
    data = None
    if method == "GET":
        url = f"{url}?{urlencode(params, doseq=True)}"
    else:
        data = urlencode(params, doseq=True).encode("utf-8")

    req = Request(
        url,
        data=data,
        headers={
            "User-Agent": "UtaPractice/1.0",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method=method,
    )
    with urlopen(req, timeout=HTTP_TIMEOUT) as response:
        set_cookie_headers = response.headers.get_all("Set-Cookie") or []
        raw = response.read()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("网易云接口返回格式异常")
    if set_cookie_headers:
        jar = SimpleCookie()
        for header_value in set_cookie_headers:
            try:
                jar.load(header_value)
            except Exception:
                continue
        cookie_header = "; ".join(f"{morsel.key}={morsel.value}" for morsel in jar.values())
        if cookie_header:
            payload["_set_cookie"] = cookie_header
    return payload


def nested_url_info(payload):
    queue = [payload]
    seen = set()
    while queue:
        value = queue.pop(0)
        if id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, dict):
            if value.get("url"):
                return value
            queue.extend(value.values())
        elif isinstance(value, list):
            queue.extend(value)
    return None


def normalize_search_song(song):
    artists = song.get("ar") or song.get("artists") or []
    album = song.get("al") or song.get("album") or {}
    return {
        "id": song.get("id"),
        "name": song.get("name") or "",
        "artist": " / ".join(str(a.get("name") or "") for a in artists if isinstance(a, dict) and a.get("name")),
        "album": album.get("name") if isinstance(album, dict) else "",
        "duration": song.get("dt") or song.get("duration") or 0,
        "fee": song.get("fee"),
    }


def lrc_text(song_id):
    for path in ("/lyric/new", "/lyric"):
        try:
            payload = ncm_request(path, {"id": str(song_id)})
        except Exception:
            continue
        lrc = payload.get("lrc")
        if isinstance(lrc, dict) and str(lrc.get("lyric") or "").strip():
            return str(lrc["lyric"])
    return ""


def existing_audio_for_stem(stem):
    for path in SONG_DIR.iterdir():
        if path.is_file() and path.stem == stem and path.suffix.lower() in AUDIO_EXTENSIONS:
            return path
    return None


def extension_for(info, response):
    kind = str((info or {}).get("type") or "").lower().strip(".")
    if kind in {"mp3", "flac", "m4a", "wav"}:
        return "." + kind

    content_type = (response.headers.get_content_type() or "").lower()
    guessed = mimetypes.guess_extension(content_type)
    if guessed in AUDIO_EXTENSIONS:
        return guessed

    suffix = Path(urlparse(response.geturl()).path).suffix.lower()
    if suffix in AUDIO_EXTENSIONS:
        return suffix
    return ".mp3"


def download_song(song_id, name, artist, level, with_lyrics):
    stem = safe_name(name)
    existing = existing_audio_for_stem(stem)
    if existing:
        raise FileExistsError(f"「{stem}」已经有本地音频：{existing.name}")

    url_payload = None
    errors = []
    for path in ("/song/download/url/v1", "/song/url/v1"):
        try:
            payload = ncm_request(path, {"id": str(song_id), "level": level})
            info = nested_url_info(payload)
            if info and info.get("url"):
                url_payload = info
                break
            errors.append(str(payload.get("message") or payload.get("msg") or f"{path} 没有返回可用链接"))
        except Exception as exc:
            errors.append(str(exc))

    if not url_payload:
        raise RuntimeError("无法取得歌曲下载地址：" + "；".join(errors[-2:]))

    remote_url = str(url_payload["url"])
    parsed = urlparse(remote_url)
    if parsed.scheme not in {"http", "https"}:
        raise RuntimeError("网易云返回了不支持的下载地址")

    req = Request(
        remote_url,
        headers={
            "User-Agent": "Mozilla/5.0 UtaPractice",
            "Referer": "https://music.163.com/",
        },
    )

    temp_path = None
    final_path = None
    total = 0
    try:
        with urlopen(req, timeout=DOWNLOAD_TIMEOUT) as response:
            ext = extension_for(url_payload, response)
            final_path = SONG_DIR / f"{stem}{ext}"
            fd, temp_name = tempfile.mkstemp(prefix=f".{stem}.", suffix=".download", dir=SONG_DIR)
            temp_path = Path(temp_name)
            with os.fdopen(fd, "wb") as out:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise RuntimeError("音频超过下载大小限制")
                    out.write(chunk)
            os.replace(temp_path, final_path)
            temp_path = None

        lyrics_saved = False
        lyrics_existing = any((SONG_DIR / f"{stem}{suffix}").exists() for suffix in (".json", ".lrc"))
        if with_lyrics and not lyrics_existing:
            text = lrc_text(song_id)
            if text.strip():
                (SONG_DIR / f"{stem}.lrc").write_text(text, encoding="utf-8")
                lyrics_saved = True

        return {
            "ok": True,
            "song_name": stem,
            "artist": artist,
            "filename": final_path.name,
            "bytes": total,
            "lyrics_saved": lyrics_saved,
            "lyrics_existing": lyrics_existing,
            "level": level,
        }
    except Exception:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        if final_path and final_path.exists() and final_path.stat().st_size == 0:
            final_path.unlink(missing_ok=True)
        raise


class Handler(BaseHTTPRequestHandler):
    server_version = "UtaPracticeNeteaseBridge/1.0"

    def log_message(self, fmt, *args):
        print(f"[netease-bridge] {self.address_string()} - {fmt % args}", flush=True)

    def cors(self):
        self.send_header("Access-Control-Allow-Origin", CORS_ALLOW_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")

    def send_json(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("请求正文必须是 JSON 对象")
        return value

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        query = {k: values[-1] for k, values in parse_qs(parsed.query).items() if values}
        try:
            if parsed.path == "/health":
                return self.send_json(200, {"ok": True})

            if parsed.path == "/api/netease/status":
                cookie = load_cookie()
                if not cookie:
                    return self.send_json(200, {"connected": False})
                payload = ncm_request("/login/status")
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                profile = data.get("profile") if isinstance(data, dict) else None
                account = data.get("account") if isinstance(data, dict) else None
                nickname = profile.get("nickname") if isinstance(profile, dict) else ""
                return self.send_json(
                    200,
                    {
                        "connected": bool(profile or account),
                        "nickname": nickname or "",
                        "profile": {
                            "userId": profile.get("userId"),
                            "nickname": nickname,
                            "avatarUrl": profile.get("avatarUrl"),
                        } if isinstance(profile, dict) else None,
                    },
                )

            if parsed.path == "/api/netease/qr/check":
                key = str(query.get("key") or "").strip()
                if not key:
                    return self.send_json(400, {"error": "缺少二维码 key"})
                payload = ncm_request("/login/qr/check", {"key": key})
                code = payload.get("code")
                cookie = str(payload.pop("_set_cookie", "") or payload.get("cookie") or "").strip()
                if code == 803 and cookie:
                    save_cookie(cookie)
                return self.send_json(
                    200,
                    {
                        "code": code,
                        "message": payload.get("message") or payload.get("msg") or "",
                        "connected": code == 803 and bool(cookie),
                    },
                )

            if parsed.path == "/api/netease/search":
                keywords = str(query.get("q") or "").strip()
                if not keywords:
                    return self.send_json(400, {"error": "请输入歌曲名或歌手"})
                limit = min(30, max(1, int(query.get("limit") or 20)))
                payload = ncm_request(
                    "/cloudsearch",
                    {"keywords": keywords, "type": "1", "limit": str(limit), "offset": "0"},
                )
                result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
                songs = result.get("songs") if isinstance(result, dict) else []
                normalized = [normalize_search_song(song) for song in (songs or []) if isinstance(song, dict)]
                return self.send_json(200, {"songs": normalized})

            return self.send_json(404, {"error": "接口不存在"})
        except Exception as exc:
            return self.send_json(502, {"error": str(exc)})

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/netease/qr/start":
                key_payload = ncm_request("/login/qr/key")
                key_data = key_payload.get("data") if isinstance(key_payload.get("data"), dict) else {}
                key = str(key_data.get("unikey") or "").strip()
                if not key:
                    raise RuntimeError("网易云没有返回二维码 key")
                qr_payload = ncm_request("/login/qr/create", {"key": key, "qrimg": "true"})
                qr_data = qr_payload.get("data") if isinstance(qr_payload.get("data"), dict) else {}
                return self.send_json(
                    200,
                    {
                        "key": key,
                        "qrimg": qr_data.get("qrimg") or "",
                        "qrurl": qr_data.get("qrurl") or "",
                    },
                )

            if parsed.path == "/api/netease/download":
                body = self.read_json()
                song_id = str(body.get("id") or "").strip()
                if not song_id.isdigit():
                    return self.send_json(400, {"error": "歌曲 ID 无效"})
                name = str(body.get("name") or "").strip()
                if not name:
                    return self.send_json(400, {"error": "歌曲名不能为空"})
                artist = str(body.get("artist") or "").strip()
                level = str(body.get("level") or "exhigh").strip().lower()
                allowed_levels = {"standard", "higher", "exhigh", "lossless", "hires"}
                if level not in allowed_levels:
                    return self.send_json(400, {"error": "不支持的音质"})
                result = download_song(
                    song_id,
                    name,
                    artist,
                    level,
                    bool(body.get("with_lyrics", True)),
                )
                return self.send_json(200, result)

            if parsed.path == "/api/netease/logout":
                try:
                    if load_cookie():
                        ncm_request("/logout")
                except Exception:
                    pass
                clear_cookie()
                return self.send_json(200, {"ok": True})

            return self.send_json(404, {"error": "接口不存在"})
        except FileExistsError as exc:
            return self.send_json(409, {"error": str(exc)})
        except (ValueError, json.JSONDecodeError) as exc:
            return self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            return self.send_json(502, {"error": str(exc)})


if __name__ == "__main__":
    print(f"[netease-bridge] listening on 0.0.0.0:{PORT}; ncm={NCM_API_BASE}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
