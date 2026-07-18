FROM dustynv/l4t-pytorch:r36.4.0
#FROM pytorch:r36.4.tegra-aarch64-cu126-22.04-cuda

# export timezone - for python3.9-dev install
ENV TZ=Europe/Paris
ENV CUDA_HOME=/usr/local/cuda-12.6
ENV PATH=${CUDA_HOME}/bin:${PATH}
ENV LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${LD_LIBRARY_PATH}

# place timezone data /etc/timezone
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY requirements.txt requirements.txt

RUN apt-get update

RUN pip install --index-url https://pypi.org/simple --upgrade pip
RUN mkdir -p /etc/pip && \
    echo "[global]\nindex-url = https://pypi.org/simple" > /etc/pip.conf

RUN pip install -r requirements.txt --index-url https://pypi.org/simple && rm requirements.txt

# Workaround: the trackers==2.5.0 PyPI wheel (and the wheel built from its sdist)
# is metadata-only (broken package discovery upstream) — no trackers/ package code.
# Fetch the sdist, extract, and copy the trackers/ package dir into site-packages.
RUN pip download trackers==2.5.0 --no-binary :all: --no-deps -d /tmp/tks --index-url https://pypi.org/simple \
    && cd /tmp/tks && tar xzf trackers-2.5.0.tar.gz \
    && cp -r trackers-2.5.0/trackers /usr/local/lib/python3.10/dist-packages/ \
    && python3 -c "import trackers; from trackers import OCSORTTracker; print('trackers 2.5.0 import OK')" \
    && rm -rf /tmp/tks

RUN mkdir -p /usr/local/lib/python3.10/dist-packages/cv2/qt/fonts \
    && ln -snf /usr/share/fonts/truetype/dejavu /usr/local/lib/python3.10/dist-packages/cv2/qt/fonts
    
# Build-info baking (BL-68): write /app/.build-info.json from build args so the
# image carries its git_commit + image_tag. Defaults keep local builds working.
ARG IMAGE_TAG=local
ARG GIT_COMMIT=unknown
WORKDIR /app
RUN printf '{"git_commit":"%s","image_tag":"%s"}\n' "$GIT_COMMIT" "$IMAGE_TAG" > /app/.build-info.json

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
