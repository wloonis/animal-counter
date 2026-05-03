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
# RUN apt-get remove python3-numpy -y
# RUN apt-get install -y \
#     qtbase5-dev \
#     qtchooser \
#     qt5-qmake \
#     qtbase5-dev-tools

RUN pip install --index-url https://pypi.org/simple --upgrade pip
RUN mkdir -p /etc/pip && \
    echo "[global]\nindex-url = https://pypi.org/simple" > /etc/pip.conf

RUN pip install -r requirements.txt --index-url https://pypi.org/simple && rm requirements.txt

RUN mkdir -p /usr/local/lib/python3.10/dist-packages/cv2/qt/fonts \
    && ln -snf /usr/share/fonts/truetype/dejavu /usr/local/lib/python3.10/dist-packages/cv2/qt/fonts

# ENV OPENCV_VERSION=4.13.0
# ENV OPENCV_PYTHON=92
# ENV OPENCV_URL=http://jetson.webredirect.org:8000/jp6/cu126/
# ENV CUDA_ARCH_BIN=8.7
# ENV FORCE_BUILD=off
# ENV TMP=/tmp/opencv

# COPY ./build/build.sh \
#      ./build/install.sh \
#      ./build/install_deps.sh \
#      ./build/install_deb.sh \
#      ./build/install_pip.sh \
#      ./build/patches.diff \
#      $TMP/

# RUN cd $TMP && ./build.sh || true

# RUN if [ ! -f "$TMP/.opencv" ]; then \
#       echo "FAILED to install OpenCV $OPENCV_VERSION"; \
#       exit 1; \
#     fi     
    
WORKDIR /app

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

#CMD ["sh", "-c", "python3 src/main.py"]
#CMD ["sleep", "infinity"]
