# 使用一个官方的 Python 运行时作为基础镜像
FROM python:3.9-slim

# 在容器里创建一个叫 /app 的文件夹，作为我们的工作目录
WORKDIR /app

# 先把依赖清单复制进去
COPY requirements.txt ./

# 安装所有依赖，--no-cache-dir 是个好习惯，能让镜像小一点
RUN pip install --no-cache-dir -r requirements.txt

# 把当前目录下的所有文件（也就是你的Python代码、songs文件夹等）都复制到容器的 /app 目录里
COPY . .

# 告诉 Docker，容器里的 8501 端口需要被外界访问（Streamlit默认用这个端口）
EXPOSE 8501

# 定义容器启动时要执行的命令
# 把 "your_script_name.py" 换成你那个Python文件的真实名字
CMD ["streamlit", "run", "app.py"]