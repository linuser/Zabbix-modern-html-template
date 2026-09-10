# Runner for the end-to-end test: Python + Playwright/Chromium + the build dependencies.
# The repository is mounted at /work at run time (see ../compose.yaml).
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

# The image ships the browsers (/ms-playwright) but not the Python package; its version
# must match the image tag.
COPY requirements.txt /tmp/requirements.txt
# Pillow composes the README images (run.py docs).
RUN python3 -m pip install --no-cache-dir --break-system-packages -r /tmp/requirements.txt playwright==1.62.0 pillow==12.3.0

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /work
ENTRYPOINT ["python3", "/work/test/e2e/runner/run.py"]
CMD ["scenario"]
