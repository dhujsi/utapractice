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

def get_audio_base64(file_path):
    try:
        with open(file_path, "rb") as f:
            data = f.read()
        b64 = base64.b64encode(data).decode()
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type is None:
            if file_path.endswith(('.mp3', '.m4a')):
                mime_type = 'audio/mpeg'
            elif file_path.endswith('.wav'):
                mime_type = 'audio/wav'
            elif file_path.endswith('.flac'):
                 mime_type = 'audio/flac'
            else:
                mime_type = 'application/octet-stream'
        return f"data:{mime_type};base64,{b64}"
    except FileNotFoundError:
        return None

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

        audio_b64_data = ""
        if key_shift == 0:
            with st.spinner("加载音频..."):
                audio_b64_data = get_audio_base64(song_files['audio_path'])
        else:
            with st.spinner(f"处理变调 ({key_shift:+} key)..."):
                temp_audio_path = process_pitch(song_files['audio_path'], key_shift)
                audio_b64_data = get_audio_base64(temp_audio_path)
        
        st.session_state['audio_b64_data'] = audio_b64_data

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
            lyric_align = st.radio(
                            "歌词对齐:",
                            ("居左", "居中", "居右"),
                            horizontal=True,
                            key=f"align_{selected_song_name}",
                            # 如果之前没设置过，就默认居中
                            index=1 
                        )
            new_range = st.text_input("音域备注:", value=song_info.get("range", ""), key=f"range_{selected_song_name}")
            new_learned = st.checkbox("已学会", value=song_info.get("learned", False), key=f"learned_{selected_song_name}")

            if (new_range != song_info.get("range", "") or new_learned != song_info.get("learned", False)):
                song_info['range'] = new_range; song_info['learned'] = new_learned; save_db(song_db)
                st.toast("备注已保存!", icon="✔️")
    # 初始化编辑模式的状态
            if 'edit_mode' not in st.session_state:
                st.session_state.edit_mode = False

            # 添加一个编辑按钮
            if st.button("📝 编辑歌词", use_container_width=True):
                st.session_state.edit_mode = not st.session_state.edit_mode # 点一下切换编辑/查看模式
                st.rerun()

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
if st.session_state.selected_song and st.session_state.get('audio_b64_data'):
    # ... 在 if st.session_state.selected_song ... 之后

    # 根据是否在编辑模式，决定显示什么
    if st.session_state.edit_mode:
        st.subheader(f"正在编辑: {selected_song_name}")
        
        try:
            with open(song_files['lyrics_path'], 'r', encoding='utf-8') as f:
                # 把整个json文件内容读出来，格式化一下，放到文本框里
                current_lyrics_str = json.dumps(json.load(f), indent=2, ensure_ascii=False)
            
            edited_lyrics_str = st.text_area(
                "在此修改歌词JSON内容 (请注意保持JSON格式正确！)",
                value=current_lyrics_str,
                height=600
            )

            c1, c2 = st.columns(2)
            if c1.button("💾 保存修改", type="primary"):
                try:
                    # 尝试解析修改后的文本，看看是不是合法的JSON
                    new_lyrics_data = json.loads(edited_lyrics_str)
                    # 如果合法，就写回文件
                    with open(song_files['lyrics_path'], 'w', encoding='utf-8') as f:
                        json.dump(new_lyrics_data, f, indent=2, ensure_ascii=False)
                    
                    st.success("歌词已保存！")
                    st.cache_data.clear() # 清除缓存，让下次显示时加载新内容
                    st.session_state.edit_mode = False # 退出编辑模式
                    st.rerun()
                except json.JSONDecodeError:
                    st.error("保存失败！你修改后的内容不是一个有效的JSON格式，请检查。")
            
            if c2.button("❌ 取消"):
                st.session_state.edit_mode = False
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
        audio_src = st.session_state['audio_b64_data']
        
        # --- 这里是修改点 ---
        # 我把那个错误的 key 参数删掉了
            # --- 这里是修改点 ---
        # 把整个 html_content 变量的内容替换成下面的
          # --- 这里是修改点 ---
        # 把整个 html_content 变量的内容替换成下面的
        align_class_map = {"居左": "align-left", "居中": "align-center", "居右": "align-right"}
        css_align_class = align_class_map.get(lyric_align, "align-center")
        html_content = f"""
    <style>
        html, body {{
            height: 100%; margin: 0; padding: 0;
            overflow: hidden; display: flex;
            flex-direction: column; font-family: sans-serif;
        }}
        .lyric-container {{
            flex-grow: 1; overflow-y: auto; padding: 10px;
        }}
        /* --- 核心修改在这里 --- */
        /* 我们不再直接给 .lyric-line 设置 text-align */
        .lyric-line {{
            padding: 8px 12px; margin: 4px 0; border-radius: 8px;
            cursor: pointer; transition: background-color 0.2s, color 0.2s;
            line-height: 2;
        }}
        /* 而是根据父容器的 class 来决定对齐方式 */
        .lyric-container.align-left .lyric-line {{ text-align: left; }}
        .lyric-container.align-center .lyric-line {{ text-align: center; }}
        .lyric-container.align-right .lyric-line {{ text-align: right; }}

        .lyric-line:hover {{ background-color: #f0f2f6; }}
        ruby rt {{ font-size: 0.7em; color: #B0B0B0; }}
        .active-lyric {{ background-color: #e0e0e0; color: #000; }}
        .audio-player-desktop {{
            flex-shrink: 0; padding: 10px;
            background-color: rgba(255, 255, 255, 0.8);
            backdrop-filter: blur(10px);
            border-top: 1px solid #eee;
        }}
        .audio-player-desktop audio {{ width: 100%; }}
        .mobile-player-container {{
            display: none; position: fixed; bottom: 30px; right: 20px;
            z-index: 101; align-items: flex-end; gap: 10px;
        }}
        .audio-player-mobile {{
            width: 60px; height: 60px; background-color: rgba(50, 50, 50, 0.7);
            border-radius: 50%; box-shadow: 0 4px 12px rgba(0,0,0,0.2);
            color: white; display: flex; align-items: center; justify-content: center;
            font-size: 24px; cursor: pointer; user-select: none;
        }}
        #speed-toggle-button {{
            width: 40px; height: 40px; background-color: rgba(80, 80, 80, 0.7);
            border-radius: 50%; color: white; display: flex; align-items: center;
            justify-content: center; font-size: 12px; cursor: pointer; user-select: none;
        }}
        @media (max-width: 600px) {{
            .audio-player-desktop {{ display: none; }}
            .mobile-player-container {{ display: flex; }}
            .lyric-container {{ padding-bottom: 80px; }}
        }}
    </style>

    <!-- 把我们生成的 class 加到这个 div 上 -->
    <div class="lyric-container {css_align_class}" id="lyric-container">{lyrics_block}</div>

    <div class="audio-player-desktop">
        <audio id="main-audio" controls src="{audio_src}"></audio>
    </div>
    <div class="mobile-player-container">
        <div id="speed-toggle-button">1.0x</div>
        <div class="audio-player-mobile" id="mobile-player">
            <div id="mobile-player-icon">▶</div>
        </div>
    </div>

    <script>
        // script部分不用动
        const audioPlayer = document.getElementById('main-audio');
        const mobilePlayer = document.getElementById('mobile-player');
        const mobilePlayerIcon = document.getElementById('mobile-player-icon');
        const speedToggleButton = document.getElementById('speed-toggle-button');
        const lyricContainer = document.getElementById('lyric-container');
        const lyricLines = lyricContainer.querySelectorAll('.lyric-line');
        let currentActiveLine = null;
        function playAudio() {{ audioPlayer.play(); }}
        function pauseAudio() {{ audioPlayer.pause(); }}
        function togglePlayPause() {{ audioPlayer.paused ? playAudio() : pauseAudio(); }}
        function seekAudio(time) {{ if (audioPlayer) {{ audioPlayer.currentTime = time; playAudio(); }} }}
        function highlightAndScroll(line) {{
            if (line !== currentActiveLine) {{
                if (currentActiveLine) currentActiveLine.classList.remove('active-lyric');
                line.classList.add('active-lyric');
                currentActiveLine = line;
                line.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
            }}
        }}
        audioPlayer.addEventListener('timeupdate', function() {{
            const currentTime = audioPlayer.currentTime;
            for (const line of lyricLines) {{
                const startTime = parseFloat(line.dataset.startTime);
                const endTime = parseFloat(line.dataset.endTime);
                if (currentTime >= startTime && currentTime < endTime) {{
                    highlightAndScroll(line);
                    return;
                }}
            }}
            if (currentActiveLine) {{ currentActiveLine.classList.remove('active-lyric'); currentActiveLine = null; }}
        }});
        audioPlayer.addEventListener('play', () => mobilePlayerIcon.innerHTML = '❚❚');
        audioPlayer.addEventListener('pause', () => mobilePlayerIcon.innerHTML = '▶');
        mobilePlayer.addEventListener('click', togglePlayPause);
        speedToggleButton.addEventListener('click', function() {{
            const currentRate = audioPlayer.playbackRate;
            let newRate = 1.0;
            if (currentRate === 1.0) {{ newRate = 0.75; }}
            else if (currentRate === 0.75) {{ newRate = 0.5; }}
            else {{ newRate = 1.0; }}
            audioPlayer.playbackRate = newRate;
            speedToggleButton.innerText = newRate.toFixed(2).replace('.00', '') + 'x';
        }});
        document.addEventListener('keydown', function(e) {{
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
            if (e.code === 'Space') {{ e.preventDefault(); togglePlayPause(); }}
            if (e.code === 'ArrowDown' && currentActiveLine) {{
                const nextLine = currentActiveLine.nextElementSibling;
                if (nextLine && nextLine.classList.contains('lyric-line')) seekAudio(parseFloat(nextLine.dataset.startTime));
            }}
            if (e.code === 'ArrowUp' && currentActiveLine) {{
                const prevLine = currentActiveLine.previousElementSibling;
                if (prevLine && prevLine.classList.contains('lyric-line')) seekAudio(parseFloat(prevLine.dataset.startTime));
            }}
        }});
    </script>
    """

        st.markdown("""
        <style>
            iframe[title="streamlit.components.v1.html"] {
                height: 85vh !important;
            }
        </style>
        """, unsafe_allow_html=True)
       
        components.html(html_content, height=740, scrolling=True) # height 和 scrolling 在这里影响不大，但留着也行

elif st.session_state.selected_song:
    st.info("音频正在加载中，请稍候...")
else:
    st.header("欢迎使用练歌房！")
    st.info("请从左侧的曲库中选择一首歌曲开始，或者添加新歌。")
