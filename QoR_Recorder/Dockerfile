# =========================================================================
# QoR Recorder - Docker 镜像构建文件
#
# 构建命令:
#   docker build -t qor_recorder:latest .
#
# 运行命令:
#   docker run -d -p 5000:5000 \
#       -v ./data:/app/data \
#       -e PORT=5000 \
#       qor_recorder:latest
#
# 使用 Docker Compose (推荐):
#   docker-compose up -d
# =========================================================================

# 使用 Python 官方基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建必要目录
RUN mkdir -p uploads backups static/vendor data

# 下载 echarts（如果静态目录不存在）
RUN if [ ! -f static/vendor/echarts.min.js ]; then \
        curl -sSL https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js \
        -o static/vendor/echarts.min.js; \
    fi

# 设置环境变量
ENV FLASK_APP=app.py \
    FLASK_ENV=production \
    HOST=0.0.0.0 \
    PORT=5000 \
    DEBUG=0

# 暴露端口
EXPOSE 5000

# 健康检查
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# 启动命令
CMD ["python", "app.py"]
