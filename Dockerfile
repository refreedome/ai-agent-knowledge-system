# ============================================================
# 阶段一：构建阶段
# ============================================================
FROM python:3.12-slim AS builder

WORKDIR /app

# 安装系统依赖（OCR 需要 pytesseract，jieba 需要编译）
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

# 只复制依赖文件，利用 Docker 缓存层
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ============================================================
# 阶段二：运行阶段（多阶段构建，减小镜像体积）
# ============================================================
FROM python:3.12-slim

WORKDIR /app

# 从 builder 阶段复制已安装的包
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /usr/bin/tesseract /usr/bin/tesseract
COPY --from=builder /usr/share/tesseract-ocr /usr/share/tesseract-ocr
COPY --from=builder /usr/lib/x86_64-linux-gnu /usr/lib/x86_64-linux-gnu

# 复制项目代码
COPY . .

# 确保 API 密钥通过环境变量传入，不写在镜像里
ENV DASHSCOPE_API_KEY=${DASHSCOPE_API_KEY}

# 暴露 API 端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
# ============================================================
# 阶段一：构建阶段
# ============================================================
FROM python:3.12-slim AS builder

WORKDIR /app

# 安装系统依赖（OCR 需要 pytesseract，jieba 需要编译）
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

# 只复制依赖文件，利用 Docker 缓存层
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ============================================================
# 阶段二：运行阶段（多阶段构建，减小镜像体积）
# ============================================================
FROM python:3.12-slim

WORKDIR /app

# 从 builder 阶段复制已安装的包
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /usr/bin/tesseract /usr/bin/tesseract
COPY --from=builder /usr/share/tesseract-ocr /usr/share/tesseract-ocr
COPY --from=builder /usr/lib/x86_64-linux-gnu /usr/lib/x86_64-linux-gnu

# 复制项目代码
COPY . .

# 确保 API 密钥通过环境变量传入，不写在镜像里
ENV DASHSCOPE_API_KEY=${DASHSCOPE_API_KEY}

# 暴露 API 端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
