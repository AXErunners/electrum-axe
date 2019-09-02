FROM ubuntu:18.04
LABEL maintainer "Andriy Khavryuchenko <akhavr@khavr.com>"

ENV LANG="en_US.UTF-8" \
    LANGUAGE="en_US.UTF-8" \
    LC_ALL="en_US.UTF-8"

ENV OPTDIR="/opt"
ENV ANDROID_NDK_HOME="${OPTDIR}/android-ndk"
ENV ANDROID_NDK_VERSION="17c"
ENV ANDROID_NDK_HOME_V="${ANDROID_NDK_HOME}-r${ANDROID_NDK_VERSION}"
ENV ANDROID_NDK_ARCHIVE="android-ndk-r${ANDROID_NDK_VERSION}-linux-x86_64.zip"
ENV ANDROID_NDK_DL_URL="https://dl.google.com/android/repository/${ANDROID_NDK_ARCHIVE}"

ENV ANDROID_SDK_HOME="${OPTDIR}/android-sdk"
ENV ANDROID_SDK_TOOLS_VERSION="4333796"
ENV ANDROID_SDK_BUILD_TOOLS_VERSION="28.0.3"
ENV ANDROID_SDK_TOOLS_ARCHIVE="sdk-tools-linux-${ANDROID_SDK_TOOLS_VERSION}.zip"
ENV ANDROID_SDK_TOOLS_DL_URL="https://dl.google.com/android/repository/${ANDROID_SDK_TOOLS_ARCHIVE}"

ENV USE_SDK_WRAPPER=1
ENV GRADLE_OPTS="-Xmx1536M -Dorg.gradle.jvmargs='-Xmx1536M'"
ENV USER="buildozer"
ENV HOMEDIR="/home/${USER}"
ENV WORKDIR="${HOMEDIR}/build" \
    PATH="${HOMEDIR}/.local/bin:${PATH}"


RUN dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        software-properties-common \
    && add-apt-repository ppa:kivy-team/kivy \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        software-properties-common \
        language-pack-en build-essential ccache git \
        libncurses5:i386 libstdc++6:i386 libgtk2.0-0:i386 \
        libpangox-1.0-0:i386 libpangoxft-1.0-0:i386 libidn11:i386 \
        openjdk-8-jdk unzip zlib1g-dev zlib1g:i386 zip sudo \
        python3-dev python3-kivy lbzip2 \
        wget curl ca-certificates patch vim less autoconf automake libtool \
        libffi-dev cmake gettext libltdl-dev pkg-config \
        locales \
        ffmpeg \
        libsdl2-dev \
        libsdl2-image-dev \
        libsdl2-mixer-dev \
        libsdl2-ttf-dev \
        libportmidi-dev \
        libswscale-dev \
        libavformat-dev \
        libavcodec-dev \
        libgmp-dev \
    && locale-gen en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

RUN wget https://bootstrap.pypa.io/get-pip.py && python3 get-pip.py \
    && pip3 install --upgrade setuptools cython==0.29.9 image

RUN git config --global user.email "buildozer@example.com" \
    && git config --global user.name "Buildozer"

RUN adduser --disabled-password --gecos '' ${USER} \
    && mkdir /home/buildozer/build \
    && chown ${USER}.${USER} ${WORKDIR}
RUN usermod -append --groups sudo ${USER}
RUN echo "%sudo ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

RUN cd ${OPTDIR} \
    && git clone https://github.com/kivy/python-for-android \
    && cd python-for-android \
    && git remote add sombernight \
        https://github.com/SomberNight/python-for-android \
    && git fetch --all \
    && git checkout ccb0f8e1bab36f1b7d1508216b4b4afb076e614f \
    && git cherry-pick d7f722e4e5d4b3e6f5b1733c95e6a433f78ee570 \
    && git cherry-pick ed20e196fbcdce718a180f88f23bb2d165c4c5d8 \
    && python3 -m pip install -e . \
    && cd ${OPTDIR} \
    && git clone https://github.com/kivy/buildozer \
    && cd buildozer \
    && git checkout 678b1bf52cf63daa51b06e86a43ea4e2ea8a0b24 \
    && python3 -m pip install -e .

RUN cd ${OPTDIR} \
    && curl -# "${ANDROID_SDK_TOOLS_DL_URL}" \
        --output "${ANDROID_SDK_TOOLS_ARCHIVE}" \
    && mkdir --parents "${ANDROID_SDK_HOME}" \
    && unzip -q "${ANDROID_SDK_TOOLS_ARCHIVE}" -d "${ANDROID_SDK_HOME}" \
    && rm -rf "${ANDROID_SDK_TOOLS_ARCHIVE}" \
    && mkdir --parents "${ANDROID_SDK_HOME}/.android/" \
    && echo '### User Sources for Android SDK Manager' \
        > "${ANDROID_SDK_HOME}/.android/repositories.cfg" \
    && yes | "${ANDROID_SDK_HOME}/tools/bin/sdkmanager" \
        "build-tools;${ANDROID_SDK_BUILD_TOOLS_VERSION}" > /dev/null \
    && "${ANDROID_SDK_HOME}/tools/bin/sdkmanager" \
        "platforms;android-24" > /dev/null \
    && "${ANDROID_SDK_HOME}/tools/bin/sdkmanager" \
        "platforms;android-28" > /dev/null \
    && "${ANDROID_SDK_HOME}/tools/bin/sdkmanager" \
        "build-tools;${ANDROID_SDK_BUILD_TOOLS_VERSION}" > /dev/null \
    && "${ANDROID_SDK_HOME}/tools/bin/sdkmanager" \
        "extras;android;m2repository" > /dev/null && \
    chmod +x "${ANDROID_SDK_HOME}/tools/bin/avdmanager"

RUN cd ${OPTDIR} \
    && curl -# "${ANDROID_NDK_DL_URL}" \
        --output "${ANDROID_NDK_ARCHIVE}" \
    && mkdir --parents "${ANDROID_NDK_HOME_V}" \
    && unzip -q "${ANDROID_NDK_ARCHIVE}" -d "${OPTDIR}" \
    && chown -R ${USER}.${USER} ${OPTDIR} \
    && ln -sfn "${ANDROID_NDK_HOME_V}" "${ANDROID_NDK_HOME}" \
    && rm -rf "${ANDROID_NDK_ARCHIVE}"

USER ${USER}
WORKDIR ${WORKDIR}
