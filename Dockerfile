# Anchor & Delta — Railway deployment image.
#
# Same Streamlit app as local dev (ui/app.py), containerized only so
# Playwright's Chromium can get real system-level dependencies installed —
# the one thing Streamlit Cloud's managed container didn't allow
# (see ARCHITECTURE_SNAPSHOT.md §4.2, INFRA_DECISIONS.md Decision #01).

FROM python:3.11-slim

WORKDIR /app

# System deps for Pillow/lxml wheels that sometimes need a C toolchain,
# plus curl for local debugging. Playwright's own Chromium system deps are
# installed separately below via `--with-deps`, not listed here.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Installs the Chromium binary AND its system-level shared libraries
# (fonts, libnss3, libatk, etc.) — this is the exact capability Streamlit
# Cloud's container lacked (DESIGN_LESSONS.md §14, Decision #50).
RUN playwright install --with-deps chromium

COPY . .

ENV PORT=8501
EXPOSE 8501

CMD ["sh", "-c", "streamlit run ui/app.py --server.port ${PORT} --server.address 0.0.0.0"]
