FROM ubuntu:18.04
LABEL maintainer "Andriy Khavryuchenko <akhavr@khavr.com>"

USER root
WORKDIR /root

RUN dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y --no-install-recommends software-properties-common \
    && apt-add-repository -y ppa:zebra-lucky/ed-bdeps \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        wine-development wine32-development wine64-development libwine-development libwine-development:i386 \
        cabextract xauth xvfb wget ca-certificates zip unzip p7zip-full \
    && wget https://raw.githubusercontent.com/Winetricks/winetricks/master/src/winetricks \
    && chmod +x winetricks && mv winetricks /usr/local/bin \
    && rm -rf /var/lib/apt/lists/*

ENV WINEPATH c:/git/cmd;c:/Python36;c:/Python36/Scripts
ENV WINEDEBUG -all
ENV WINEPREFIX /root/.wine-32
ENV WINEARCH win32
ENV PYHOME $WINEPREFIX/drive_c/Python36

RUN echo 'download and install 32-bit Python/pywin32/PyQt/git/NSIS' \
    && wineboot -i \
    && xvfb-run -a winetricks -q vcrun2015 && winetricks win10 \
    \
    && wget -nv -O python.exe https://www.python.org/ftp/python/3.6.6/python-3.6.6.exe \
    && xvfb-run -a wine python.exe /quiet InstallAllUsers=1 TargetDir=$PYHOME && rm python.exe \
    && wine python -m pip install -U pip \
    \
    && wget -nv -O libusb.7z https://prdownloads.sourceforge.net/project/libusb/libusb-1.0/libusb-1.0.22/libusb-1.0.22.7z?download \
    && 7z x -olibusb libusb.7z -aos && rm libusb.7z  \
    && cp libusb/MS32/dll/libusb-1.0.dll $PYHOME/ \
    \
    && wget -nv -O pywin32.exe https://github.com/mhammond/pywin32/releases/download/b223/pywin32-223.win32-py3.6.exe \
    && unzip -qq -d pywin32 pywin32.exe; echo && rm pywin32.exe \
    && cp -r pywin32/PLATLIB/* $PYHOME/Lib/site-packages/ \
    && cp -r pywin32/SCRIPTS/* $PYHOME/Scripts/ && rm -rf pywin32 \
    && wine python $PYHOME/Scripts/pywin32_postinstall.py -install \
    \
    && wine pip install PyQt5==5.11.2 \
    \
    && wget -nv -O git.zip https://github.com/git-for-windows/git/releases/download/v2.16.3.windows.1/MinGit-2.16.3-32-bit.zip \
    && unzip -qq -d git git.zip && rm git.zip && mv git $WINEPREFIX/drive_c/ \
    \
    && wget -nv -O nsis.exe "https://prdownloads.sourceforge.net/nsis/nsis-3.03-setup.exe?download" \
    && wine nsis.exe /S \
    \
    && rm -rf /tmp/.wine-0


ENV WINEPREFIX /root/.wine-64
ENV WINEARCH win64
ENV PYHOME $WINEPREFIX/drive_c/Python36

RUN echo 'download and install 64-bit Python/pywin32/PyQt/git/NSIS' \
    && wineboot -i && winetricks win10 \
    && wget -nv https://download.microsoft.com/download/9/3/F/93FCF1E7-E6A4-478B-96E7-D4B285925B00/vc_redist.x64.exe \
    && cabextract -d ex vc_redist.x64.exe && rm vc_redist.x64.exe \
    && cabextract -d ex/a10ex ex/a10 && cabextract -d ex/a11ex ex/a11 \
    && for f in ex/a10ex/api_ms_win_*; do mv $f $(echo "$f" | sed s/_/-/g); done \
    && cp ex/a10ex/* $WINEPREFIX/drive_c/windows/system32 \
    && cp ex/a11ex/* $WINEPREFIX/drive_c/windows/system32 \
    && rm -rf ex \
    \
    && wget -nv -O python.exe https://www.python.org/ftp/python/3.6.6/python-3.6.6-amd64.exe \
    && xvfb-run -a wine python.exe /quiet InstallAllUsers=1 TargetDir=$PYHOME && rm python.exe \
    && wine python -m pip install -U pip \
    \
    && cp libusb/MS64/dll/libusb-1.0.dll $PYHOME/ && rm -rf libusb \
    \
    && wget -nv -O pywin32.exe https://github.com/mhammond/pywin32/releases/download/b223/pywin32-223.win-amd64-py3.6.exe \
    && unzip -qq -d pywin32 pywin32.exe; echo && rm pywin32.exe \
    && cp -r pywin32/PLATLIB/* $PYHOME/Lib/site-packages/ \
    && cp -r pywin32/SCRIPTS/* $PYHOME/Scripts/ && rm -rf pywin32 \
    && wine python $PYHOME/Scripts/pywin32_postinstall.py -install \
    \
    && wine pip install PyQt5==5.11.2 \
    \
    && wget -nv -O git.zip https://github.com/git-for-windows/git/releases/download/v2.16.3.windows.1/MinGit-2.16.3-64-bit.zip \
    && unzip -qq -d git git.zip && rm git.zip && mv git $WINEPREFIX/drive_c/ \
    \
    && wine nsis.exe /S && rm nsis.exe \
    \
    && rm -rf /tmp/.wine-0
