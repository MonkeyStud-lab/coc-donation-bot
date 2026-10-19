FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-tk adb aapt curl ca-certificates \
    libglib2.0-0 libgl1 tesseract-ocr \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
RUN python -m pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY config ./config
COPY data/game ./data/game
COPY scripts/setup_live_view.py ./scripts/setup_live_view.py
COPY scripts/sync_game_data.py ./scripts/sync_game_data.py
# CPU-only Torch keeps the bot image independent of the host graphics driver.
RUN python -m pip install --no-cache-dir '.[web,web-live]' \
    && python scripts/setup_live_view.py \
    && python scripts/sync_game_data.py --icons-only --require-core-icons \
    && mkdir -p /app/bin \
    && printf '#!/opt/venv/bin/python\nfrom coc_bot.host_bridge import shim_main\nshim_main()\n' > /app/bin/waydroid \
    && cp /app/bin/waydroid /app/bin/gdbus \
    && chmod 755 /app/bin/waydroid /app/bin/gdbus
ENV PATH=/app/bin:/opt/venv/bin:$PATH COC_BOT_HOME=/profile COC_HOST_SOCKET=/host-runtime/host.sock
ENV HOME=/profile EASYOCR_MODULE_PATH=/profile/data/ocr-cache TORCH_HOME=/profile/data/torch-cache
RUN apt-get update && apt-get install -y --no-install-recommends apksigner default-jre-headless \
    && rm -rf /var/lib/apt/lists/*
# Helper-only updates must not invalidate the large Python/artwork build layer.
COPY packaging/casaos ./packaging/casaos
USER 1000:1000
EXPOSE 8767
ENTRYPOINT ["python", "/app/packaging/casaos/entrypoint.py"]
