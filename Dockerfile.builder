FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive
ENV ARCH=arm64

RUN sed -i 's|http://archive.ubuntu.com|http://mirrors.ustc.edu.cn|g; s|http://security.ubuntu.com|http://mirrors.ustc.edu.cn|g' /etc/apt/sources.list && \
    apt-get update && apt-get install -y wget gnupg && \
    wget -q https://apt.llvm.org/llvm-snapshot.gpg.key -O /etc/apt/trusted.gpg.d/llvm.asc && \
    echo "deb http://apt.llvm.org/focal/ llvm-toolchain-focal-14 main" >> /etc/apt/sources.list && \
    apt-get update && apt-get install -y \
    git curl zip unzip python3 python3-pip \
    build-essential libssl-dev bc cpio kmod ccache \
    device-tree-compiler lz4 zstd flex bison libelf-dev \
    gcc-aarch64-linux-gnu g++-aarch64-linux-gnu \
    gcc-arm-linux-gnueabi \
    clang-14 lld-14 llvm-14 llvm-14-dev \
    && rm -rf /var/lib/apt/lists/*

RUN for tool in clang clang++ ld.lld llvm-ar llvm-nm llvm-objcopy llvm-objdump llvm-strip llvm-readelf; do \
      ln -sf "/usr/bin/${tool}-14" "/usr/local/bin/${tool}"; \
    done && \
    /usr/local/bin/clang --version | head -1

ENV CCACHE_DIR=/ccache
ENV USE_CCACHE=1
ENV CCACHE_COMPRESS=1
ENV CCACHE_MAXSIZE=5G

WORKDIR /build

CMD ["/bin/bash"]
