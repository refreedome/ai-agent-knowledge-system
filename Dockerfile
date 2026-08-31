# ============================================================
# 阶段一：构建阶段
# ============================================================
FROM python:3.12-slim AS builder

WORKDIR /app

# 安装系统依赖（OCR 需要 pytesseract，jieba 需要编译）
# 境内网络加速：apt 换清华源（海外服务器可删除本行用官方源）
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

# 只复制依赖文件，利用 Docker 缓存层
COPY requirements.txt .
# 境内网络加速：pip 走清华镜像（海外服务器可去掉 -i 参数用官方源）
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 预下载本地 Embedding 模型（FastEmbed/BGE，走 HF 国内镜像）
# 构建进镜像 → 服务器启动时无需联网下载模型，秒级就绪
# HF_HUB_DISABLE_XET=1：禁用 huggingface 新 Xet 协议（hf-mirror 不支持，会 401）
ENV HF_ENDPOINT=https://hf-mirror.com
ENV HF_HUB_DISABLE_XET=1
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-zh-v1.5')"

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
# 复制预下载的 Embedding 模型缓存（避免运行时联网下载；HF 镜像兜底）
COPY --from=builder /root/.cache /root/.cache
ENV HF_ENDPOINT=https://hf-mirror.com
ENV HF_HUB_DISABLE_XET=1

# 复制项目代码
COPY . .

# 密钥通过 docker-compose 运行时注入（.env → environment），绝不 build 进镜像层
# （docker history 可翻出镜像每一层，密钥写进镜像 = 泄露）

# 暴露 API 端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
