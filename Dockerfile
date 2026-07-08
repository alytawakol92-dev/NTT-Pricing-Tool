# NTT Pricing Tool — container image for cloud hosting.
# Builds LibreDWG (dwg2dxf) so DWG uploads work, installs the app, and serves
# it with gunicorn.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    NTT_DWG2DXF=/usr/local/bin/dwg2dxf \
    PORT=8080

# ---- build LibreDWG (DWG -> DXF converter) ----
RUN apt-get update && apt-get install -y --no-install-recommends \
        git cmake build-essential pkg-config ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/LibreDWG/libredwg.git /tmp/libredwg \
    && cd /tmp/libredwg \
    && git submodule update --init \
    && cmake -S . -B build -DLIBREDWG_LIBONLY=OFF -DENABLE_BINDINGS=OFF >/dev/null \
    && cmake --build build --target dwg2dxf -j 4 \
    && install -m755 build/dwg2dxf /usr/local/bin/dwg2dxf \
    && cp build/libredwg.so* /usr/local/lib/ 2>/dev/null || true \
    && ldconfig \
    && rm -rf /tmp/libredwg

# ---- app ----
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# gunicorn: honour the platform's $PORT.
#  * default to ONE worker — the 13k-row price book + DWG conversions are
#    memory-heavy, and a second worker doubles peak RAM on a 512 MB instance
#    (raise WEB_CONCURRENCY on a larger plan);
#  * long timeout so a multi-drawing job on a throttled CPU still finishes;
#  * recycle the worker every so often to release memory between big jobs.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8080} --workers ${WEB_CONCURRENCY:-1} --timeout 300 --max-requests 20 --max-requests-jitter 5 wsgi:app"]
