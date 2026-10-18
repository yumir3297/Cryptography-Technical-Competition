# 一个镜像装整套：受信端、各角色端、调用者和控制台是同一个包的不同入口。

# 页面：Vite 把 Vue 应用构建成静态资源。构建阶段带 Node，运行阶段只带产物，
# 所以 Python 运行与回归仍然不依赖 Node。
FROM node:22-slim AS page
WORKDIR /page
COPY competition/console/frontend/package.json competition/console/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY competition/console/frontend/ ./
RUN npm run build

FROM python:3.13-slim

# 全部容器同一个 uid。端钥和端 socket 都是 0600 且检查属主，读它们的进程必须是
# 同一个用户；X 回执子进程与工具子进程是从共享卷上直接读凭据的，所以受信端也得
# 读得到那两个文件。
ARG UID=1000
RUN useradd --uid "$UID" --create-home --shell /usr/sbin/nologin zjj

WORKDIR /app
COPY requirements.txt ./
COPY competition/agent/requirements.txt ./agent-requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r agent-requirements.txt

# 契约与 Schema 是运行时从仓库树里读的，所以要带上整棵树而不是一个 wheel。
COPY competition ./competition
COPY system_dev ./system_dev

# 已构建的页面落在控制台期望它出现的位置。
COPY --from=page /page/dist ./competition/console/frontend/dist

# 卷的挂载点先在镜像里建好并归给 zjj，命名卷才会以这个属主落盘。
# agent/operator/executor 各自一个卷，所以三个 caller 的私钥不会住在一起。
RUN mkdir -p /run /endpoints /callers /agent /operator /executor \
    && chown -R zjj:zjj /run /endpoints /callers /agent /operator /executor /app

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1
USER zjj
