package com.utapractice.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.ContentResolver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.OpenableColumns;
import android.util.Base64;
import android.view.View;
import android.view.Window;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class MainActivity extends Activity {
    private static final String APP_ORIGIN = "https://utapractice.local";
    private static final String DEFAULT_SERVER_URL = "";
    private static final String PREFS_NAME = "utapractice_apk";
    private static final String KEY_SERVER_URL = "server_url";
    private static final String KEY_CLOUD_CONFIG_URL = "cloud_config_url";
    private static final String KEY_LAST_SYNC = "last_sync";
    private static final int REQUEST_IMPORT_AUDIO = 4101;
    private static final int REQUEST_IMPORT_LYRICS = 4102;

    private WebView webView;
    private SharedPreferences prefs;
    private String pendingImportSongName = "";
    private String pendingImportKind = "";

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);

        webView = new WebView(this);
        setContentView(webView);
        configureSystemBars();

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);

        webView.addJavascriptInterface(new AndroidBridge(), "UtaPracticeAndroid");
        webView.setWebChromeClient(new WebChromeClient());
        webView.setWebViewClient(new AppWebViewClient());
        webView.loadUrl(APP_ORIGIN + "/");
    }

    private void configureSystemBars() {
        Window window = getWindow();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            window.setStatusBarColor(Color.parseColor("#f7f8fb"));
            window.setNavigationBarColor(Color.parseColor("#f7f8fb"));
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.setDecorFitsSystemWindows(true);
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            int flags = window.getDecorView().getSystemUiVisibility() | View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                flags |= View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
            }
            window.getDecorView().setSystemUiVisibility(flags);
        }
    }

    private class AppWebViewClient extends WebViewClient {
        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
            Uri uri = request.getUrl();
            if (!APP_ORIGIN.equals(uri.getScheme() + "://" + uri.getHost())) {
                return super.shouldInterceptRequest(view, request);
            }

            String path = uri.getPath() == null ? "/" : uri.getPath();
            if ("/".equals(path) || "/index.html".equals(path)) {
                return assetResponse("text/html", "webapp/index.html");
            }
            if ("/manifest.webmanifest".equals(path)) {
                return assetResponse("application/manifest+json", "webapp/web_static/manifest.webmanifest");
            }
            if (path.startsWith("/web_static/")) {
                return assetResponse(mimeForPath(path), "webapp" + path);
            }
            if (path.startsWith("/api/")) {
                return handleApiRequest(request);
            }
            return super.shouldInterceptRequest(view, request);
        }
    }

    private WebResourceResponse handleApiRequest(WebResourceRequest request) {
        Uri uri = request.getUrl();
        String method = request.getMethod() == null ? "GET" : request.getMethod().toUpperCase();
        String pathAndQuery = uri.getEncodedPath() + (uri.getEncodedQuery() == null ? "" : "?" + uri.getEncodedQuery());
        if (!"GET".equals(method)) {
            return jsonResponse(405, "{\"error\":\"APK 本地写入请通过 Android Bridge 提交\"}");
        }

        try {
            WebResourceResponse cached = cachedFirstResponse(request);
            if (cached != null) {
                return cached;
            }

            String baseUrl = serverUrl();
            if (baseUrl.isEmpty()) return cachedApiResponse(request);
            byte[] remote = httpGetBytes(baseUrl + pathAndQuery);
            cacheGetResponse(uri, remote);
            return bytesResponse(mimeForPath(uri.getPath()), remote);
        } catch (Exception ignored) {
            return cachedApiResponse(request);
        }
    }

    private WebResourceResponse cachedFirstResponse(WebResourceRequest request) throws IOException {
        Uri uri = request.getUrl();
        String path = uri.getPath();
        if ("/api/songs".equals(path)) {
            return jsonResponse(200, localSongsListJson().toString());
        }
        if ("/api/settings".equals(path)) {
            return jsonResponse(200, localSettingsJson().toString());
        }
        if ("/api/convert-jobs".equals(path)) {
            return jsonResponse(200, "[]");
        }
        if ("/api/app/health".equals(path)) {
            return jsonResponse(200, "{\"ok\":true,\"name\":\"utapractice-apk\",\"offline\":true}");
        }

        String audioPrefix = "/api/songs/";
        if (path != null && path.startsWith(audioPrefix) && path.endsWith("/audio")) {
            String name = Uri.decode(path.substring(audioPrefix.length(), path.length() - "/audio".length()));
            File audio = audioFile(name);
            if (audio.exists()) return audioFileResponse(audioMimeFile(name), audio, request);
            return jsonResponse(404, "{\"error\":\"这首歌没有本地音频，请先导入或同步\"}");
        }

        if (path != null && path.startsWith(audioPrefix)) {
            String name = Uri.decode(path.substring(audioPrefix.length()));
            File song = songJsonFile(name);
            if (song.exists()) return fileResponse("application/json", song);
            return jsonResponse(404, "{\"error\":\"本地歌库没有这首歌\"}");
        }

        return null;
    }

    private void cacheGetResponse(Uri uri, byte[] bytes) throws Exception {
        String path = uri.getPath();
        if ("/api/songs".equals(path)) {
            writeFile(songsListFile(), bytes);
            return;
        }

        String prefix = "/api/songs/";
        if (path != null && path.startsWith(prefix) && !path.endsWith("/audio")) {
            String name = Uri.decode(path.substring(prefix.length()));
            writeFile(songJsonFile(name), bytes);
        }
    }

    private WebResourceResponse cachedApiResponse(WebResourceRequest request) {
        Uri uri = request.getUrl();
        String path = uri.getPath();
        try {
            if ("/api/songs".equals(path)) {
                return jsonResponse(200, localSongsListJson().toString());
            }
            if ("/api/settings".equals(path)) {
                return jsonResponse(200, localSettingsJson().toString());
            }
            if ("/api/convert-jobs".equals(path)) {
                return jsonResponse(200, "[]");
            }
            if ("/api/app/health".equals(path)) {
                return jsonResponse(200, "{\"ok\":true,\"name\":\"utapractice-apk\",\"offline\":true}");
            }

            String audioPrefix = "/api/songs/";
            if (path != null && path.startsWith(audioPrefix) && path.endsWith("/audio")) {
                String name = Uri.decode(path.substring(audioPrefix.length(), path.length() - "/audio".length()));
                File audio = audioFile(name);
                if (audio.exists()) return audioFileResponse(audioMimeFile(name), audio, request);
                return jsonResponse(404, "{\"error\":\"这首歌没有本地音频，请先导入或同步\"}");
            }

            if (path != null && path.startsWith(audioPrefix)) {
                String name = Uri.decode(path.substring(audioPrefix.length()));
                File song = songJsonFile(name);
                if (song.exists()) return fileResponse("application/json", song);
                return jsonResponse(404, "{\"error\":\"本地歌库没有这首歌\"}");
            }
        } catch (Exception error) {
            return jsonResponse(500, "{\"error\":\"读取 APK 离线缓存失败\"}");
        }
        return jsonResponse(503, "{\"error\":\"离线模式不支持这个接口\"}");
    }

    private class AndroidBridge {
        @JavascriptInterface
        public String apiRequest(String method, String path, String body) {
            try {
                String apiPath = apiPath(path);
                if (isLocalPostPath(apiPath)) {
                    JSONObject result = handleLocalPost(method, apiPath, body);
                    return result.toString();
                }
                return proxyJsonRequest(method, apiPath, body);
            } catch (Exception error) {
                return errorJson(error.getMessage()).toString();
            }
        }

        @JavascriptInterface
        public String getServerUrl() {
            return serverUrl();
        }

        @JavascriptInterface
        public void setServerUrl(String value) {
            prefs.edit().putString(KEY_SERVER_URL, cleanUrl(value)).apply();
        }

        @JavascriptInterface
        public String getCloudConfigUrl() {
            return prefs.getString(KEY_CLOUD_CONFIG_URL, "");
        }

        @JavascriptInterface
        public void loadCloudConfig(String value) {
            prefs.edit().putString(KEY_CLOUD_CONFIG_URL, cleanUrl(value)).apply();
            new Thread(() -> {
                try {
                    emit("cloud", "reading", 0, "正在读取云端配置");
                    String raw = new String(httpGetBytes(cleanUrl(value)), StandardCharsets.UTF_8);
                    JSONObject config = new JSONObject(raw);
                    String nextServer = cleanUrl(config.optString("default_base_url", config.optString("defaultBaseUrl", "")));
                    JSONArray servers = config.optJSONArray("servers");
                    if (nextServer.isEmpty() && servers != null && servers.length() > 0) {
                        JSONObject first = servers.optJSONObject(0);
                        if (first != null) nextServer = cleanUrl(first.optString("base_url", first.optString("baseUrl", first.optString("url", ""))));
                    }
                    if (nextServer.isEmpty()) throw new IOException("云端配置没有服务器地址");
                    prefs.edit().putString(KEY_SERVER_URL, nextServer).apply();
                    emit("cloud", "done", 100, nextServer);
                } catch (Exception error) {
                    emit("cloud", "failed", 0, "云端配置失败：" + error.getMessage());
                }
            }).start();
        }

        @JavascriptInterface
        public void syncAll() {
            new Thread(() -> {
                try {
                    String baseUrl = serverUrl();
                    if (baseUrl.isEmpty()) throw new IOException("请先填写同步服务器地址");
                    emit("sync", "running", 0, "正在读取远端歌库");
                    byte[] listBytes = httpGetBytes(baseUrl + "/api/songs");
                    writeFile(songsListFile(), listBytes);
                    JSONArray songs = new JSONArray(new String(listBytes, StandardCharsets.UTF_8));
                    int failed = 0;
                    for (int index = 0; index < songs.length(); index++) {
                        JSONObject summary = songs.optJSONObject(index);
                        if (summary == null) continue;
                        String name = summary.optString("name", "");
                        if (name.isEmpty()) continue;
                        int progress = Math.round(index * 100f / Math.max(songs.length(), 1));
                        emit("sync", "running", progress, "同步 " + (index + 1) + "/" + songs.length() + "：" + name);
                        try {
                            syncSong(baseUrl, name);
                        } catch (Exception error) {
                            failed += 1;
                        }
                    }
                    prefs.edit().putString(KEY_LAST_SYNC, String.valueOf(System.currentTimeMillis())).apply();
                    emit("sync", "done", 100, failed == 0 ? "同步完成；刷新歌库后可离线使用" : "同步完成，失败 " + failed + " 首；其余可离线使用");
                } catch (Exception error) {
                    emit("sync", "failed", 0, "同步失败：" + error.getMessage());
                }
            }).start();
        }

        @JavascriptInterface
        public void chooseAudioForSong(String songName) {
            openImportPicker("audio", cleanSongName(songName), REQUEST_IMPORT_AUDIO, "audio/*");
        }

        @JavascriptInterface
        public void chooseLyricsForSong(String songName) {
            openImportPicker("lyrics", cleanSongName(songName), REQUEST_IMPORT_LYRICS, "*/*");
        }
    }

    private JSONObject handleLocalPost(String method, String rawPath, String body) throws Exception {
        String normalizedMethod = method == null ? "GET" : method.trim().toUpperCase();
        if (!"POST".equals(normalizedMethod)) throw new IOException("APK 本地版暂不支持这个写方法");

        String path = apiPath(rawPath);
        String songPrefix = "/api/songs/";
        if (path.startsWith(songPrefix) && path.endsWith("/meta")) {
            String name = Uri.decode(path.substring(songPrefix.length(), path.length() - "/meta".length()));
            return handleMetaPost(name, new JSONObject(emptyJsonObject(body)));
        }
        if (path.startsWith(songPrefix) && path.endsWith("/lyrics")) {
            String name = Uri.decode(path.substring(songPrefix.length(), path.length() - "/lyrics".length()));
            return handleLyricsPost(name, new JSONArray(emptyJsonArray(body)));
        }
        if (path.startsWith(songPrefix) && path.endsWith("/delete")) {
            String name = Uri.decode(path.substring(songPrefix.length(), path.length() - "/delete".length()));
            return handleDeletePost(name);
        }
        if ("/api/upload/lyrics-text".equals(path)) {
            return handleLyricsTextPost(new JSONObject(emptyJsonObject(body)));
        }
        if ("/api/settings".equals(path)) {
            return handleSettingsPost(new JSONObject(emptyJsonObject(body)));
        }
        if ("/api/settings/test".equals(path)) {
            return handleSettingsTestPost();
        }
        throw new IOException("APK 本地版暂不支持这个接口");
    }

    private boolean isLocalPostPath(String path) {
        String songPrefix = "/api/songs/";
        return path != null && (
            "/api/upload/lyrics-text".equals(path)
                || "/api/settings".equals(path)
                || "/api/settings/test".equals(path)
                || path.startsWith(songPrefix) && (
                    path.endsWith("/meta")
                        || path.endsWith("/lyrics")
                        || path.endsWith("/delete")
                )
        );
    }

    private String proxyJsonRequest(String method, String path, String body) throws IOException {
        String normalizedMethod = method == null ? "GET" : method.trim().toUpperCase();
        String baseUrl = serverUrl();
        if (baseUrl.isEmpty()) throw new IOException("这个功能需要先配置可选后端");
        return new String(httpRequest(normalizedMethod, baseUrl + path, body).bytes, StandardCharsets.UTF_8);
    }

    private JSONObject handleSettingsPost(JSONObject payload) throws Exception {
        JSONObject settings = readLocalSettings();
        if (payload.has("base_url")) settings.put("base_url", payload.optString("base_url", "").trim());
        if (payload.has("model")) settings.put("model", payload.optString("model", "deepseek-v4-pro").trim());
        if (payload.has("api_key") && !payload.optString("api_key", "").trim().isEmpty()) {
            settings.put("api_key", payload.optString("api_key", "").trim());
        }
        writeLocalSettings(settings);
        JSONObject result = new JSONObject();
        result.put("ok", true);
        return result;
    }

    private JSONObject handleSettingsTestPost() throws Exception {
        JSONObject settings = readLocalSettings();
        String apiKey = settings.optString("api_key", "").trim();
        if (apiKey.isEmpty()) throw new IOException("API key is not configured");

        JSONObject payload = new JSONObject();
        payload.put("model", settings.optString("model", "deepseek-v4-pro"));
        payload.put("temperature", 0);
        payload.put("max_tokens", 8);
        JSONArray messages = new JSONArray();
        messages.put(new JSONObject().put("role", "system").put("content", "Reply with OK only."));
        messages.put(new JSONObject().put("role", "user").put("content", "Connection test. Reply OK."));
        payload.put("messages", messages);

        Map<String, String> headers = new LinkedHashMap<>();
        headers.put("Authorization", "Bearer " + apiKey);
        HttpResult response = httpRequest("POST", openAiChatCompletionsUrl(settings.optString("base_url", "")), payload.toString(), headers);
        JSONObject raw = new JSONObject(new String(response.bytes, StandardCharsets.UTF_8));
        String message = "OK";
        JSONArray choices = raw.optJSONArray("choices");
        if (choices != null && choices.length() > 0) {
            JSONObject choice = choices.optJSONObject(0);
            JSONObject contentMessage = choice == null ? null : choice.optJSONObject("message");
            String content = contentMessage == null ? "" : contentMessage.optString("content", "").trim();
            if (!content.isEmpty()) message = content;
        }

        JSONObject result = new JSONObject();
        result.put("ok", true);
        result.put("message", message);
        return result;
    }

    private JSONObject handleMetaPost(String name, JSONObject payload) throws Exception {
        JSONObject detail = readLocalSong(cleanSongName(name));
        if (payload.has("saved_key")) detail.put("saved_key", payload.optInt("saved_key", 0));
        if (payload.has("range")) detail.put("range", payload.optString("range", ""));
        if (payload.has("learned")) detail.put("learned", payload.optBoolean("learned", false));
        upsertLocalSong(detail);

        JSONObject info = new JSONObject();
        info.put("saved_key", detail.optInt("saved_key", 0));
        info.put("range", detail.optString("range", ""));
        info.put("learned", detail.optBoolean("learned", false));
        JSONObject result = new JSONObject();
        result.put("ok", true);
        result.put("info", info);
        return result;
    }

    private JSONObject handleLyricsPost(String name, JSONArray lyrics) throws Exception {
        JSONObject detail = readLocalSong(cleanSongName(name));
        detail.put("lyrics", lyrics);
        detail.put("has_lyrics", true);
        detail.put("lyrics_type", "json");
        upsertLocalSong(detail);

        JSONObject result = new JSONObject();
        result.put("ok", true);
        result.put("song_name", detail.optString("name", name));
        result.put("lines", lyrics.length());
        return result;
    }

    private JSONObject handleLyricsTextPost(JSONObject payload) throws Exception {
        String targetSong = cleanSongName(payload.optString("target_song", ""));
        String songName = targetSong.isEmpty() ? cleanSongName(payload.optString("song_name", "")) : targetSong;
        String lyricsText = payload.optString("lyrics_text", "").trim();
        String lyricsType = payload.optString("lyrics_type", "lrc").trim().toLowerCase();
        if (songName.isEmpty()) throw new IOException("Song name is required");
        if (lyricsText.isEmpty()) throw new IOException("Lyrics text is required");
        if (!"lrc".equals(lyricsType) && !"json".equals(lyricsType)) throw new IOException("Lyrics type must be lrc or json");

        JSONObject detail = readLocalSong(songName);
        if (targetSong.length() > 0 && !detail.optBoolean("has_audio", false)) {
            throw new IOException("Target song has no audio");
        }
        if (detail.optBoolean("has_lyrics", false)) {
            throw new IOException("Target song already has lyrics");
        }

        JSONArray lyrics = "json".equals(lyricsType) ? new JSONArray(lyricsText) : parseLrc(lyricsText);
        if (!"json".equals(lyricsType) && lyrics.length() == 0) {
            throw new IOException("LRC lyrics must include timestamped lines");
        }
        detail.put("lyrics", lyrics);
        detail.put("has_lyrics", true);
        detail.put("lyrics_type", lyricsType);
        upsertLocalSong(detail);

        JSONObject result = new JSONObject();
        result.put("ok", true);
        result.put("song_name", songName);
        result.put("saved", songName + "." + lyricsType);
        result.put("lines", lyrics.length());
        return result;
    }

    private JSONObject handleDeletePost(String name) throws Exception {
        String songName = cleanSongName(name);
        if (songName.isEmpty()) throw new IOException("Song name is required");
        deleteIfExists(songJsonFile(songName));
        deleteIfExists(audioFile(songName));
        deleteIfExists(audioMimeSidecar(songName));

        JSONArray songs = localSongsListJson();
        JSONArray next = new JSONArray();
        for (int index = 0; index < songs.length(); index++) {
            JSONObject song = songs.optJSONObject(index);
            if (song == null || songName.equals(song.optString("name", ""))) continue;
            next.put(song);
        }
        writeSongsListJson(next);
        JSONObject result = new JSONObject();
        result.put("ok", true);
        return result;
    }

    private void openImportPicker(String kind, String songName, int requestCode, String mimeType) {
        pendingImportKind = kind;
        pendingImportSongName = songName;
        runOnUiThread(() -> {
            try {
                Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType(mimeType);
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                startActivityForResult(intent, requestCode);
                emitImport(kind, "selecting", "请选择文件");
            } catch (Exception error) {
                emitImport(kind, "failed", "打开文件选择器失败：" + error.getMessage());
            }
        });
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST_IMPORT_AUDIO && requestCode != REQUEST_IMPORT_LYRICS) return;
        String kind = requestCode == REQUEST_IMPORT_AUDIO ? "audio" : "lyrics";
        if (resultCode != RESULT_OK || data == null || data.getData() == null) {
            emitImport(kind, "cancelled", "已取消选择");
            return;
        }
        handlePickedImportFile(kind, data.getData(), pendingImportSongName);
    }

    private void handlePickedImportFile(String kind, Uri uri, String requestedSongName) {
        new Thread(() -> {
            try {
                String displayName = displayNameForUri(uri);
                String fallbackName = cleanSongName(stemName(displayName));
                String songName = cleanSongName(requestedSongName);
                if (songName.isEmpty()) songName = fallbackName;
                if (songName.isEmpty()) throw new IOException("无法从文件名识别歌曲名");

                if ("audio".equals(kind)) {
                    importAudioUri(uri, songName);
                } else {
                    importLyricsUri(uri, songName, displayName);
                }
                emitImport(kind, "done", "已导入：" + songName);
            } catch (Exception error) {
                emitImport(kind, "failed", "导入失败：" + error.getMessage());
            }
        }).start();
    }

    private void importAudioUri(Uri uri, String songName) throws Exception {
        JSONObject detail = readLocalSong(songName);
        if (detail.optBoolean("has_audio", false)) throw new IOException("Target song already has audio");
        try (InputStream input = getContentResolver().openInputStream(uri)) {
            if (input == null) throw new IOException("无法读取音频文件");
            writeStream(audioFile(songName), input);
        }
        String mime = getContentResolver().getType(uri);
        writeText(audioMimeSidecar(songName), mime == null || mime.trim().isEmpty() ? "audio/mpeg" : mime);
        detail.put("has_audio", true);
        upsertLocalSong(detail);
    }

    private void importLyricsUri(Uri uri, String songName, String displayName) throws Exception {
        JSONObject detail = readLocalSong(songName);
        if (detail.optBoolean("has_lyrics", false)) throw new IOException("Target song already has lyrics");
        String raw;
        try (InputStream input = getContentResolver().openInputStream(uri)) {
            if (input == null) throw new IOException("无法读取歌词文件");
            raw = new String(readAll(input), StandardCharsets.UTF_8).trim();
        }
        String lowerName = displayName == null ? "" : displayName.toLowerCase();
        String lyricsType = lowerName.endsWith(".json") ? "json" : "lrc";
        JSONArray lyrics = "json".equals(lyricsType) ? new JSONArray(raw) : parseLrc(raw);
        if (!"json".equals(lyricsType) && lyrics.length() == 0) {
            throw new IOException("LRC lyrics must include timestamped lines");
        }
        detail.put("lyrics", lyrics);
        detail.put("has_lyrics", true);
        detail.put("lyrics_type", lyricsType);
        upsertLocalSong(detail);
    }

    private JSONObject errorJson(String message) {
        JSONObject result = new JSONObject();
        try {
            result.put("ok", false);
            result.put("error", message == null || message.trim().isEmpty() ? "APK 本地操作失败" : message);
        } catch (Exception ignored) {
        }
        return result;
    }

    private String apiPath(String value) {
        String text = value == null ? "" : value.trim();
        if (text.startsWith("http://") || text.startsWith("https://")) {
            Uri uri = Uri.parse(text);
            text = uri.getEncodedPath();
        }
        int queryIndex = text.indexOf('?');
        if (queryIndex >= 0) text = text.substring(0, queryIndex);
        return text.startsWith("/") ? text : "/" + text;
    }

    private String emptyJsonObject(String value) {
        String text = value == null ? "" : value.trim();
        return text.isEmpty() ? "{}" : text;
    }

    private String emptyJsonArray(String value) {
        String text = value == null ? "" : value.trim();
        return text.isEmpty() ? "[]" : text;
    }

    private JSONArray localSongsListJson() {
        File file = songsListFile();
        if (!file.exists()) return new JSONArray();
        try (InputStream input = new FileInputStream(file)) {
            String raw = new String(readAll(input), StandardCharsets.UTF_8);
            return new JSONArray(raw);
        } catch (Exception error) {
            return new JSONArray();
        }
    }

    private void writeSongsListJson(JSONArray songs) throws IOException {
        writeText(songsListFile(), songs.toString());
    }

    private JSONObject localSettingsJson() {
        JSONObject settings = readLocalSettings();
        JSONObject visible = new JSONObject();
        try {
            visible.put("base_url", settings.optString("base_url", ""));
            visible.put("model", settings.optString("model", "deepseek-v4-pro"));
            visible.put("has_api_key", !settings.optString("api_key", "").trim().isEmpty());
        } catch (Exception ignored) {
        }
        return visible;
    }

    private JSONObject readLocalSettings() {
        File file = settingsFile();
        if (!file.exists()) return defaultSettings();
        try (InputStream input = new FileInputStream(file)) {
            JSONObject settings = new JSONObject(new String(readAll(input), StandardCharsets.UTF_8));
            if (!settings.has("base_url")) settings.put("base_url", "");
            if (!settings.has("model") || settings.optString("model", "").trim().isEmpty()) {
                settings.put("model", "deepseek-v4-pro");
            }
            if (!settings.has("api_key")) settings.put("api_key", "");
            return settings;
        } catch (Exception error) {
            return defaultSettings();
        }
    }

    private JSONObject defaultSettings() {
        JSONObject settings = new JSONObject();
        try {
            settings.put("base_url", "");
            settings.put("model", "deepseek-v4-pro");
            settings.put("api_key", "");
        } catch (Exception ignored) {
        }
        return settings;
    }

    private void writeLocalSettings(JSONObject settings) throws IOException {
        writeText(settingsFile(), settings.toString());
    }

    private String openAiChatCompletionsUrl(String baseUrl) {
        String base = baseUrl == null ? "" : baseUrl.trim();
        if (base.isEmpty()) base = "https://api.openai.com/v1";
        while (base.endsWith("/")) base = base.substring(0, base.length() - 1);
        if (base.endsWith("/chat/completions")) return base;
        return base + "/chat/completions";
    }

    private JSONObject readLocalSong(String rawName) throws Exception {
        String name = cleanSongName(rawName);
        if (name.isEmpty()) throw new IOException("Song name is required");
        File file = songJsonFile(name);
        JSONObject detail;
        if (file.exists()) {
            try (InputStream input = new FileInputStream(file)) {
                detail = new JSONObject(new String(readAll(input), StandardCharsets.UTF_8));
            }
        } else {
            detail = new JSONObject();
        }
        detail.put("name", name);
        if (!detail.has("lyrics")) detail.put("lyrics", new JSONArray());
        if (!detail.has("learned")) detail.put("learned", false);
        if (!detail.has("range")) detail.put("range", "");
        if (!detail.has("saved_key")) detail.put("saved_key", 0);
        detail.put("has_audio", detail.optBoolean("has_audio", false) || audioFile(name).exists());
        detail.put("has_lyrics", detail.optBoolean("has_lyrics", false) || detail.optJSONArray("lyrics") != null && detail.optJSONArray("lyrics").length() > 0);
        if (!detail.optBoolean("has_lyrics", false)) detail.put("lyrics_type", JSONObject.NULL);
        return detail;
    }

    private void upsertLocalSong(JSONObject detail) throws Exception {
        String name = cleanSongName(detail.optString("name", ""));
        if (name.isEmpty()) throw new IOException("Song name is required");
        detail.put("name", name);
        detail.put("has_audio", detail.optBoolean("has_audio", false) || audioFile(name).exists());
        if (!detail.has("lyrics")) detail.put("lyrics", new JSONArray());
        JSONArray lyrics = detail.optJSONArray("lyrics");
        detail.put("has_lyrics", detail.optBoolean("has_lyrics", false) || lyrics != null && lyrics.length() > 0);
        if (!detail.optBoolean("has_lyrics", false)) detail.put("lyrics_type", JSONObject.NULL);
        writeText(songJsonFile(name), detail.toString());

        JSONArray songs = localSongsListJson();
        JSONArray next = new JSONArray();
        boolean replaced = false;
        JSONObject summary = songSummary(detail);
        for (int index = 0; index < songs.length(); index++) {
            JSONObject existing = songs.optJSONObject(index);
            if (existing == null) continue;
            if (name.equals(existing.optString("name", ""))) {
                next.put(summary);
                replaced = true;
            } else {
                next.put(existing);
            }
        }
        if (!replaced) next.put(summary);
        writeSongsListJson(next);
    }

    private JSONObject songSummary(JSONObject detail) throws Exception {
        JSONObject summary = new JSONObject();
        summary.put("name", detail.optString("name", ""));
        summary.put("has_audio", detail.optBoolean("has_audio", false));
        summary.put("has_lyrics", detail.optBoolean("has_lyrics", false));
        summary.put("lyrics_type", detail.optBoolean("has_lyrics", false) ? detail.optString("lyrics_type", "json") : JSONObject.NULL);
        summary.put("learned", detail.optBoolean("learned", false));
        summary.put("range", detail.optString("range", ""));
        summary.put("saved_key", detail.optInt("saved_key", 0));
        return summary;
    }

    private JSONArray parseLrc(String text) throws Exception {
        JSONArray lines = new JSONArray();
        Pattern pattern = Pattern.compile("\\[(\\d{1,2}):(\\d{2})(?:[.:](\\d{1,3}))?\\]");
        String[] rawLines = text == null ? new String[0] : text.split("\\r?\\n");
        for (String rawLine : rawLines) {
            Matcher matcher = pattern.matcher(rawLine);
            JSONArray times = new JSONArray();
            while (matcher.find()) {
                int minutes = Integer.parseInt(matcher.group(1));
                int seconds = Integer.parseInt(matcher.group(2));
                String fraction = matcher.group(3) == null ? "0" : matcher.group(3);
                double fractionSeconds = Integer.parseInt(fraction) / (fraction.length() == 3 ? 1000.0 : 100.0);
                times.put(Math.round((minutes * 60 + seconds + fractionSeconds) * 1000.0) / 1000.0);
            }
            if (times.length() == 0) continue;
            String lyric = pattern.matcher(rawLine).replaceAll("").trim();
            for (int index = 0; index < times.length(); index++) {
                JSONObject line = new JSONObject();
                line.put("time", times.getDouble(index));
                line.put("original_html", lyric);
                line.put("translation", "");
                lines.put(line);
            }
        }
        return sortLyricsByTime(lines);
    }

    private JSONArray sortLyricsByTime(JSONArray source) throws Exception {
        JSONArray sorted = new JSONArray();
        for (int sourceIndex = 0; sourceIndex < source.length(); sourceIndex++) {
            JSONObject line = source.getJSONObject(sourceIndex);
            int insertAt = sorted.length();
            for (int sortedIndex = 0; sortedIndex < sorted.length(); sortedIndex++) {
                if (line.optDouble("time", 0) < sorted.getJSONObject(sortedIndex).optDouble("time", 0)) {
                    insertAt = sortedIndex;
                    break;
                }
            }
            JSONArray next = new JSONArray();
            for (int index = 0; index < insertAt; index++) next.put(sorted.getJSONObject(index));
            next.put(line);
            for (int index = insertAt; index < sorted.length(); index++) next.put(sorted.getJSONObject(index));
            sorted = next;
        }
        return sorted;
    }

    private String displayNameForUri(Uri uri) {
        String name = null;
        if (ContentResolver.SCHEME_CONTENT.equals(uri.getScheme())) {
            try (Cursor cursor = getContentResolver().query(uri, null, null, null, null)) {
                if (cursor != null && cursor.moveToFirst()) {
                    int index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                    if (index >= 0) name = cursor.getString(index);
                }
            } catch (Exception ignored) {
            }
        }
        if (name == null || name.trim().isEmpty()) name = uri.getLastPathSegment();
        return name == null ? "untitled" : name;
    }

    private String stemName(String filename) {
        String name = filename == null ? "" : filename.trim();
        int slash = Math.max(name.lastIndexOf('/'), name.lastIndexOf('\\'));
        if (slash >= 0) name = name.substring(slash + 1);
        int dot = name.lastIndexOf('.');
        if (dot > 0) name = name.substring(0, dot);
        return name;
    }

    private String cleanSongName(String value) {
        String text = value == null ? "" : value.trim();
        text = text.replace('\r', ' ').replace('\n', ' ').replace('\t', ' ');
        text = text.replace('/', '／').replace('\\', '＼');
        while (text.contains("  ")) text = text.replace("  ", " ");
        return text.trim();
    }

    private void deleteIfExists(File file) throws IOException {
        if (file.exists() && !file.delete()) throw new IOException("删除本地文件失败：" + file.getName());
    }

    private void syncSong(String baseUrl, String name) throws Exception {
        String encodedName = URLEncoder.encode(name, "UTF-8").replace("+", "%20");
        byte[] songBytes = httpGetBytes(baseUrl + "/api/songs/" + encodedName);
        writeFile(songJsonFile(name), songBytes);

        JSONObject song = new JSONObject(new String(songBytes, StandardCharsets.UTF_8));
        if (!song.optBoolean("has_audio", false)) return;
        int key = song.optInt("saved_key", 0);
        HttpResult audio = httpGet(baseUrl + "/api/songs/" + encodedName + "/audio?key=" + key);
        writeFile(audioFile(name), audio.bytes);
        writeText(audioMimeSidecar(name), audio.contentType == null ? "audio/mpeg" : audio.contentType);
    }

    private void emit(String channel, String status, int progress, String message) {
        try {
            JSONObject detail = new JSONObject();
            detail.put("channel", channel);
            detail.put("status", status);
            detail.put("progress", progress);
            detail.put("message", message);
            if ("cloud".equals(channel) && "done".equals(status)) detail.put("serverUrl", message);
            String script = "window.dispatchEvent(new CustomEvent('utapractice-android', { detail: " + detail + " }));";
            runOnUiThread(() -> webView.evaluateJavascript(script, null));
        } catch (Exception ignored) {
        }
    }

    private void emitImport(String kind, String status, String message) {
        try {
            JSONObject detail = new JSONObject();
            detail.put("channel", "import");
            detail.put("kind", kind);
            detail.put("status", status);
            detail.put("progress", "done".equals(status) ? 100 : 0);
            detail.put("message", message);
            String script = "window.dispatchEvent(new CustomEvent('utapractice-android', { detail: " + detail + " }));";
            runOnUiThread(() -> webView.evaluateJavascript(script, null));
        } catch (Exception ignored) {
        }
    }

    private String serverUrl() {
        return cleanUrl(prefs.getString(KEY_SERVER_URL, DEFAULT_SERVER_URL));
    }

    private String cleanUrl(String value) {
        String text = value == null ? "" : value.trim();
        while (text.endsWith("/")) text = text.substring(0, text.length() - 1);
        return text;
    }

    private HttpResult httpGet(String urlText) throws IOException {
        return httpRequest("GET", urlText, null);
    }

    private HttpResult httpRequest(String method, String urlText, String body) throws IOException {
        return httpRequest(method, urlText, body, null);
    }

    private HttpResult httpRequest(String method, String urlText, String body, Map<String, String> extraHeaders) throws IOException {
        HttpURLConnection connection = (HttpURLConnection) new URL(urlText).openConnection();
        connection.setConnectTimeout(1500);
        connection.setReadTimeout(8000);
        connection.setRequestProperty("User-Agent", "utapractice-android");
        if (extraHeaders != null) {
            for (Map.Entry<String, String> entry : extraHeaders.entrySet()) {
                connection.setRequestProperty(entry.getKey(), entry.getValue());
            }
        }
        connection.setRequestMethod(method);
        if (!"GET".equals(method)) {
            byte[] bytes = (body == null ? "" : body).getBytes(StandardCharsets.UTF_8);
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json");
            connection.setRequestProperty("Content-Length", String.valueOf(bytes.length));
            try (OutputStream output = connection.getOutputStream()) {
                output.write(bytes);
            }
        }
        int status = connection.getResponseCode();
        String contentType = connection.getContentType();
        InputStream stream = status >= 200 && status < 300 ? connection.getInputStream() : connection.getErrorStream();
        try (InputStream input = stream == null ? new ByteArrayInputStream(new byte[0]) : stream) {
            byte[] bytes = readAll(input);
            if (status < 200 || status >= 300) {
                String text = new String(bytes, StandardCharsets.UTF_8).trim();
                throw new IOException(text.isEmpty() ? "HTTP " + status : text);
            }
            return new HttpResult(bytes, contentType);
        } finally {
            connection.disconnect();
        }
    }

    private byte[] httpGetBytes(String urlText) throws IOException {
        return httpGet(urlText).bytes;
    }

    private byte[] readAll(InputStream input) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int count;
        while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
        return output.toByteArray();
    }

    private WebResourceResponse assetResponse(String mimeType, String assetPath) {
        try {
            return new WebResourceResponse(mimeType, "UTF-8", getAssets().open(assetPath));
        } catch (IOException error) {
            return jsonResponse(404, "{\"error\":\"asset not found\"}");
        }
    }

    private WebResourceResponse bytesResponse(String mimeType, byte[] bytes) {
        return new WebResourceResponse(mimeType, "UTF-8", new ByteArrayInputStream(bytes));
    }

    private WebResourceResponse fileResponse(String mimeType, File file) throws IOException {
        Map<String, String> headers = new LinkedHashMap<>();
        headers.put("Content-Type", mimeType);
        headers.put("Content-Length", String.valueOf(file.length()));
        return new WebResourceResponse(mimeType, null, 200, "OK", headers, new FileInputStream(file));
    }

    private WebResourceResponse audioFileResponse(String mimeType, File file, WebResourceRequest request) throws IOException {
        long fileLength = file.length();
        String rangeHeader = request.getRequestHeaders() == null ? null : request.getRequestHeaders().get("Range");
        if (rangeHeader == null) rangeHeader = requestHeader(request, "Range");

        if (rangeHeader == null || rangeHeader.trim().isEmpty()) {
            Map<String, String> headers = audioHeaders(mimeType, fileLength);
            return new WebResourceResponse(mimeType, null, 200, "OK", headers, new FileInputStream(file));
        }

        RangeSpec range = parseRangeHeader(rangeHeader, fileLength);
        if (range == null) {
            Map<String, String> headers = audioHeaders(mimeType, 0);
            headers.put("Content-Range", "bytes */" + fileLength);
            return new WebResourceResponse(mimeType, null, 416, "Range Not Satisfiable", headers, new ByteArrayInputStream(new byte[0]));
        }

        Map<String, String> headers = audioHeaders(mimeType, range.length());
        headers.put("Content-Range", "bytes " + range.start + "-" + range.end + "/" + fileLength);
        return new WebResourceResponse(
            mimeType,
            null,
            206,
            "Partial Content",
            headers,
            new BoundedInputStream(openFileAt(file, range.start), range.length())
        );
    }

    private Map<String, String> audioHeaders(String mimeType, long contentLength) {
        Map<String, String> headers = new LinkedHashMap<>();
        headers.put("Accept-Ranges", "bytes");
        headers.put("Content-Type", mimeType);
        headers.put("Content-Length", String.valueOf(contentLength));
        return headers;
    }

    private String requestHeader(WebResourceRequest request, String name) {
        Map<String, String> headers = request.getRequestHeaders();
        if (headers == null) return null;
        String value = headers.get(name);
        if (value != null) return value;
        for (Map.Entry<String, String> entry : headers.entrySet()) {
            if (name.equalsIgnoreCase(entry.getKey())) return entry.getValue();
        }
        return null;
    }

    private RangeSpec parseRangeHeader(String header, long fileLength) {
        if (header == null || fileLength <= 0) return null;
        String value = header.trim();
        if (!value.startsWith("bytes=") || value.contains(",")) return null;

        String range = value.substring("bytes=".length()).trim();
        int dash = range.indexOf('-');
        if (dash < 0) return null;

        String startText = range.substring(0, dash).trim();
        String endText = range.substring(dash + 1).trim();
        try {
            long start;
            long end;
            if (startText.isEmpty()) {
                long suffixLength = Long.parseLong(endText);
                if (suffixLength <= 0) return null;
                start = Math.max(fileLength - suffixLength, 0);
                end = fileLength - 1;
            } else {
                start = Long.parseLong(startText);
                end = endText.isEmpty() ? fileLength - 1 : Long.parseLong(endText);
            }
            if (start < 0 || start >= fileLength || end < start) return null;
            return new RangeSpec(start, Math.min(end, fileLength - 1));
        } catch (NumberFormatException error) {
            return null;
        }
    }

    private FileInputStream openFileAt(File file, long offset) throws IOException {
        FileInputStream input = new FileInputStream(file);
        try {
            skipFully(input, offset);
            return input;
        } catch (IOException error) {
            input.close();
            throw error;
        }
    }

    private void skipFully(InputStream input, long offset) throws IOException {
        long remaining = offset;
        while (remaining > 0) {
            long skipped = input.skip(remaining);
            if (skipped <= 0) {
                if (input.read() == -1) throw new IOException("Unable to seek cached audio");
                skipped = 1;
            }
            remaining -= skipped;
        }
    }

    private WebResourceResponse jsonResponse(int status, String json) {
        WebResourceResponse response = bytesResponse("application/json", json.getBytes(StandardCharsets.UTF_8));
        response.setStatusCodeAndReasonPhrase(status, status == 200 ? "OK" : "Error");
        return response;
    }

    private String mimeForPath(String path) {
        if (path == null) return "application/octet-stream";
        if (path.endsWith(".html")) return "text/html";
        if (path.endsWith(".css")) return "text/css";
        if (path.endsWith(".js")) return "text/javascript";
        if (path.endsWith(".json") || path.startsWith("/api/")) return "application/json";
        if (path.endsWith(".webmanifest")) return "application/manifest+json";
        return "application/octet-stream";
    }

    private File cacheDir(String name) {
        File dir = new File(getFilesDir(), name);
        if (!dir.exists()) dir.mkdirs();
        return dir;
    }

    private File songsListFile() {
        return new File(cacheDir("cache"), "songs.json");
    }

    private File settingsFile() {
        return new File(cacheDir("config"), "settings.local.json");
    }

    private File songJsonFile(String name) {
        return new File(cacheDir("songs"), safeName(name) + ".json");
    }

    private File audioFile(String name) {
        return new File(cacheDir("audio"), safeName(name) + ".bin");
    }

    private File audioMimeSidecar(String name) {
        return new File(cacheDir("audio"), safeName(name) + ".mime");
    }

    private String audioMimeFile(String name) {
        File sidecar = audioMimeSidecar(name);
        if (!sidecar.exists()) return "audio/mpeg";
        try (InputStream input = new FileInputStream(sidecar)) {
            return new String(readAll(input), StandardCharsets.UTF_8).trim();
        } catch (IOException error) {
            return "audio/mpeg";
        }
    }

    private String safeName(String value) {
        return Base64.encodeToString(value.getBytes(StandardCharsets.UTF_8), Base64.URL_SAFE | Base64.NO_WRAP);
    }

    private void writeFile(File file, byte[] bytes) throws IOException {
        File parent = file.getParentFile();
        if (parent != null && !parent.exists()) parent.mkdirs();
        try (FileOutputStream output = new FileOutputStream(file)) {
            output.write(bytes);
        }
    }

    private void writeStream(File file, InputStream input) throws IOException {
        File parent = file.getParentFile();
        if (parent != null && !parent.exists()) parent.mkdirs();
        try (FileOutputStream output = new FileOutputStream(file)) {
            byte[] buffer = new byte[8192];
            int count;
            while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
        }
    }

    private void writeText(File file, String value) throws IOException {
        writeFile(file, value.getBytes(StandardCharsets.UTF_8));
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
            return;
        }
        super.onBackPressed();
    }

    private static class HttpResult {
        final byte[] bytes;
        final String contentType;

        HttpResult(byte[] bytes, String contentType) {
            this.bytes = bytes;
            this.contentType = contentType;
        }
    }

    private static class RangeSpec {
        final long start;
        final long end;

        RangeSpec(long start, long end) {
            this.start = start;
            this.end = end;
        }

        long length() {
            return end - start + 1;
        }
    }

    private static class BoundedInputStream extends InputStream {
        private final InputStream input;
        private long remaining;

        BoundedInputStream(InputStream input, long length) {
            this.input = input;
            this.remaining = length;
        }

        @Override
        public int read() throws IOException {
            if (remaining <= 0) return -1;
            int value = input.read();
            if (value != -1) remaining -= 1;
            return value;
        }

        @Override
        public int read(byte[] buffer, int offset, int length) throws IOException {
            if (remaining <= 0) return -1;
            int count = input.read(buffer, offset, (int) Math.min(length, remaining));
            if (count != -1) remaining -= count;
            return count;
        }

        @Override
        public void close() throws IOException {
            input.close();
        }
    }
}
