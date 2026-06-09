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
.
RUN pip install --index-url https://pypi.org/simple --upgrade pip
RUN mkdir -p /etc/pip && \
    echo "[global]\nindex-url = https://pypi.org/simple" > /etc/pip.conf

RUN pip install -r requirements.txt --index-url https://pypi.org/simple && rm requirements.txt

RUN mkdir -p /usr/local/lib/python3.10/dist-packages/cv2/qt/fonts \
    && ln -snf /usr/share/fonts/truetype/dejavu /usr/local/lib/python3.10/dist-packages/cv2/qt/fonts
    
WORKDIR /app

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
