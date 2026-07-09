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
import java.util.ArrayList;
import java.util.UUID;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class MainActivity extends Activity {
    private static final String APP_ORIGIN = "https://utapractice.local";
    private static final String DEFAULT_SERVER_URL = "";
    private static final String PREFS_NAME = "utapractice_apk";
    private static final String KEY_SERVER_URL = "server_url";
    private static final String KEY_LAST_SYNC = "last_sync";
    private static final int REQUEST_IMPORT_AUDIO = 4101;
    private static final int REQUEST_IMPORT_LYRICS = 4102;
    private static final int SEARCH_TIMEOUT_MS = 6000;
    private static final int SEARCH_AGGREGATE_TIMEOUT_MS = 7000;

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
            return jsonResponse(200, localJobsListJson().toString());
        }
        if ("/api/app/health".equals(path)) {
            return jsonResponse(200, "{\"ok\":true,\"name\":\"utapractice-apk\",\"offline\":true}");
        }
        if (path != null && path.startsWith("/api/lyrics-workspace/")) {
            String name = Uri.decode(path.substring("/api/lyrics-workspace/".length()));
            File workspace = workspaceFile(name);
            if (workspace.exists()) return fileResponse("application/json", workspace);
            return jsonResponse(404, "{\"error\":\"Lyrics workspace not found\"}");
        }

        String audioPrefix = "/api/songs/";
        if (path != null && path.startsWith(audioPrefix) && path.endsWith("/audio")) {
            String name = Uri.decode(path.substring(audioPrefix.length(), path.length() - "/audio".length()));
            WebResourceResponse unavailable = audioUnavailableResponse(name);
            if (unavailable != null) return unavailable;
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
                return jsonResponse(200, localJobsListJson().toString());
            }
            if ("/api/app/health".equals(path)) {
                return jsonResponse(200, "{\"ok\":true,\"name\":\"utapractice-apk\",\"offline\":true}");
            }
            if (path != null && path.startsWith("/api/lyrics-workspace/")) {
                String name = Uri.decode(path.substring("/api/lyrics-workspace/".length()));
                File workspace = workspaceFile(name);
                if (workspace.exists()) return fileResponse("application/json", workspace);
                return jsonResponse(404, "{\"error\":\"Lyrics workspace not found\"}");
            }

            String audioPrefix = "/api/songs/";
            if (path != null && path.startsWith(audioPrefix) && path.endsWith("/audio")) {
                String name = Uri.decode(path.substring(audioPrefix.length(), path.length() - "/audio".length()));
                WebResourceResponse unavailable = audioUnavailableResponse(name);
                if (unavailable != null) return unavailable;
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
                if (isLocalPostPath(apiPath) || isLocalDeletePath(apiPath)) {
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
                    List<String> failedNames = new ArrayList<>();
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
                            failedNames.add(name + "：" + error.getMessage());
                        }
                    }
                    prefs.edit().putString(KEY_LAST_SYNC, String.valueOf(System.currentTimeMillis())).apply();
                    String message = failed == 0
                        ? "同步完成；刷新歌库后可离线使用"
                        : "同步完成，失败 " + failed + " 首：" + joinFirst(failedNames, 3);
                    emit("sync", "done", 100, message);
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
        String path = apiPath(rawPath);
        if ("DELETE".equals(normalizedMethod) && path.startsWith("/api/convert-jobs/")) {
            String jobId = Uri.decode(path.substring("/api/convert-jobs/".length()));
            return handleConvertJobDelete(jobId);
        }
        if (!"POST".equals(normalizedMethod)) throw new IOException("APK 本地版暂不支持这个写方法");

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
        if ("/api/lyrics-search".equals(path)) {
            return handleLyricsSearchPost(new JSONObject(emptyJsonObject(body)));
        }
        if ("/api/lyrics-preview".equals(path)) {
            return handleLyricsPreviewPost(new JSONObject(emptyJsonObject(body)));
        }
        if ("/api/convert-jobs".equals(path)) {
            return handleConvertJobPost(new JSONObject(emptyJsonObject(body)));
        }
        if (path.startsWith("/api/convert-jobs/") && path.endsWith("/stop")) {
            String jobId = Uri.decode(path.substring("/api/convert-jobs/".length(), path.length() - "/stop".length()));
            return handleConvertJobStop(jobId);
        }
        if (path.startsWith("/api/lyrics-align/")) {
            String name = Uri.decode(path.substring("/api/lyrics-align/".length()));
            return handleWorkspaceAlignPost(name);
        }
        if (path.startsWith("/api/lyrics-workspace/") && path.endsWith("/use-preview")) {
            String name = Uri.decode(path.substring("/api/lyrics-workspace/".length(), path.length() - "/use-preview".length()));
            return handleWorkspaceUsePreviewPost(name, new JSONObject(emptyJsonObject(body)));
        }
        if (path.startsWith("/api/lyrics-workspace/") && path.endsWith("/publish")) {
            String name = Uri.decode(path.substring("/api/lyrics-workspace/".length(), path.length() - "/publish".length()));
            return handleWorkspacePublishPost(name);
        }
        if (path.startsWith("/api/lyrics-workspace/")) {
            String name = Uri.decode(path.substring("/api/lyrics-workspace/".length()));
            return handleWorkspaceSavePost(name, new JSONObject(emptyJsonObject(body)));
        }
        throw new IOException("APK 本地版暂不支持这个接口");
    }

    private boolean isLocalPostPath(String path) {
        String songPrefix = "/api/songs/";
        return path != null && (
            "/api/upload/lyrics-text".equals(path)
                || "/api/settings".equals(path)
                || "/api/settings/test".equals(path)
                || "/api/lyrics-search".equals(path)
                || "/api/lyrics-preview".equals(path)
                || "/api/convert-jobs".equals(path)
                || path.startsWith("/api/lyrics-workspace/")
                || path.startsWith("/api/lyrics-align/")
                || path.startsWith("/api/convert-jobs/") && path.endsWith("/stop")
                || path.startsWith(songPrefix) && (
                    path.endsWith("/meta")
                        || path.endsWith("/lyrics")
                        || path.endsWith("/delete")
                )
        );
    }

    private boolean isLocalDeletePath(String path) {
        return path != null && path.startsWith("/api/convert-jobs/") && !path.endsWith("/stop");
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

    private JSONObject handleLyricsSearchPost(JSONObject payload) throws Exception {
        String songName = payload.optString("song_name", "").trim();
        String artist = payload.optString("artist", "").trim();
        String album = payload.optString("album", "").trim();
        String provider = payload.optString("provider", "aggregate").trim();
        if (songName.isEmpty()) throw new IOException("Song name is required");

        JSONObject result = new JSONObject();
        JSONObject errors = new JSONObject();
        JSONArray results = new JSONArray();
        boolean aggregate = provider.isEmpty() || "aggregate".equals(provider);
        List<String> providers = new ArrayList<>();
        if (aggregate) {
            providers.add("lrclib");
            providers.add("netease");
            providers.add("qq");
            providers.add("kugou");
        } else if (isApkSearchProvider(provider)) {
            providers.add(provider);
        } else {
            errors.put(provider, "未知歌词源");
        }
        if (aggregate) {
            results = searchProvidersConcurrently(providers, songName, artist, album, errors);
        } else if (!providers.isEmpty()) {
            try {
                results = searchProvider(providers.get(0), songName, artist, album);
            } catch (Exception error) {
                errors.put(providers.get(0), error.getMessage());
            }
        }
        result.put("results", results);
        result.put("errors", errors);
        return result;
    }

    private JSONObject handleLyricsPreviewPost(JSONObject payload) throws Exception {
        JSONObject result = payload.optJSONObject("result");
        if (result == null) result = payload;
        String provider = result.optString("provider", "");
        if ("lrclib".equals(provider)) return previewLrclib(result);
        if ("netease".equals(provider)) return previewNetease(result);
        if ("qq".equals(provider)) return previewQq(result);
        if ("kugou".equals(provider)) return previewKugou(result);
        throw new IOException("未知歌词源");
    }

    private boolean isApkSearchProvider(String provider) {
        return "lrclib".equals(provider) || "netease".equals(provider) || "qq".equals(provider) || "kugou".equals(provider);
    }

    private JSONArray searchProvider(String provider, String songName, String artist, String album) throws Exception {
        if ("lrclib".equals(provider)) return searchLrclib(songName, artist, album);
        if ("netease".equals(provider)) return searchNetease(songName, artist, album);
        if ("qq".equals(provider)) return searchQq(songName, artist, album);
        if ("kugou".equals(provider)) return searchKugou(songName, artist, album);
        throw new IOException("未知歌词源");
    }

    private JSONArray searchProvidersConcurrently(List<String> providers, String songName, String artist, String album, JSONObject errors) throws Exception {
        JSONArray results = new JSONArray();
        if (providers.isEmpty()) return results;
        ExecutorService executor = Executors.newFixedThreadPool(Math.min(4, providers.size()));
        Map<String, Future<JSONArray>> futures = new LinkedHashMap<>();
        try {
            for (String provider : providers) {
                Callable<JSONArray> task = () -> searchProvider(provider, songName, artist, album);
                futures.put(provider, executor.submit(task));
            }
            long deadline = System.currentTimeMillis() + SEARCH_AGGREGATE_TIMEOUT_MS;
            for (Map.Entry<String, Future<JSONArray>> entry : futures.entrySet()) {
                long remaining = Math.max(1, deadline - System.currentTimeMillis());
                try {
                    results = mergeSearchResults(results, entry.getValue().get(remaining, TimeUnit.MILLISECONDS));
                } catch (TimeoutException error) {
                    entry.getValue().cancel(true);
                    errors.put(entry.getKey(), "Timed out");
                } catch (Exception error) {
                    errors.put(entry.getKey(), error.getMessage());
                }
            }
        } finally {
            executor.shutdownNow();
        }
        return results;
    }

    private JSONArray searchLrclib(String songName, String artist, String album) throws Exception {
        StringBuilder broad = new StringBuilder();
        appendQuery(broad, "q", (songName + " " + artist).trim());
        String raw = new String(httpGetSearchBytes("https://lrclib.net/api/search?" + broad), StandardCharsets.UTF_8);
        JSONArray items = new JSONArray(raw);
        if (items.length() == 0 && (!artist.trim().isEmpty() || !album.trim().isEmpty())) {
            StringBuilder exact = new StringBuilder();
            appendQuery(exact, "track_name", songName);
            appendQuery(exact, "artist_name", artist);
            appendQuery(exact, "album_name", album);
            items = new JSONArray(new String(httpGetSearchBytes("https://lrclib.net/api/search?" + exact), StandardCharsets.UTF_8));
        }
        JSONArray results = new JSONArray();
        int count = Math.min(items.length(), 20);
        for (int index = 0; index < count; index++) {
            JSONObject item = items.optJSONObject(index);
            if (item == null) continue;
            JSONObject row = new JSONObject();
            boolean hasSynced = !item.optString("syncedLyrics", "").trim().isEmpty();
            row.put("provider", "lrclib");
            row.put("source_song_id", String.valueOf(item.opt("id")));
            row.put("title", item.optString("trackName", ""));
            row.put("artist", item.optString("artistName", ""));
            row.put("album", item.optString("albumName", ""));
            row.put("duration", item.has("duration") ? item.opt("duration") : JSONObject.NULL);
            row.put("has_original", hasSynced || !item.optString("plainLyrics", "").trim().isEmpty());
            row.put("has_translation", false);
            row.put("has_roman", false);
            row.put("has_word_timing", false);
            row.put("score", hasSynced ? 1 : 0.6);
            row.put("match_hint", "lrclib · " + row.optString("artist", "unknown"));
            row.put("source_data", new JSONObject());
            results.put(row);
        }
        return results;
    }

    private JSONArray searchNetease(String songName, String artist, String album) throws Exception {
        String keyword = (songName + " " + artist).trim();
        StringBuilder query = new StringBuilder();
        appendQuery(query, "s", keyword);
        appendQuery(query, "type", "1");
        appendQuery(query, "offset", "0");
        appendQuery(query, "limit", "10");
        String url = "https://music.163.com/api/search/get/web?" + query;
        String raw = new String(httpGetSearchBytes(url, neteaseHeaders()), StandardCharsets.UTF_8);
        JSONObject data = new JSONObject(raw);
        JSONObject result = data.optJSONObject("result");
        JSONArray songs = result == null ? new JSONArray() : result.optJSONArray("songs");
        if (songs == null) songs = new JSONArray();

        JSONArray results = new JSONArray();
        int count = Math.min(songs.length(), 20);
        for (int index = 0; index < count; index++) {
            JSONObject item = songs.optJSONObject(index);
            if (item == null) continue;
            Object sourceId = item.opt("id");
            if (sourceId == null || JSONObject.NULL.equals(sourceId)) continue;
            JSONObject albumObject = item.optJSONObject("album");
            JSONObject row = new JSONObject();
            row.put("provider", "netease");
            row.put("source_song_id", String.valueOf(sourceId));
            row.put("title", item.optString("name", ""));
            row.put("artist", joinArtistNames(item.optJSONArray("artists")));
            row.put("album", albumObject == null ? "" : albumObject.optString("name", ""));
            long durationMs = item.optLong("duration", 0);
            if (durationMs > 0) {
                row.put("duration", Math.round(durationMs / 1000.0));
            } else {
                row.put("duration", JSONObject.NULL);
            }
            row.put("has_original", true);
            row.put("has_translation", true);
            row.put("has_roman", false);
            row.put("has_word_timing", false);
            row.put("score", JSONObject.NULL);
            row.put("match_hint", "netease · " + row.optString("artist", "unknown"));
            row.put("source_data", new JSONObject());
            results.put(row);
        }
        return results;
    }

    private JSONArray searchQq(String songName, String artist, String album) throws Exception {
        String keyword = (songName + " " + artist).trim();
        String url = "https://c.y.qq.com/splcloud/fcgi-bin/smartbox_new.fcg?format=json&key=" + urlEncode(keyword);
        String raw = new String(httpGetSearchBytes(url, qqHeaders()), StandardCharsets.UTF_8);
        JSONObject data = new JSONObject(raw);
        JSONObject rootData = data.optJSONObject("data");
        JSONObject song = rootData == null ? null : rootData.optJSONObject("song");
        JSONArray items = song == null ? new JSONArray() : song.optJSONArray("itemlist");
        if (items == null) items = new JSONArray();
        JSONArray results = new JSONArray();
        int count = Math.min(items.length(), 20);
        for (int index = 0; index < count; index++) {
            JSONObject item = items.optJSONObject(index);
            if (item == null) continue;
            String songId = firstNonEmpty(item.optString("mid", ""), item.optString("songmid", ""));
            if (songId.isEmpty()) continue;
            JSONObject sourceData = new JSONObject();
            sourceData.put("qq_id", item.optString("id", ""));
            sourceData.put("docid", item.optString("docid", ""));
            JSONObject row = new JSONObject();
            row.put("provider", "qq");
            row.put("source_song_id", songId);
            row.put("title", item.optString("name", ""));
            row.put("artist", item.optString("singer", ""));
            row.put("album", item.optString("albumname", ""));
            row.put("duration", JSONObject.NULL);
            row.put("has_original", true);
            row.put("has_translation", true);
            row.put("has_roman", false);
            row.put("has_word_timing", false);
            row.put("score", JSONObject.NULL);
            row.put("match_hint", "qq · " + row.optString("artist", "unknown"));
            row.put("source_data", sourceData);
            results.put(row);
        }
        return results;
    }

    private JSONArray searchKugou(String songName, String artist, String album) throws Exception {
        String keyword = (songName + " " + artist).trim();
        StringBuilder query = new StringBuilder();
        appendQuery(query, "keyword", keyword);
        appendQuery(query, "page", "1");
        appendQuery(query, "pagesize", "10");
        String url = "https://songsearch.kugou.com/song_search_v2?" + query;
        String raw = new String(httpGetSearchBytes(url), StandardCharsets.UTF_8);
        JSONObject data = new JSONObject(raw);
        JSONObject dataObject = data.optJSONObject("data");
        JSONArray songs = dataObject == null ? new JSONArray() : dataObject.optJSONArray("lists");
        if (songs == null) songs = new JSONArray();

        JSONArray results = new JSONArray();
        int count = Math.min(songs.length(), 20);
        for (int index = 0; index < count; index++) {
            JSONObject item = songs.optJSONObject(index);
            if (item == null) continue;
            String fileHash = firstNonEmpty(item.optString("FileHash", ""), item.optString("Hash", ""));
            if (fileHash.isEmpty()) continue;
            JSONObject sourceData = new JSONObject();
            sourceData.put("album_id", item.opt("AlbumID"));
            sourceData.put("file_hash", fileHash);
            JSONObject row = new JSONObject();
            row.put("provider", "kugou");
            row.put("source_song_id", fileHash);
            row.put("title", item.optString("SongName", ""));
            row.put("artist", item.optString("SingerName", ""));
            row.put("album", item.optString("AlbumName", ""));
            if (item.has("Duration")) {
                row.put("duration", item.opt("Duration"));
            } else {
                row.put("duration", JSONObject.NULL);
            }
            row.put("has_original", true);
            row.put("has_translation", false);
            row.put("has_roman", false);
            row.put("has_word_timing", false);
            row.put("score", JSONObject.NULL);
            row.put("match_hint", "kugou · " + row.optString("artist", "unknown"));
            row.put("source_data", sourceData);
            results.put(row);
        }
        return results;
    }

    private JSONObject previewLrclib(JSONObject result) throws Exception {
        String sourceId = result.optString("source_song_id", "").trim();
        if (sourceId.isEmpty()) throw new IOException("Search result is missing source_song_id");
        String raw = new String(httpGetSearchBytes("https://lrclib.net/api/get/" + urlEncode(sourceId)), StandardCharsets.UTF_8);
        JSONObject data = new JSONObject(raw);
        String original = data.optString("syncedLyrics", "");
        if (original.trim().isEmpty()) original = data.optString("plainLyrics", "");
        return previewPayload(result, original, "", "");
    }

    private JSONObject previewNetease(JSONObject result) throws Exception {
        String sourceId = result.optString("source_song_id", "").trim();
        if (sourceId.isEmpty()) throw new IOException("Search result is missing source_song_id");
        StringBuilder query = new StringBuilder();
        appendQuery(query, "id", sourceId);
        appendQuery(query, "lv", "1");
        appendQuery(query, "kv", "1");
        appendQuery(query, "tv", "-1");
        appendQuery(query, "rv", "1");
        String url = "https://music.163.com/api/song/lyric?" + query;
        String raw = new String(httpGetSearchBytes(url, neteaseHeaders()), StandardCharsets.UTF_8);
        JSONObject data = new JSONObject(raw);
        String original = optObjectString(data, "lrc", "lyric");
        String translation = optObjectString(data, "tlyric", "lyric");
        String roman = optObjectString(data, "romalrc", "lyric");
        return previewPayload(result, original, translation, roman);
    }

    private JSONObject previewQq(JSONObject result) throws Exception {
        String songMid = result.optString("source_song_id", "").trim();
        if (songMid.isEmpty()) throw new IOException("Search result is missing source_song_id");
        StringBuilder query = new StringBuilder();
        appendQuery(query, "songmid", songMid);
        appendQuery(query, "g_tk", "5381");
        appendQuery(query, "format", "json");
        appendQuery(query, "nobase64", "1");
        String url = "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?" + query;
        String raw = new String(httpGetSearchBytes(url, qqHeaders()), StandardCharsets.UTF_8);
        JSONObject data = new JSONObject(raw);
        String original = data.optString("lyric", "");
        String translation = data.optString("trans", "");
        String roman = data.optString("roma", "");
        return previewPayload(result, original, translation, roman);
    }

    private JSONObject previewKugou(JSONObject result) throws Exception {
        JSONObject source = result.optJSONObject("source_data");
        if (source == null) source = new JSONObject();
        String keyword = (result.optString("title", "") + " " + result.optString("artist", "")).trim();
        String fileHash = firstNonEmpty(source.optString("file_hash", ""), result.optString("source_song_id", ""));
        StringBuilder searchQuery = new StringBuilder();
        appendQuery(searchQuery, "ver", "1");
        appendQuery(searchQuery, "man", "yes");
        appendQuery(searchQuery, "client", "pc");
        appendQuery(searchQuery, "keyword", keyword);
        appendQuery(searchQuery, "duration", result.optString("duration", "0"));
        appendQuery(searchQuery, "hash", fileHash);
        String searchUrl = "https://lyrics.kugou.com/search?" + searchQuery;
        String searchRaw = new String(httpGetSearchBytes(searchUrl), StandardCharsets.UTF_8);
        JSONObject searchData = new JSONObject(searchRaw);
        JSONArray candidates = searchData.optJSONArray("candidates");
        if (candidates == null || candidates.length() == 0) return previewPayload(result, "", "", "");
        JSONObject candidate = candidates.optJSONObject(0);
        if (candidate == null) return previewPayload(result, "", "", "");

        StringBuilder downloadQuery = new StringBuilder();
        appendQuery(downloadQuery, "ver", "1");
        appendQuery(downloadQuery, "client", "pc");
        appendQuery(downloadQuery, "id", candidate.optString("id", ""));
        appendQuery(downloadQuery, "accesskey", candidate.optString("accesskey", ""));
        appendQuery(downloadQuery, "fmt", "lrc");
        appendQuery(downloadQuery, "charset", "utf8");
        String downloadUrl = "https://lyrics.kugou.com/download?" + downloadQuery;
        String downloadRaw = new String(httpGetSearchBytes(downloadUrl), StandardCharsets.UTF_8);
        JSONObject data = new JSONObject(downloadRaw);
        String encoded = data.optString("content", "");
        String lyric = "";
        if (!encoded.trim().isEmpty()) {
            try {
                lyric = new String(Base64.decode(encoded, Base64.DEFAULT), StandardCharsets.UTF_8);
            } catch (Exception ignored) {
                lyric = "";
            }
        }
        return previewPayload(result, lyric, "", "");
    }

    private JSONObject previewPayload(JSONObject result, String original, String translation, String roman) throws Exception {
        JSONObject preview = new JSONObject();
        preview.put("result", result);
        preview.put("original_lrc", original == null ? "" : original);
        preview.put("translation_lrc", translation == null ? "" : translation);
        preview.put("roman_lrc", roman == null ? "" : roman);
        preview.put("line_rows", alignLrcSources(preview.optString("original_lrc", ""), preview.optString("translation_lrc", ""), preview.optString("roman_lrc", "")));
        preview.put("has_translation", !preview.optString("translation_lrc", "").trim().isEmpty());
        preview.put("has_roman", !preview.optString("roman_lrc", "").trim().isEmpty());
        return preview;
    }

    private JSONArray mergeSearchResults(JSONArray first, JSONArray second) throws Exception {
        JSONArray merged = new JSONArray();
        for (int source = 0; source < 2; source++) {
            JSONArray items = source == 0 ? first : second;
            for (int index = 0; index < items.length(); index++) {
                JSONObject candidate = items.optJSONObject(index);
                if (candidate == null) continue;
                String key = candidate.optString("provider", "") + ":" + candidate.optString("source_song_id", "");
                boolean seen = false;
                for (int existingIndex = 0; existingIndex < merged.length(); existingIndex++) {
                    JSONObject existing = merged.optJSONObject(existingIndex);
                    if (existing != null && key.equals(existing.optString("provider", "") + ":" + existing.optString("source_song_id", ""))) {
                        seen = true;
                        break;
                    }
                }
                if (!seen) merged.put(candidate);
            }
        }
        return merged;
    }

    private JSONObject handleWorkspaceSavePost(String name, JSONObject payload) throws Exception {
        String songName = cleanSongName(payload.optString("song_name", name));
        if (songName.isEmpty()) throw new IOException("Song name is required");
        JSONObject existing = readJsonObject(workspaceFile(songName));
        String originalLrc = payload.has("original_lrc") ? payload.optString("original_lrc", "") : existing.optString("original_lrc", "");
        String translationLrc = payload.has("translation_lrc") ? payload.optString("translation_lrc", "") : existing.optString("translation_lrc", "");
        String romanLrc = payload.has("roman_lrc") ? payload.optString("roman_lrc", "") : existing.optString("roman_lrc", "");

        JSONObject workspace = new JSONObject();
        workspace.put("song_name", songName);
        workspace.put("artist", payload.optString("artist", existing.optString("artist", "")));
        workspace.put("source", payload.optJSONObject("source") != null ? payload.optJSONObject("source") : existing.optJSONObject("source") != null ? existing.optJSONObject("source") : new JSONObject());
        workspace.put("original_lrc", originalLrc);
        workspace.put("translation_lrc", translationLrc);
        workspace.put("roman_lrc", romanLrc);
        workspace.put("line_rows", alignLrcSources(originalLrc, translationLrc, romanLrc));
        workspace.put("generated_lyrics", payload.optJSONArray("generated_lyrics") != null ? payload.optJSONArray("generated_lyrics") : new JSONArray());
        workspace.put("status", "draft");
        workspace.put("updated_at", nowText());
        writeJsonObject(workspaceFile(songName), workspace);
        return workspace;
    }

    private JSONObject handleWorkspaceUsePreviewPost(String name, JSONObject payload) throws Exception {
        JSONObject result = payload.optJSONObject("result");
        JSONObject preview = payload.optJSONObject("preview");
        if (result == null || preview == null) throw new IOException("Preview result is required");
        String songName = cleanSongName(payload.optString("song_name", name));
        if (songName.isEmpty()) throw new IOException("Song name is required");

        JSONObject source = new JSONObject();
        source.put("provider", result.optString("provider", ""));
        source.put("song_id", result.optString("source_song_id", ""));
        source.put("album", result.optString("album", ""));
        source.put("duration", result.has("duration") ? result.opt("duration") : JSONObject.NULL);

        JSONObject workspace = new JSONObject();
        workspace.put("song_name", songName);
        workspace.put("artist", payload.optString("artist", result.optString("artist", "")));
        workspace.put("source", source);
        workspace.put("original_lrc", preview.optString("original_lrc", ""));
        workspace.put("translation_lrc", preview.optString("translation_lrc", ""));
        workspace.put("roman_lrc", preview.optString("roman_lrc", ""));
        workspace.put("line_rows", alignLrcSources(workspace.optString("original_lrc", ""), workspace.optString("translation_lrc", ""), workspace.optString("roman_lrc", "")));
        workspace.put("generated_lyrics", new JSONArray());
        workspace.put("status", "draft");
        workspace.put("updated_at", nowText());
        writeJsonObject(workspaceFile(songName), workspace);
        return workspace;
    }

    private JSONObject handleWorkspaceAlignPost(String name) throws Exception {
        JSONObject workspace = readJsonObject(workspaceFile(name));
        if (workspace.length() == 0) throw new IOException("Lyrics workspace not found");
        workspace.put("line_rows", alignLrcSources(
            workspace.optString("original_lrc", ""),
            workspace.optString("translation_lrc", ""),
            workspace.optString("roman_lrc", "")
        ));
        workspace.put("generated_lyrics", new JSONArray());
        workspace.put("status", "draft");
        workspace.put("updated_at", nowText());
        writeJsonObject(workspaceFile(name), workspace);
        return workspace;
    }

    private JSONObject handleWorkspacePublishPost(String name) throws Exception {
        JSONObject workspace = readJsonObject(workspaceFile(name));
        if (workspace.length() == 0) throw new IOException("Lyrics workspace not found");
        JSONArray lyrics = workspace.optJSONArray("generated_lyrics");
        if (lyrics == null || lyrics.length() == 0) throw new IOException("No generated lyrics to publish");

        JSONObject detail = readLocalSong(cleanSongName(name));
        detail.put("lyrics", lyrics);
        detail.put("has_lyrics", true);
        detail.put("lyrics_type", "json");
        upsertLocalSong(detail);

        workspace.put("status", "published");
        workspace.put("updated_at", nowText());
        writeJsonObject(workspaceFile(name), workspace);

        JSONObject result = new JSONObject();
        result.put("ok", true);
        result.put("song_name", cleanSongName(name));
        result.put("published_count", lyrics.length());
        result.put("lyrics_count", lyrics.length());
        return result;
    }

    private JSONObject handleConvertJobPost(JSONObject payload) throws Exception {
        String songName = cleanSongName(payload.optString("song_name", ""));
        String type = payload.optString("type", payload.optString("job_type", "convert_lyrics"));
        if (songName.isEmpty()) throw new IOException("Song name is required");
        if (!"generate_ruby_from_rows".equals(type)) throw new IOException("APK 本地模式只支持工作源 ruby 生成");
        if (!workspaceFile(songName).exists()) throw new IOException("Lyrics workspace not found");
        if (readLocalSettings().optString("api_key", "").trim().isEmpty()) throw new IOException("API key is not configured");

        String jobId = UUID.randomUUID().toString().replace("-", "");
        JSONObject job = new JSONObject();
        job.put("id", jobId);
        job.put("type", "generate_ruby_from_rows");
        job.put("song_name", songName);
        job.put("mode", "workspace");
        job.put("progress", 0);
        job.put("status", "queued");
        job.put("message", "APK 本地任务已加入后台队列");
        job.put("steps", new JSONArray().put(step("APK 本地任务已加入后台队列")));
        job.put("created_at", nowText());
        job.put("updated_at", nowText());
        job.put("payload", payload);
        saveJob(job);
        startLocalRubyJob(jobId, songName);
        return publicJob(job);
    }

    private JSONObject handleConvertJobStop(String jobId) throws Exception {
        JSONObject job = readJobsJson().optJSONObject(jobId);
        if (job == null) throw new IOException("Job not found");
        job.put("stop_requested", true);
        job.put("status", "stopped");
        job.put("message", "任务已停止");
        job.put("updated_at", nowText());
        saveJob(job);
        return publicJob(job);
    }

    private JSONObject handleConvertJobDelete(String jobId) throws Exception {
        JSONObject jobs = readJobsJson();
        jobs.remove(jobId);
        writeJobsJson(jobs);
        JSONObject result = new JSONObject();
        result.put("ok", true);
        return result;
    }

    private void startLocalRubyJob(String jobId, String songName) {
        new Thread(() -> runLocalRubyJob(jobId, songName)).start();
    }

    private void runLocalRubyJob(String jobId, String songName) {
        try {
            updateJob(jobId, "running", 1, "任务已开始", false);
            performLocalRubyGeneration(jobId, songName);
            updateJob(jobId, "done", 100, "生成完成", true);
        } catch (Exception error) {
            try {
                if ("TASK_STOPPED".equals(error.getMessage())) {
                    updateJob(jobId, "stopped", 100, "任务已停止", true);
                } else {
                    updateJob(jobId, "failed", 100, "生成失败：" + error.getMessage(), true);
                }
            } catch (Exception ignored) {
            }
        }
    }

    private void performLocalRubyGeneration(String jobId, String songName) throws Exception {
        JSONObject workspace = readJsonObject(workspaceFile(songName));
        if (workspace.length() == 0) throw new IOException("Lyrics workspace not found");
        JSONArray rows = workspace.optJSONArray("line_rows");
        if (rows == null || rows.length() == 0) throw new IOException("Workspace has no aligned lyric rows");
        JSONObject settings = readLocalSettings();
        if (settings.optString("api_key", "").trim().isEmpty()) throw new IOException("API key is not configured");

        workspace.put("status", "generating");
        workspace.put("errors", new JSONArray());
        workspace.put("generated_lyrics", new JSONArray());
        workspace.put("updated_at", nowText());
        writeJsonObject(workspaceFile(songName), workspace);

        JSONArray generated = new JSONArray();
        int chunkSize = 8;
        int totalChunks = Math.max(1, (int) Math.ceil(rows.length() / (double) chunkSize));
        for (int start = 0, chunkNumber = 1; start < rows.length(); start += chunkSize, chunkNumber++) {
            if (jobStopRequested(jobId)) throw new IOException("TASK_STOPPED");
            int end = Math.min(rows.length(), start + chunkSize);
            appendJobStep(jobId, "正在生成第 " + chunkNumber + "/" + totalChunks + " 段");
            JSONArray chunk = new JSONArray();
            for (int index = start; index < end; index++) chunk.put(rows.getJSONObject(index));
            JSONArray chunkResult = generateRubyChunk(settings, workspace, chunk, chunkNumber, totalChunks);
            for (int index = 0; index < chunkResult.length(); index++) generated.put(chunkResult.getJSONObject(index));
            int progress = 1 + Math.round((chunkNumber / (float) totalChunks) * 94);
            updateJob(jobId, "running", progress, "已完成 " + chunkNumber + "/" + totalChunks + " 段", false);
        }

        workspace.put("generated_lyrics", generated);
        workspace.put("status", "generated");
        workspace.put("errors", new JSONArray());
        workspace.put("updated_at", nowText());
        writeJsonObject(workspaceFile(songName), workspace);
    }

    private JSONArray generateRubyChunk(JSONObject settings, JSONObject workspace, JSONArray rows, int chunkNumber, int totalChunks) throws Exception {
        JSONArray targetRows = new JSONArray();
        for (int index = 0; index < rows.length(); index++) {
            JSONObject row = rows.getJSONObject(index);
            JSONObject target = new JSONObject();
            target.put("row_number", index + 1);
            target.put("index", row.optInt("index", index));
            target.put("time", row.opt("time"));
            target.put("original", row.optString("original", ""));
            target.put("translation", row.optString("translation", ""));
            target.put("roman_or_pronunciation", row.optString("roman", ""));
            targetRows.put(target);
        }

        JSONObject task = new JSONObject();
        task.put("task", "Generate ruby annotated JSON for aligned lyric rows.");
        task.put("song_name", workspace.optString("song_name", ""));
        task.put("artist", workspace.optString("artist", ""));
        task.put("chunk_number", chunkNumber);
        task.put("total_chunks", totalChunks);
        task.put("rules", "Return JSON object only. Schema: {\"items\":[{\"row_number\":1,\"original_html\":\"lyrics with <ruby>漢字<rt>かんじ</rt></ruby>\",\"translation\":\"plain translation or empty\"}]}. Preserve every original lyric exactly outside ruby tags. Do not add rows or remove rows.");
        task.put("target_rows", targetRows);

        JSONObject request = new JSONObject();
        request.put("model", settings.optString("model", "deepseek-v4-pro"));
        request.put("temperature", 0.1);
        request.put("max_tokens", 6000);
        request.put("response_format", new JSONObject().put("type", "json_object"));
        JSONArray messages = new JSONArray();
        messages.put(new JSONObject().put("role", "system").put("content", "You generate strict JSON for Japanese lyric ruby annotation. Return JSON only."));
        messages.put(new JSONObject().put("role", "user").put("content", task.toString()));
        request.put("messages", messages);

        Map<String, String> headers = new LinkedHashMap<>();
        headers.put("Authorization", "Bearer " + settings.optString("api_key", ""));
        HttpResult response;
        try {
            response = httpRequest("POST", openAiChatCompletionsUrl(settings.optString("base_url", "")), request.toString(), headers);
        } catch (IOException error) {
            if (!unsupportedJsonMode(error.getMessage())) throw error;
            request.remove("response_format");
            response = httpRequest("POST", openAiChatCompletionsUrl(settings.optString("base_url", "")), request.toString(), headers);
        }
        JSONObject raw = new JSONObject(new String(response.bytes, StandardCharsets.UTF_8));
        JSONArray choices = raw.optJSONArray("choices");
        if (choices == null || choices.length() == 0) throw new IOException("模型没有返回 choices");
        JSONObject message = choices.getJSONObject(0).optJSONObject("message");
        String content = message == null ? "" : message.optString("content", "").trim();
        JSONArray items = modelItems(content);

        JSONArray normalized = new JSONArray();
        for (int index = 0; index < rows.length(); index++) {
            JSONObject source = rows.getJSONObject(index);
            JSONObject item = itemForRow(items, index + 1, index);
            JSONObject line = new JSONObject();
            line.put("time", source.opt("time"));
            String originalHtml = item == null ? "" : item.optString("original_html", "");
            if (originalHtml.trim().isEmpty()) originalHtml = source.optString("original", "");
            line.put("original_html", originalHtml);
            line.put("translation", item == null ? source.optString("translation", "") : item.optString("translation", source.optString("translation", "")));
            normalized.put(line);
        }
        return normalized;
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
                emitImport(kind, "done", "已导入：" + songName, songName);
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
        String audioMime = normalizeAudioMime(mime, "");
        writeText(audioMimeSidecar(songName), audioMime);
        detail.put("has_audio", true);
        detail.put("audio_playable", true);
        detail.put("audio_error", "");
        detail.put("audio_size", audioFile(songName).length());
        detail.put("audio_mime", audioMime);
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

    private JSONObject readJsonObject(File file) {
        if (!file.exists()) return new JSONObject();
        try (InputStream input = new FileInputStream(file)) {
            return new JSONObject(new String(readAll(input), StandardCharsets.UTF_8));
        } catch (Exception error) {
            return new JSONObject();
        }
    }

    private void writeJsonObject(File file, JSONObject value) throws IOException {
        writeText(file, value.toString());
    }

    private synchronized JSONObject readJobsJson() {
        return readJsonObject(jobsFile());
    }

    private synchronized void writeJobsJson(JSONObject jobs) throws IOException {
        writeJsonObject(jobsFile(), jobs);
    }

    private synchronized void saveJob(JSONObject job) throws Exception {
        JSONObject jobs = readJobsJson();
        jobs.put(job.optString("id", ""), job);
        writeJobsJson(jobs);
    }

    private synchronized void updateJob(String jobId, String status, int progress, String message, boolean finished) throws Exception {
        JSONObject jobs = readJobsJson();
        JSONObject job = jobs.optJSONObject(jobId);
        if (job == null) return;
        job.put("status", status);
        job.put("progress", progress);
        job.put("message", message);
        job.put("updated_at", nowText());
        if (finished) job.put("finished_at", nowText());
        jobs.put(jobId, job);
        writeJobsJson(jobs);
    }

    private synchronized void appendJobStep(String jobId, String message) throws Exception {
        JSONObject jobs = readJobsJson();
        JSONObject job = jobs.optJSONObject(jobId);
        if (job == null) return;
        JSONArray steps = job.optJSONArray("steps");
        if (steps == null) steps = new JSONArray();
        steps.put(step(message));
        job.put("steps", steps);
        job.put("message", message);
        job.put("updated_at", nowText());
        jobs.put(jobId, job);
        writeJobsJson(jobs);
    }

    private synchronized boolean jobStopRequested(String jobId) {
        JSONObject job = readJobsJson().optJSONObject(jobId);
        return job != null && job.optBoolean("stop_requested", false);
    }

    private JSONArray localJobsListJson() {
        JSONObject jobs = readJobsJson();
        JSONArray items = new JSONArray();
        Iterator<String> keys = jobs.keys();
        while (keys.hasNext()) {
            JSONObject job = jobs.optJSONObject(keys.next());
            if (job != null) items.put(publicJob(job));
        }
        return items;
    }

    private JSONObject publicJob(JSONObject job) {
        JSONObject result = new JSONObject();
        Iterator<String> keys = job.keys();
        while (keys.hasNext()) {
            String key = keys.next();
            if ("payload".equals(key)) continue;
            try {
                result.put(key, job.opt(key));
            } catch (Exception ignored) {
            }
        }
        return result;
    }

    private JSONObject step(String message) throws Exception {
        JSONObject step = new JSONObject();
        step.put("time", nowText());
        step.put("message", message);
        return step;
    }

    private String nowText() {
        return String.valueOf(System.currentTimeMillis());
    }

    private void appendQuery(StringBuilder query, String key, String value) throws Exception {
        String text = value == null ? "" : value.trim();
        if (text.isEmpty()) return;
        if (query.length() > 0) query.append('&');
        query.append(urlEncode(key)).append('=').append(urlEncode(text));
    }

    private String urlEncode(String value) throws Exception {
        return URLEncoder.encode(value == null ? "" : value, "UTF-8").replace("+", "%20");
    }

    private String firstNonEmpty(String... values) {
        for (String value : values) {
            String text = value == null ? "" : value.trim();
            if (!text.isEmpty()) return text;
        }
        return "";
    }

    private String joinArtistNames(JSONArray artists) {
        if (artists == null) return "";
        StringBuilder names = new StringBuilder();
        for (int index = 0; index < artists.length(); index++) {
            JSONObject artist = artists.optJSONObject(index);
            if (artist == null) continue;
            String name = artist.optString("name", "").trim();
            if (name.isEmpty()) continue;
            if (names.length() > 0) names.append('/');
            names.append(name);
        }
        return names.toString();
    }

    private String optObjectString(JSONObject parent, String objectKey, String valueKey) {
        JSONObject object = parent == null ? null : parent.optJSONObject(objectKey);
        return object == null ? "" : object.optString(valueKey, "");
    }

    private JSONArray modelItems(String content) throws Exception {
        String text = content == null ? "" : content.trim();
        if (text.startsWith("```")) {
            text = text.replaceFirst("^```(?:json)?\\s*", "").replaceFirst("\\s*```$", "").trim();
        }
        if (text.startsWith("[")) return new JSONArray(text);
        JSONObject object = new JSONObject(text);
        JSONArray items = object.optJSONArray("items");
        if (items != null) return items;
        JSONArray result = object.optJSONArray("result");
        if (result != null) return result;
        throw new IOException("模型返回 JSON 中没有 items 数组");
    }

    private JSONObject itemForRow(JSONArray items, int rowNumber, int fallbackIndex) {
        for (int index = 0; index < items.length(); index++) {
            JSONObject item = items.optJSONObject(index);
            if (item != null && item.optInt("row_number", -1) == rowNumber) return item;
        }
        return items.optJSONObject(fallbackIndex);
    }

    private boolean unsupportedJsonMode(String message) {
        String text = message == null ? "" : message.toLowerCase();
        return text.contains("response_format") || text.contains("json_object") || text.contains("unsupported") || text.contains("invalid parameter");
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
        if (detail.optBoolean("has_audio", false) && !detail.has("audio_playable")) detail.put("audio_playable", true);
        if (!detail.has("audio_error")) detail.put("audio_error", "");
        detail.put("has_lyrics", detail.optBoolean("has_lyrics", false) || detail.optJSONArray("lyrics") != null && detail.optJSONArray("lyrics").length() > 0);
        if (!detail.optBoolean("has_lyrics", false)) detail.put("lyrics_type", JSONObject.NULL);
        return detail;
    }

    private void upsertLocalSong(JSONObject detail) throws Exception {
        String name = cleanSongName(detail.optString("name", ""));
        if (name.isEmpty()) throw new IOException("Song name is required");
        detail.put("name", name);
        detail.put("has_audio", detail.optBoolean("has_audio", false) || audioFile(name).exists());
        if (detail.optBoolean("has_audio", false) && !detail.has("audio_playable")) detail.put("audio_playable", true);
        if (!detail.has("audio_error")) detail.put("audio_error", "");
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
        summary.put("audio_playable", detail.optBoolean("audio_playable", true));
        summary.put("audio_error", detail.optString("audio_error", ""));
        summary.put("audio_size", detail.optLong("audio_size", 0));
        summary.put("audio_mime", detail.optString("audio_mime", ""));
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

    private JSONArray alignLrcSources(String originalLrc, String translationLrc, String romanLrc) throws Exception {
        JSONArray originalRows = groupLrcRows(parseLrcTextRows(originalLrc));
        JSONArray translationRows = groupLrcRows(parseLrcTextRows(translationLrc));
        JSONArray romanRows = groupLrcRows(parseLrcTextRows(romanLrc));
        JSONArray lineRows = new JSONArray();
        for (int index = 0; index < originalRows.length(); index++) {
            JSONObject row = originalRows.getJSONObject(index);
            double time = row.optDouble("time", 0);
            JSONObject line = new JSONObject();
            line.put("index", index);
            line.put("time", row.opt("time"));
            line.put("original", row.optString("text", ""));
            line.put("translation", nearestText(translationRows, time));
            line.put("roman", nearestText(romanRows, time));
            lineRows.put(line);
        }
        return lineRows;
    }

    private JSONArray parseLrcTextRows(String text) throws Exception {
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
                line.put("text", lyric);
                lines.put(line);
            }
        }
        return sortRowsByTime(lines);
    }

    private JSONArray groupLrcRows(JSONArray rows) throws Exception {
        JSONArray grouped = new JSONArray();
        for (int index = 0; index < rows.length(); index++) {
            JSONObject row = rows.getJSONObject(index);
            double time = row.optDouble("time", 0);
            String text = row.optString("text", "").trim();
            JSONObject current = grouped.length() == 0 ? null : grouped.getJSONObject(grouped.length() - 1);
            if (current == null || current.optDouble("time", 0) != time) {
                current = new JSONObject();
                current.put("time", row.opt("time"));
                current.put("text", text);
                current.put("texts", new JSONArray());
                grouped.put(current);
            }
            if (!text.isEmpty()) {
                JSONArray texts = current.optJSONArray("texts");
                if (texts == null) texts = new JSONArray();
                texts.put(text);
                current.put("texts", texts);
                current.put("text", joinTexts(texts));
            }
        }
        return grouped;
    }

    private String nearestText(JSONArray rows, double time) {
        if (rows == null || rows.length() == 0) return "";
        String exact = "";
        double bestDistance = Double.MAX_VALUE;
        String best = "";
        for (int index = 0; index < rows.length(); index++) {
            JSONObject row = rows.optJSONObject(index);
            if (row == null) continue;
            double distance = Math.abs(row.optDouble("time", 0) - time);
            if (distance == 0) exact = exact.isEmpty() ? row.optString("text", "") : exact + " / " + row.optString("text", "");
            if (distance < bestDistance) {
                bestDistance = distance;
                best = row.optString("text", "");
            }
        }
        if (!exact.isEmpty()) return exact;
        return bestDistance <= 0.75 ? best : "";
    }

    private String joinTexts(JSONArray texts) {
        StringBuilder builder = new StringBuilder();
        for (int index = 0; index < texts.length(); index++) {
            String text = texts.optString(index, "").trim();
            if (text.isEmpty()) continue;
            if (builder.length() > 0) builder.append(" / ");
            builder.append(text);
        }
        return builder.toString();
    }

    private JSONArray sortRowsByTime(JSONArray source) throws Exception {
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

    private String joinFirst(List<String> values, int limit) {
        StringBuilder builder = new StringBuilder();
        int count = Math.min(values.size(), limit);
        for (int index = 0; index < count; index++) {
            if (builder.length() > 0) builder.append("；");
            builder.append(values.get(index));
        }
        if (values.size() > limit) builder.append("；另有 ").append(values.size() - limit).append(" 首");
        return builder.toString();
    }

    private String normalizeAudioMime(String contentType, String fallback) {
        String mime = contentType == null ? "" : contentType.split(";", 2)[0].trim().toLowerCase();
        if (mime.isEmpty() || "application/octet-stream".equals(mime)) {
            mime = fallback == null ? "" : fallback.split(";", 2)[0].trim().toLowerCase();
        }
        if (mime.isEmpty() || "application/octet-stream".equals(mime)) return "audio/mpeg";
        return mime;
    }

    private void markLocalAudioPlayable(JSONObject song, HttpResult audio) throws Exception {
        String mime = normalizeAudioMime(audio.contentType, song.optString("audio_mime", ""));
        song.put("has_audio", true);
        song.put("audio_playable", true);
        song.put("audio_error", "");
        song.put("audio_size", audio.bytes.length);
        song.put("audio_mime", mime);
    }

    private WebResourceResponse audioUnavailableResponse(String name) {
        JSONObject detail = readJsonObject(songJsonFile(name));
        if (detail.optBoolean("audio_playable", true)) return null;
        return jsonResponse(415, errorJson(detail.optString("audio_error", "音频格式不支持")).toString());
    }

    private void syncSong(String baseUrl, String name) throws Exception {
        String encodedName = URLEncoder.encode(name, "UTF-8").replace("+", "%20");
        byte[] songBytes = httpGetBytes(baseUrl + "/api/songs/" + encodedName);
        JSONObject song = new JSONObject(new String(songBytes, StandardCharsets.UTF_8));
        if (!song.optBoolean("has_audio", false)) {
            deleteIfExists(audioFile(name));
            deleteIfExists(audioMimeSidecar(name));
            upsertLocalSong(song);
            return;
        }
        if (!song.optBoolean("audio_playable", true)) {
            deleteIfExists(audioFile(name));
            deleteIfExists(audioMimeSidecar(name));
            upsertLocalSong(song);
            return;
        }
        int key = song.optInt("saved_key", 0);
        HttpResult audio = httpGet(baseUrl + "/api/songs/" + encodedName + "/audio?key=" + key);
        writeFile(audioFile(name), audio.bytes);
        markLocalAudioPlayable(song, audio);
        writeText(audioMimeSidecar(name), song.optString("audio_mime", "audio/mpeg"));
        upsertLocalSong(song);
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
        emitImport(kind, status, message, "");
    }

    private void emitImport(String kind, String status, String message, String songName) {
        try {
            JSONObject detail = new JSONObject();
            detail.put("channel", "import");
            detail.put("kind", kind);
            detail.put("status", status);
            detail.put("progress", "done".equals(status) ? 100 : 0);
            detail.put("message", message);
            detail.put("song_name", songName == null ? "" : songName);
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
        return httpRequest(method, urlText, body, extraHeaders, 10000, 120000);
    }

    private HttpResult httpRequest(String method, String urlText, String body, Map<String, String> extraHeaders, int connectTimeoutMs, int readTimeoutMs) throws IOException {
        HttpURLConnection connection = (HttpURLConnection) new URL(urlText).openConnection();
        connection.setConnectTimeout(connectTimeoutMs);
        connection.setReadTimeout(readTimeoutMs);
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

    private byte[] httpGetSearchBytes(String urlText) throws IOException {
        return httpGetSearchBytes(urlText, null);
    }

    private byte[] httpGetSearchBytes(String urlText, Map<String, String> headers) throws IOException {
        return httpRequest("GET", urlText, null, headers, SEARCH_TIMEOUT_MS, SEARCH_TIMEOUT_MS).bytes;
    }

    private Map<String, String> qqHeaders() {
        Map<String, String> headers = new LinkedHashMap<>();
        headers.put("Referer", "https://y.qq.com/");
        return headers;
    }

    private Map<String, String> neteaseHeaders() {
        Map<String, String> headers = new LinkedHashMap<>();
        headers.put("Referer", "https://music.163.com/");
        return headers;
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

    private File jobsFile() {
        return new File(cacheDir("jobs"), "lyrics_jobs.json");
    }

    private File songJsonFile(String name) {
        return new File(cacheDir("songs"), safeName(name) + ".json");
    }

    private File workspaceFile(String name) {
        return new File(cacheDir("workspaces"), safeName(cleanSongName(name)) + ".lyrics_source.json");
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
