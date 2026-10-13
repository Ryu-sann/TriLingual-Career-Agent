FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_CACHE_DIR=/tmp/uv-cache
RUN --mount=type=secret,id=cloud_ca,target=/run/cloud-ca,mode=0444 \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt_extra=""; if [ -s /run/cloud-ca ]; then apt_extra="-o Acquire::https::CaInfo=/run/cloud-ca"; fi; \
    apt-get $apt_extra -o APT::Update::Error-Mode=any update \
    && apt-get $apt_extra install -y --no-install-recommends chromium fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
RUN --mount=type=secret,id=cloud_ca,target=/run/cloud-ca,mode=0444 \
    if [ -s /run/cloud-ca ]; then PIP_CERT=/run/cloud-ca pip install --no-cache-dir uv==0.12.23; \
    else pip install --no-cache-dir uv==0.12.23; fi
RUN useradd --create-home --uid 10001 career
WORKDIR /app
RUN chown career:career /app
COPY --chown=career:career pyproject.toml uv.lock .python-version README.md alembic.ini ./
COPY --chown=career:career src ./src
COPY --chown=career:career migrations ./migrations
COPY --chown=career:career config ./config
COPY --chown=career:career examples ./examples
USER career
RUN --mount=type=secret,id=cloud_ca,target=/run/cloud-ca,uid=10001,gid=10001,mode=0444 \
    if [ -s /run/cloud-ca ]; then SSL_CERT_FILE=/run/cloud-ca uv --system-certs sync --locked; \
    else uv sync --locked; fi
ENV PATH=/app/.venv/bin:$PATH CAREER_PROJECT_ROOT=/app CAREER_CHROMIUM_PATH=/usr/bin/chromium
EXPOSE 8501
CMD ["streamlit", "run", "src/career_agent/dashboard/app.py", "--server.address=0.0.0.0", "--server.headless=true", "--browser.gatherUsageStats=false"]
