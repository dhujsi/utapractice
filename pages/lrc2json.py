import streamlit as st
import os
import json
import re
from openai import OpenAI
import time

# 导入我们需要的特定事件类型
from openai.types.responses import ResponseCreatedEvent, ResponseOutputMessage

# --- 固定API Key ---
API_KEY = "2978a7fa-db47-496f-98b0-266b7a8582a4"
# --- 使用你指定的新模型 ---
MODEL_ID = "ep-20260208224806-h8zp7"

# --- AI Client Setup ---
try:
    CLIENT = OpenAI(
        base_url='https://ark.cn-beijing.volces.com/api/v3',
        api_key=API_KEY
    )
except Exception as e:
    st.error(f"初始化AI客户端时出错: {e}")
    st.stop()


# --- Helper Functions (强化版) ---
def build_generation_prompt(lrc_content, ruby_content):
    """第一步：构建生成JSON的指令（最终强化版）"""
    return f"""
你是一个专业的歌词处理工具。你的任务是根据我提供的LRC时间和带注音的歌词文本，生成一个严格的JSON数组。

[LRC文件内容]
{lrc_content}

[带注音的歌词文本]
{ruby_content}

[输出要求 - 必须严格遵守！]
1. **必须使用我提供的文本内容**，绝对禁止使用任何你自己编造的示例文字（如“这是第一句字幕文本”）。
2. 格式为一个JSON数组，每个元素是一个包含 "time", "original_html", "translation" 三个字段的对象。
3. "time" 字段必须是纯数字（例如：27.800），代表歌词开始的秒数。**绝对不能是 "00:27.800" 这样的字符串格式！**
4. "original_html" 字段需要将 "漢字[かんじ]" 格式转为 "<ruby>漢字<rt>かんじ</rt></ruby>" 的HTML。
5. **只输出纯净的JSON数组**，不要包含任何解释或```json标记。
"""

def build_verification_prompt(raw_ai_output):
    """第二步：构建校验和修正JSON的指令（最终强化版）"""
    return f"""
你是一个严格的数据格式校验员。下面的文本是上一步AI生成的初步结果。

[待校验文本]
{raw_ai_output}

[你的任务 - 必须严格遵守！]
1. 检查该文本是否是一个完美、纯净、语法正确的JSON数组。
2. **特别检查 "time" 字段的值是否为纯数字（例如：33.450），如果不是（例如："00:33.450"），请将其修正为纯数字秒数。**
3. 如果它包含了任何非JSON内容或存在语法错误，请将其修正。
4. **你的最终输出必须且只能是一个干净、有效的JSON数组。**
"""

def extract_json_from_response(text):
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        return match.group(0)
    return text

# --- Streamlit App ---
st.set_page_config(layout="wide")
st.title("歌词处理与校验工具 (流式+计时版)")
st.markdown("---")

# --- Main App Body ---
st.subheader("1. 提供歌词数据")
col1, col2 = st.columns(2)
with col1:
    lrc_file = st.file_uploader("上传LRC文件", type=['lrc'])
with col2:
    ruby_text_input = st.text_area(
        "粘贴带注音的歌词文本", 
        height=300, 
        placeholder="在这里粘贴从别处复制的、带注音的歌词全文，例如：\n刃渡り[はわたり]数[すう]センチの不信感[ふしんかん]が..."
    )

if lrc_file and ruby_text_input:
    if st.button("2. 开始流式处理与校验", use_container_width=True, type="primary"):
        try:
            lrc_content = lrc_file.getvalue().decode('utf-8-sig', errors='ignore')
            ruby_content = ruby_text_input
            
            # --- Step 1: Streaming Generation with Timer ---
            st.subheader("实时生成预览")
            placeholder = st.empty()
            full_response = ""
            
            gen_prompt = build_generation_prompt(lrc_content, ruby_content)
            
            start_gen_time = time.time()
            gen_stream = CLIENT.responses.create(
                model=MODEL_ID,
                input=[{"role": "user", "content": gen_prompt}],
                stream=True
            )
            
            with gen_stream:
                for chunk in gen_stream:
                    if isinstance(chunk, ResponseOutputMessage):
                        if chunk.content and chunk.content[0].text:
                            chunk_text = chunk.content[0].text
                            full_response += chunk_text
                            placeholder.markdown(f"```json\n{full_response}\n```")
            
            gen_duration = time.time() - start_gen_time
            st.success(f"✅ 初版生成完成！(耗时: {gen_duration:.2f} 秒)")
            
            # --- Step 2: Verification with Timer ---
            with st.spinner("第2步：请求AI校验并修正格式..."):
                ver_prompt = build_verification_prompt(full_response)
                
                start_ver_time = time.time()
                ver_response = CLIENT.responses.create(
                    model=MODEL_ID,
                    input=[{"role": "user", "content": ver_prompt}]
                )
                
                final_output = ver_response.output[0].content[0].text
                st.session_state.processed_json_str = extract_json_from_response(final_output)

            ver_duration = time.time() - start_ver_time
            st.success(f"✅ 格式校验完成！(耗时: {ver_duration:.2f} 秒)")

            # --- Step 3: Preview and Save ---
            st.markdown("---")
            st.subheader("3. 最终结果预览与保存")
            
            try:
                parsed_json = json.loads(st.session_state.processed_json_str)
                pretty_json = json.dumps(parsed_json, indent=2, ensure_ascii=False)
                st.code(pretty_json, language="json")

                default_filename = os.path.splitext(lrc_file.name)[0] + ".json"
                save_filename = st.text_input("保存文件名:", value=default_filename)
                
                if st.button("保存到本地", use_container_width=True, key="save_button"):
                    save_dir = "processed_lyrics"
                    os.makedirs(save_dir, exist_ok=True)
                    save_path = os.path.join(save_dir, save_filename)
                    
                    with open(save_path, 'w', encoding='utf-8') as f:
                        f.write(pretty_json)
                    
                    st.success(f"文件已成功保存到: `{save_path}`")
            
            except json.JSONDecodeError:
                st.error("AI校验后仍然不是有效的JSON格式。以下是AI最终的回复：")
                st.code(st.session_state.processed_json_str, language="text")

        except Exception as e:
            st.error(f"处理过程中出错: {e}")
            if 'processed_json_str' in st.session_state:
                del st.session_state['processed_json_str']
