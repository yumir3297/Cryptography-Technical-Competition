# 一个镜像装整套：受信端、各角色端和调用者是同一个包的不同入口。
FROM python:3.13-slim

# 全部容器同一个 uid。端钥和端 socket 都是 0600 且检查属主，读它们的进程必须是
# 同一个用户；X 回执子进程与工具子进程是从共享卷上直接读凭据的，所以受信端也得
# 读得到那两个文件。
ARG UID=1000
RUN useradd --uid "$UID" --create-home --shell /usr/sbin/nologin zjj

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 契约与 Schema 是运行时从仓库树里读的，所以要带上整棵树而不是一个 wheel。
COPY competition ./competition
COPY system_dev ./system_dev

# 卷的挂载点先在镜像里建好并归给 zjj，命名卷才会以这个属主落盘。
RUN mkdir -p /run /endpoints /callers && chown -R zjj:zjj /run /endpoints /callers /app

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1
USER zjj
