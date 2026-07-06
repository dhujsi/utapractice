# APK Local Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the APK usable as a local-first app with the shared Web UI, while keeping server sync as an optional add-on.

**Architecture:** The shared Web UI continues calling `/api/...`. Flask remains the Web server implementation, and Android implements the same core API contract against app-private files. Android Bridge is used only for platform capabilities that WebView request interception cannot handle, especially file import.

**Tech Stack:** Java Android WebView, app-private file storage, shared HTML/CSS/JS assets, Node static behavior tests, Gradle debug APK build.

---

### Task 1: Document The APK Contract

**Files:**
- Create: `docs/apk-local-backend.md`
- Create: `docs/superpowers/plans/2026-07-06-apk-local-backend.md`
- Modify: `android/README.md`
- Modify: `WORKLOG.md`
- Modify: `HANDOFF.md`

- [ ] **Step 1: Write the architecture note**

Create `docs/apk-local-backend.md` describing these requirements:

- APK and Web share one UI.
- Flask and Android implement the same `/api/...` contract.
- APK local storage is the primary path.
- Server sync is optional.
- Android Bridge is reserved for platform file and permission work.

- [ ] **Step 2: Update Android README**

Change `android/README.md` so it no longer describes the APK as a read-only synced player. It must say:

- APK starts with an empty local library.
- Local import and local save work without a server.
- Server sync is optional.

- [ ] **Step 3: Update project handoff docs**

Append the same user-facing architecture decision to `WORKLOG.md` and `HANDOFF.md`.

### Task 2: Add Failing APK Contract Tests

**Files:**
- Modify: `tests/app_behavior.test.js`

- [ ] **Step 1: Add a failing static behavior test for local API writes**

Add assertions that `MainActivity.java` exposes local handlers for:

- `handleLocalPost`
- `handleMetaPost`
- `handleLyricsPost`
- `handleLyricsTextPost`
- `localSongsListJson`
- `upsertLocalSong`

Also assert it no longer globally rejects every non-GET request with the old "请在网页端执行" message.

- [ ] **Step 2: Add a failing static behavior test for Android file import bridge**

Add assertions that:

- `MainActivity.java` exposes `chooseAudioForSong` and `chooseLyricsForSong`.
- `web_static/app.js` detects `window.UtaPracticeAndroid`.
- Upload UI calls the bridge for Android file import instead of relying on multipart only.

- [ ] **Step 3: Run the test and verify RED**

Run:

```bash
node --test tests/app_behavior.test.js
```

Expected: the new tests fail because the APK local write handlers and bridge methods do not exist yet.

### Task 3: Implement Android Local API Writes

**Files:**
- Modify: `android/app/src/main/java/com/utapractice/app/MainActivity.java`

- [ ] **Step 1: Route POST requests to local handlers**

Change `handleApiRequest` so GET keeps existing cached-first behavior, while supported POST paths call `handleLocalPost(pathAndQuery, body)`.

- [ ] **Step 2: Implement local song JSON helpers**

Add helpers to:

- Read and write the local song list JSON.
- Read and write a song detail JSON file.
- Upsert a song summary and detail by song name.
- Build a safe JSON response from local files.

- [ ] **Step 3: Implement metadata saves**

Support:

```text
POST /api/songs/<name>/meta
```

Update the local song detail and song list fields for `learned`, `range`, `saved_key`, and metadata-like values already used by the UI.

- [ ] **Step 4: Implement lyrics saves**

Support:

```text
POST /api/songs/<name>/lyrics
POST /api/upload/lyrics-text
```

Write lyrics into the local song detail JSON and update list flags such as `has_lyrics` and `lyrics_type`.

- [ ] **Step 5: Run the APK contract test and verify GREEN for local writes**

Run:

```bash
node --test tests/app_behavior.test.js
```

Expected: local write contract tests pass.

### Task 4: Implement Android File Import Bridge

**Files:**
- Modify: `android/app/src/main/java/com/utapractice/app/MainActivity.java`
- Modify: `web_static/app.js`

- [ ] **Step 1: Add bridge methods**

Add `chooseAudioForSong(songName)` and `chooseLyricsForSong(songName)` to `AndroidBridge`.

- [ ] **Step 2: Add Android activity result handling**

Use Android's document picker to select audio or lyrics files, copy them into app-private storage, then upsert the matching song.

- [ ] **Step 3: Add shared UI Android path**

In `web_static/app.js`, when `window.UtaPracticeAndroid` exists, provide buttons or branch the existing upload action so Android imports files through the bridge.

- [ ] **Step 4: Run static checks**

Run:

```bash
node --test tests/app_behavior.test.js
node --check web_static/app.js
```

Expected: tests and JS syntax check pass.

### Task 5: Verify And Package

**Files:**
- Modify: `WORKLOG.md`
- Modify: `HANDOFF.md`
- Build output: `dist/utapractice-local-backend-debug.apk`

- [ ] **Step 1: Run full local verification**

Run:

```bash
node --test tests/app_behavior.test.js
node --check web_static/app.js
python3 -m py_compile web_app.py
```

Expected: all commands exit 0.

- [ ] **Step 2: Build the APK**

Run:

```bash
cd android && ANDROID_HOME=/home/er/android-sdk bash ./gradlew assembleDebug
```

Expected: Gradle exits 0 and produces `android/app/build/outputs/apk/debug/app-debug.apk`.

- [ ] **Step 3: Copy APK to dist**

Copy the debug APK to:

```text
dist/utapractice-local-backend-debug.apk
```

- [ ] **Step 4: Inspect packaged assets**

Run:

```bash
unzip -p dist/utapractice-local-backend-debug.apk assets/webapp/app.js | rg "chooseAudioForSong|chooseLyricsForSong|UtaPracticeAndroid"
```

Expected: packaged JS includes the Android local import bridge calls.

- [ ] **Step 5: Commit and push**

Run:

```bash
git status -sb
git add docs android web_static tests WORKLOG.md HANDOFF.md dist/utapractice-local-backend-debug.apk
git commit -m "完善 APK 本地后端能力"
git push
```

Expected: commit is created and pushed. If local push lacks credentials, push from fnOS using the established bundle workflow.

