# ─────────────────────────────────────────────────────────────
# 前端镜像：多阶段构建
#   builder 阶段：Node 装依赖 + 构建静态产物（dist/）
#   runtime 阶段：只留 nginx + 产物 → 镜像小、攻击面小
# 生产形态：nginx 托管静态文件，并把 /api 反代到后端容器（见 nginx.conf）
# ─────────────────────────────────────────────────────────────

# ── 阶段 1：构建 ──
FROM node:20-alpine AS builder
WORKDIR /app

# 国内构建走 npm 镜像，避免拉包超时（可按需改回官方源）
RUN npm config set registry https://registry.npmmirror.com

# 先只拷依赖清单：依赖没变时这一层能命中缓存，不必每次重装
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# 再拷源码并构建（package.json 的 build = tsc -b && vite build）
COPY . .
RUN npm run build

# ── 阶段 2：运行 ──
FROM nginx:1.27-alpine AS runtime

# 静态产物
COPY --from=builder /app/dist /usr/share/nginx/html

# nginx 站点配置（含 SSE 不缓冲的关键设置）
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
