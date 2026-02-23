import streamlit as st
import os
import json
import shutil
import librosa
import numpy as np
import soundfile as sf
import streamlit.components.v1 as components
import re
import base64
import mimetypes

# --- 常量定义 ---
SONG_DIR = "songs"
ARCHIVE_DIR = "songs_archived"
DB_PATH = "song_db.json"
STATIC_DIR = "static" 
os.makedirs(SONG_DIR, exist_ok=True)
os.makedirs(ARCHIVE_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

# --- 核心功能函数 ---

def sanitize_filename(filename):
    return re.sub(r'[\\/*?:"<>|]', "_", filename)

def load_db():
    if os.path.exists(DB_PATH):
        with open(DB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_db(db_data):
    with open(DB_PATH, 'w', encoding='utf-8') as f:
        json.dump(db_data, f, indent=2, ensure_ascii=False)

@st.cache_data
def find_available_songs(directory):
    songs = {}
    audio_extensions = ['.mp3', '.wav', '.flac', '.m4a']
    for filename in os.listdir(directory):
        basename, extension = os.path.splitext(filename)
        if extension.lower() in audio_extensions and not basename.startswith("temp_"):
            json_path = os.path.join(directory, basename + ".json")
            if os.path.exists(json_path):
                songs[basename] = { "audio_path": os.path.join(directory, filename), "lyrics_path": json_path }
    return songs

@st.cache_data
def process_pitch(_audio_path, n_steps):
    y, sr = librosa.load(_audio_path, sr=None)
    y_shifted = librosa.effects.pitch_shift(y=y, sr=sr, n_steps=float(n_steps))
    
    sanitized_base = sanitize_filename(os.path.splitext(os.path.basename(_audio_path))[0])
    temp_filename = f"temp_{sanitized_base}_{n_steps}.wav"
    temp_filepath = os.path.join(STATIC_DIR, temp_filename)
    sf.write(temp_filepath, y_shifted, sr)
    return temp_filepath

# --- 主应用 ---
st.set_page_config(layout="wide", initial_sidebar_state="expanded")

if 'selected_song' not in st.session_state:
    st.session_state.selected_song = None

all_songs = find_available_songs(SONG_DIR)
song_db = load_db()

# --- 侧边栏控制中心 ---
with st.sidebar:
    st.title("练歌房")
    

    st.header("曲库")
    filter_status = st.radio("筛选", ("全部", "已学会", "未学会"), horizontal=True, label_visibility="collapsed")
    
    filtered_song_names = [name for name in all_songs.keys() if (filter_status == "全部" or (filter_status == "已学会" and song_db.get(name, {}).get('learned', False)) or (filter_status == "未学会" and not song_db.get(name, {}).get('learned', False)))]

    try:
        current_index = filtered_song_names.index(st.session_state.selected_song) if st.session_state.selected_song in filtered_song_names else 0
    except (ValueError, TypeError):
        current_index = 0

    selected_song_name_from_box = st.selectbox("选择歌曲:", filtered_song_names, index=current_index, placeholder="请选择一首歌曲开始...")

    if selected_song_name_from_box and selected_song_name_from_box != st.session_state.selected_song:
        # 在切换歌曲的时候，清理掉旧的临时文件
        files_in_static = os.listdir(STATIC_DIR)
        for f in files_in_static:
            if f.startswith("temp_"):
                os.remove(os.path.join(STATIC_DIR, f))

        st.session_state.selected_song = selected_song_name_from_box
        st.rerun()

    if st.session_state.selected_song:
        
        selected_song_name = st.session_state.selected_song
        song_files = all_songs[selected_song_name]
        song_info = song_db.setdefault(selected_song_name, {})
        
        st.divider()
        st.subheader(f"🎵 {selected_song_name}")

        slider_key = f"slider_{selected_song_name}"
        default_key = song_info.get('saved_key', 0)

        if slider_key not in st.session_state:
            st.session_state[slider_key] = default_key
        
        key_shift = st.slider("实时升降调 (Key)", -12, 12, key=slider_key)

        audio_src_url = ""
        if key_shift == 0:
            # 对于原调，我们把歌曲文件复制到 static 目录，然后生成它的URL
            with st.spinner("准备音频..."):
                original_audio_path = song_files['audio_path']
                audio_filename = os.path.basename(original_audio_path)
                static_audio_path = os.path.join(STATIC_DIR, audio_filename)
                
                # 为了效率，只在 static 目录里没有这个文件时才复制
                if not os.path.exists(static_audio_path):
                    shutil.copy(original_audio_path, static_audio_path)
                
                # 生成浏览器可以访问的URL
                audio_src_url = f"/static/{audio_filename}"
        else:
            # 对于变调，process_pitch 本来就会在 static 目录生成文件，我们直接用它的路径
            with st.spinner(f"处理变调 ({key_shift:+} key)..."):
                temp_audio_path = process_pitch(song_files['audio_path'], key_shift)
                # 直接从返回的路径里提取文件名，生成URL
                audio_src_url = f"/static/{os.path.basename(temp_audio_path)}"
        
        # 把生成的 URL 存到 session_state 里
        st.session_state['audio_src_url'] = audio_src_url

        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 设为默认Key", use_container_width=True):
                song_info['saved_key'] = key_shift; save_db(song_db)
                st.toast(f"已将默认Key设为 {key_shift}！")
        with col2:
            def reset_key_callback(): st.session_state[slider_key] = 0
            st.button("🔄 还原原Key", on_click=reset_key_callback, use_container_width=True)
        
        with st.expander("设置 & 备注", expanded=True):
            display_mode = st.selectbox("歌词显示模式:", ("原文 + 译文", "仅原文", "仅译文"), key=f"mode_{selected_song_name}")
            new_range = st.text_input("音域备注:", value=song_info.get("range", ""), key=f"range_{selected_song_name}")
            new_learned = st.checkbox("已学会", value=song_info.get("learned", False), key=f"learned_{selected_song_name}")
            if st.button("📝 编辑歌词注音", use_container_width=True):
                            st.session_state.edit_mode = True
                            st.rerun() # 点击后立刻刷新，进入编辑模式
            if (new_range != song_info.get("range", "") or new_learned != song_info.get("learned", False)):
                song_info['range'] = new_range; song_info['learned'] = new_learned; save_db(song_db)
                st.toast("备注已保存!", icon="✔️")

            if st.button("🗑️ 删除这首歌", use_container_width=True, type="secondary"):
                st.session_state.confirm_delete = True

        if 'confirm_delete' in st.session_state and st.session_state.confirm_delete:
            st.warning(f"确定要删除 **{selected_song_name}** 吗？", icon="⚠️")
            c1, c2 = st.columns(2)
            if c1.button("确认删除", type="primary"):
                shutil.move(song_files['audio_path'], ARCHIVE_DIR)
                shutil.move(song_files['lyrics_path'], ARCHIVE_DIR)
                song_db.pop(selected_song_name, None); save_db(song_db)
                st.session_state.confirm_delete = False; st.session_state.selected_song = None
                st.cache_data.clear(); st.rerun()
            if c2.button("取消"):
                st.session_state.confirm_delete = False; st.rerun()

    st.divider()
    with st.expander("➕ 添加新歌曲"):
        uploaded_files = st.file_uploader("将同名的音频和.json文件一起拖到这里", accept_multiple_files=True, key="song_uploader")
        if uploaded_files:
            for f in uploaded_files:
                with open(os.path.join(SONG_DIR, f.name), "wb") as out_file: out_file.write(f.getvalue())
                st.success(f"✅ 已添加: {f.name}")
            
            # 清理缓存，让曲库能刷新
            st.cache_data.clear()
            # 清空上传组件里的文件列表，防止重复处理
            st.session_state.song_uploader = [] 
            # 删掉 st.rerun()，让 Streamlit 自然刷新

# --- 主界面 ---
if st.session_state.selected_song and st.session_state.get('audio_src_url'):    # ... 在 if st.session_state.selected_song ... 之后
# --- 新增的“黑魔法” ---
    # 我们从外面用CSS把组件的框框强行拉到和窗口一样高
    st.markdown("""
        <style>
            iframe[title="st.iframe"] {
                /* 用 calc 函数，从100vh里减去一个估算值 */
                /* 这个 4rem 大约等于64像素，差不多是顶部标题栏和那个“编辑”链接的高度之和 */
                height: 85vh;
            }
        </style>
        """, unsafe_allow_html=True)
    # 初始化编辑模式的状态
    if 'edit_mode' not in st.session_state:
        st.session_state.edit_mode = False

    # 添加一个编辑按钮
        # --- 新的编辑按钮样式和逻辑 ---
    # 定义一个CSS样式，让链接看起来像普通文本
    edit_link_style = """
        <style>
            a.edit-link {
                color: #888 !important;
                text-decoration: underline !important;
                font-size: 0.9em;
                cursor: pointer;
            }
            a.edit-link:hover {
                color: #000 !important;
            }
        </style>
    """
    # 显示这个链接，点击它会改变URL的参数，从而触发页面刷新和逻辑判断
    #st.markdown(edit_link_style + '<a href="?edit=true" target="_self" class="edit-link">编辑歌词注音...</a>', unsafe_allow_html=True)
    
    # --- 逻辑判断从按钮点击改成判断URL参数 ---
    if st.session_state.get("edit_mode", False):
        st.subheader(f"正在编辑: {selected_song_name}")
        
        try:
            with open(song_files['lyrics_path'], 'r', encoding='utf-8') as f:
                current_lyrics_str = json.dumps(json.load(f), indent=2, ensure_ascii=False)
            
            edited_lyrics_str = st.text_area(
                "在此修改歌词JSON内容 (请注意保持JSON格式正确！)",
                value=current_lyrics_str,
                height=600
            )

            c1, c2 = st.columns(2)
            if c1.button("💾 保存修改", type="primary"):
                try:
                    # ... 保存逻辑 ...
                    st.success("歌词已保存！")
                    st.cache_data.clear()
                    st.session_state.edit_mode = False # 退出编辑模式
                    st.rerun()
                except json.JSONDecodeError:
                    st.error("保存失败！JSON格式错误，请检查。")
            
            if c2.button("❌ 取消"):
                st.session_state.edit_mode = False # 退出编辑模式
                st.rerun()

        except Exception as e:
            st.error(f"读取歌词文件时出错: {e}")


    else: # 如果不在编辑模式，就正常显示播放器和歌词
        # ... 这里接上你原来显示 components.html 的那一大段代码 ...
        selected_song_name = st.session_state.selected_song
        song_files = all_songs[selected_song_name]
        with open(song_files['lyrics_path'], 'r', encoding='utf-8') as f:
            lyrics_data = json.load(f)

        display_mode = st.session_state.get(f"mode_{selected_song_name}", "原文 + 译文")
        
        lines_html = []
        # 我们用 enumerate 来拿到索引，方便找下一句歌词的时间
        for i, line in enumerate(lyrics_data):
            original_html = line.get('original_html', '')
            translation_text = line.get('translation', '')
            display_text = ""
            if display_mode == "仅原文": display_text = original_html
            elif display_mode == "仅译文": display_text = translation_text
            else: display_text = f"{original_html}<br><small style='color: #999;'>{translation_text}</small>"
            
            start_time = line["time"]
            # 下一句歌词的开始时间，就是当前这句的结束时间。最后一句就给个超大的数。
            end_time = lyrics_data[i + 1]["time"] if i + 1 < len(lyrics_data) else 99999

            # 在 div 里加上 data-start-time 和 data-end-time
            line_html = f'<div class="lyric-line" data-start-time="{start_time}" data-end-time="{end_time}" onclick="seekAudio({start_time})">{display_text}</div>'
            lines_html.append(line_html)

        lyrics_block = "".join(lines_html)
        audio_src = st.session_state['audio_src_url']
        
        # --- HTML 内容大改版 ---
        # ...
        # --- HTML 内容最终修正版 ---
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Lyrics Player</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <script src="https://cdn.jsdelivr.net/npm/streamlit-component-lib@2/dist/streamlit-component-lib.js"></script>
            <style>
                html, body {{ 
                    margin: 0; padding: 0; height: 100%; width: 100%; 
                    font-family: sans-serif; overflow: hidden; 
                }}
                .app-container {{
                    display: grid;
                    grid-template-rows: 1fr auto; 
                    height: 100%;
                    background-color: #fff;
                }}
                .lyric-container {{
                    overflow-y: auto;
                    padding: 10px;
                }}
                .lyric-line {{ padding: 8px 12px; margin: 4px 0; border-radius: 8px; cursor: pointer; transition: background-color 0.2s; line-height: 2; }}
                .lyric-line:hover {{ background-color: #f0f2f6; }}
                ruby rt {{ font-size: 0.7em; color: #B0B0B0; }}
                .active-lyric {{ background-color: #e0e0e0; }}
                
                .audio-player-desktop {{ 
                    padding: 10px; 
                    background-color: rgba(255, 255, 255, 0.95); 
                    box-shadow: 0 -2px 10px rgba(0,0,0,0.1); 
                    z-index: 100; 
                }}
                .audio-player-desktop audio {{ width: 100%; }}

                .mobile-controls-container {{ display: none; position: fixed; bottom: 30px; right: 20px; z-index: 101; align-items: center; gap: 15px; }}
                .mobile-player-button, .speed-toggle-button {{ border-radius: 50%; box-shadow: 0 4px 12px rgba(0,0,0,0.2); color: white; cursor: pointer; user-select: none; display: flex; align-items: center; justify-content: center; }}
                .mobile-player-button {{ width: 60px; height: 60px; background-color: rgba(50, 50, 50, 0.7); font-size: 24px; }}
                .speed-toggle-button {{ width: 40px; height: 40px; background-color: rgba(80, 80, 80, 0.6); font-size: 14px; }}
                @media (max-width: 600px) {{
                    .audio-player-desktop {{ display: none; }}
                    .mobile-controls-container {{ display: flex; }}
                }}
            </style>
        </head>
        <body>
            <div class="app-container">
                <div class="lyric-container" id="lyric-container">{lyrics_block}</div>
                {'''<!-- 看这里！src 直接等于我们生成的 URL -->'''}
                <div class="audio-player-desktop"><audio id="main-audio" controls src="{audio_src}"></audio></div>
            </div>
            
            <div class="mobile-controls-container">
                <div id="speed-toggle" class="speed-toggle-button">x1</div>
                <div id="mobile-player" class="mobile-player-button">▶</div>
            </div>

            <script>
                window.addEventListener('load', function() {{
                    // 所有和高度计算相关的JS都删掉了，这里是纯业务逻辑
                    const audioPlayer = document.getElementById('main-audio');
                    const mobilePlayer = document.getElementById('mobile-player');
                    const speedToggle = document.getElementById('speed-toggle');
                    const lyricLines = document.querySelectorAll('.lyric-line');
                    let currentActiveLine = null;
                    
                    // 这里所有的JS函数和对象里的括号都换成双括号了
                    const togglePlayPause = () => {{ audioPlayer.paused ? audioPlayer.play() : audioPlayer.pause(); }};
                    
                    // seekAudio这个函数在你原来的代码里没有，但是我加上了，这样点击歌词才能跳转
                    const seekAudio = (time) => {{ if (audioPlayer) {{ audioPlayer.currentTime = time; audioPlayer.play(); }} }};

                    const highlightAndScroll = (line) => {{
                        if (line !== currentActiveLine) {{
                            if (currentActiveLine) currentActiveLine.classList.remove('active-lyric');
                            line.classList.add('active-lyric');
                            currentActiveLine = line;
                            // 之前就是这里错了！现在改好了
                            line.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                        }}
                    }};

                    audioPlayer.addEventListener('play', () => {{ mobilePlayer.innerHTML = '❚❚'; }});
                    audioPlayer.addEventListener('pause', () => {{ mobilePlayer.innerHTML = '▶'; }});
                    audioPlayer.addEventListener('timeupdate', () => {{
                        const currentTime = audioPlayer.currentTime;
                        for (const line of lyricLines) {{
                            if (currentTime >= parseFloat(line.dataset.startTime) && currentTime < parseFloat(line.dataset.endTime)) {{
                                highlightAndScroll(line);
                                return;
                            }}
                        }}
                    }});

                    mobilePlayer.addEventListener('click', togglePlayPause);
                    speedToggle.addEventListener('click', (e) => {{
                        e.stopPropagation();
                        if (audioPlayer.playbackRate === 1.0) {{ 
                            audioPlayer.playbackRate = 0.75; 
                            speedToggle.innerText = 'x0.75'; 
                        }} else {{ 
                            audioPlayer.playbackRate = 1.0; 
                            speedToggle.innerText = 'x1'; 
                        }}
                    }});

                    document.addEventListener('keydown', (e) => {{
                        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
                        if (e.code === 'Space') {{ e.preventDefault(); togglePlayPause(); }}
                        if (e.code === 'ArrowDown' && currentActiveLine) {{
                            const nextLine = currentActiveLine.nextElementSibling;
                            if (nextLine) seekAudio(parseFloat(nextLine.dataset.startTime));
                        }}
                        if (e.code === 'ArrowUp' && currentActiveLine) {{
                            const prevLine = currentActiveLine.previousElementSibling;
                            if (prevLine) seekAudio(parseFloat(prevLine.dataset.startTime));
                        }}
                    }});
                }});
            </script>
        </body>
        </html>
        """
        # ...
        
        # --- 组件调用也简化 ---
        # 不需要 height，也不需要 scrolling=True
        components.html(html_content)

# ...
elif st.session_state.selected_song:
    st.info("音频正在加载中，请稍候...")
else:
    st.header("欢迎使用练歌房！")
    st.info("请从左侧的曲库中选择一首歌曲开始，或者添加新歌。")
