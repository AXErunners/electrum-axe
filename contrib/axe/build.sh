#!/bin/bash


function read_jks_storepass {
    KEYSTORE=~/.jks/keystore
    KEYSTORE_ARG="-keystore $KEYSTORE"
    KEYTOOL_CMD="keytool -list -storepass:env JKS_STOREPASS $KEYSTORE_ARG"
    while [[ -z $JKS_STOREPASS ]]; do
        echo -n Input $KEYSTORE keystore password:
        read -s JKS_STOREPASS
        echo
        export JKS_STOREPASS
        keytool_res=`$KEYTOOL_CMD`
        if [[ $? == 0 ]]; then
            break
        else
            echo Wrong password
            export JKS_STOREPASS=''
        fi
    done
    export JKS_KEYPASS=$JKS_STOREPASS
}


if [[ ${OSTYPE} == "linux-gnu" ]]; then
    echo "Build for Linux/Windows/Android"
elif [[ ${OSTYPE} == "darwin"* ]]; then
    echo "Build for macOS"
else
    echo "Unknown OS: ${OSTYPE}"
    exit 1
fi


source contrib/axe/travis/electrum_axe_version_env.sh
if [[ -n $IS_RELEASE ]]; then
    echo electrum-axe version is $AXE_ELECTRUM_VERSION, release build
else
    echo electrum-axe version is $AXE_ELECTRUM_VERSION
fi
mkdir -p dist

BUILD_DIST_DIR=build/electrum-axe/dist
BUILD_BIN_DIR=build/electrum-axe/bin
NAME=Axe-Electrum
TNAME=Axe-Electrum-Testnet
DEB_NAME=electrum-axe
APK_NAME=Electrum_AXE
APK_TNAME=Electrum_AXE_Testnet
UAPK_TAIL=release-unsigned.apk
APK_TAIL=release.apk

if [[ "$OSTYPE" == "linux-gnu" ]]; then
    # Build sdist/AppImage/Windows
    sudo rm -rf build
    mkdir -p build && cp contrib/axe/travis/* ./build/
    ./build/before_install-linux.sh
    ./build/before_install-linux-apk.sh
    ./build/travis-build-linux.sh
    cp ${BUILD_DIST_DIR}/${NAME}-${AXE_ELECTRUM_VERSION}.tar.gz \
        dist/
    cp ${BUILD_DIST_DIR}/${NAME}-${AXE_ELECTRUM_VERSION}.zip \
        dist/
    cp ${BUILD_DIST_DIR}/${NAME}-${AXE_ELECTRUM_VERSION}-x86_64.AppImage \
        dist/
    cp ${BUILD_DIST_DIR}/${NAME}-${AXE_ELECTRUM_VERSION}-setup-win32.exe \
        dist/
    cp ${BUILD_DIST_DIR}/${NAME}-${AXE_ELECTRUM_VERSION}-setup-win64.exe \
        dist/

    # Build deb packages
    PEP440_PUBVER_PATTERN="^((\d+)!)?"
    PEP440_PUBVER_PATTERN=${PEP440_PUBVER_PATTERN}"(([0-9]+)(\.[0-9]+)*)"
    PEP440_PUBVER_PATTERN=${PEP440_PUBVER_PATTERN}"([a-zA-Z]+[0-9]+)?"
    PEP440_PUBVER_PATTERN=${PEP440_PUBVER_PATTERN}"((\.[a-zA-Z]+[0-9]+)*)$"
    if [[ ${AXE_ELECTRUM_VERSION} =~ ${PEP440_PUBVER_PATTERN} ]]; then
        if [[ -n ${BASH_REMATCH[1]} ]]; then
            DEB_VERSION="${BASH_REMATCH[2]}:"
        fi
        DEB_VERSION="${DEB_VERSION}${BASH_REMATCH[3]}"
        if [[ -n ${BASH_REMATCH[6]} ]]; then
            DEB_VERSION="${DEB_VERSION}~${BASH_REMATCH[6]}"
        fi
        if [[ -n ${BASH_REMATCH[7]} ]]; then
            DEB_VERSION="${DEB_VERSION}${BASH_REMATCH[7]}"
        fi
        DEB_SERIES=("xenial" "bionic" "disco" "eoan")
        DEB_SER_VER=("16.04.1" "18.04.1" "19.04.1" "19.10.1")

        pushd build
        sudo rm -rf electrum-axe
        cp ../dist/${NAME}-${AXE_ELECTRUM_VERSION}.tar.gz \
            ${DEB_NAME}_${DEB_VERSION}.orig.tar.gz
        tar xzf ${DEB_NAME}_${DEB_VERSION}.orig.tar.gz
        pushd ${NAME}-${AXE_ELECTRUM_VERSION}

        for ((i=0;i<${#DEB_SERIES[@]};i++)); do
            if [[ -f ~/pbuilder/${DEB_SERIES[i]}-base.tgz ]]; then
                PPA_VERSION=${DEB_VERSION}-0ppa1~ubuntu${DEB_SER_VER[i]}
                PPA_NAME=${DEB_NAME}_${PPA_VERSION}
                DEB_BUILD_DIR=~/pbuilder/${DEB_SERIES[i]}_result
                CHANGELOG_FIRST="${DEB_NAME} (${PPA_VERSION})"
                CHANGELOG_FIRST="${CHANGELOG_FIRST} ${DEB_SERIES[i]};"
                CHANGELOG_FIRST="${CHANGELOG_FIRST} urgency=medium"
                sed -i "1s/.*/$CHANGELOG_FIRST/" debian/changelog
                echo Building ${PPA_NAME}_all.deb python3-${PPA_NAME}_all.deb
                sudo debuild -i -us -uc -S
                pbuilder-dist ${DEB_SERIES[i]} ../${PPA_NAME}.dsc
                mkdir ../../dist/${DEB_SERIES[i]}
                cp ${DEB_BUILD_DIR}/${PPA_NAME}_all.deb \
                    ../../dist/${DEB_SERIES[i]}
                cp ${DEB_BUILD_DIR}/python3-${PPA_NAME}_all.deb \
                    ../../dist/${DEB_SERIES[i]}
            else
                echo ~/pbuilder/${DEB_SERIES[i]}-base.tgz not found
                echo Skip deb packages build for ${DEB_SERIES[i]}
            fi
        done

        popd
        popd
    else
        echo Version does not match PEP440 pubversion patter
        echo Skip deb packages build
    fi

    # Build mainnet release apk
    if [[ -n $IS_RELEASE ]]; then
        sudo rm -rf build
        mkdir -p build && cp contrib/axe/travis/* ./build/
        export ELECTRUM_MAINNET=true
        ./build/travis-build-linux-apk.sh
        cp ${BUILD_BIN_DIR}/${APK_NAME}-$AXE_ELECTRUM_APK_VERSION-$UAPK_TAIL \
            dist/
    fi

    # Build testnet release apk
    sudo rm -rf build
    mkdir -p build && cp contrib/axe/travis/* ./build/
    export ELECTRUM_MAINNET=false
    ./build/travis-build-linux-apk.sh
    cp ${BUILD_BIN_DIR}/${APK_TNAME}-$AXE_ELECTRUM_APK_VERSION-$UAPK_TAIL \
        dist/

    sudo rm -rf build

    read_jks_storepass

    # Sign mainnet apk
    if [[ -n $IS_RELEASE ]]; then
        jarsigner -verbose \
            -tsa http://sha256timestamp.ws.symantec.com/sha256/timestamp \
            -sigalg SHA1withRSA -digestalg SHA1 \
            -sigfile axe-electrum \
            -keystore ~/.jks/keystore \
            -storepass:env JKS_STOREPASS \
            -keypass:env JKS_KEYPASS \
            dist/${APK_NAME}-$AXE_ELECTRUM_APK_VERSION-$UAPK_TAIL \
            axerunners.com

        zipalign -v 4 \
            dist/${APK_NAME}-$AXE_ELECTRUM_APK_VERSION-$UAPK_TAIL \
            dist/${NAME}-$AXE_ELECTRUM_APK_VERSION-$APK_TAIL \

        rm dist/${APK_NAME}-$AXE_ELECTRUM_APK_VERSION-$UAPK_TAIL
    fi

    # Sign testnet apk
    jarsigner -verbose \
        -tsa http://sha256timestamp.ws.symantec.com/sha256/timestamp \
        -sigalg SHA1withRSA -digestalg SHA1 \
        -sigfile axe-electrum \
        -keystore ~/.jks/keystore \
        -storepass:env JKS_STOREPASS \
        -keypass:env JKS_KEYPASS \
        dist/${APK_TNAME}-$AXE_ELECTRUM_APK_VERSION-$UAPK_TAIL \
        axerunners.com

    zipalign -v 4 \
        dist/${APK_TNAME}-$AXE_ELECTRUM_APK_VERSION-$UAPK_TAIL \
        dist/${TNAME}-$AXE_ELECTRUM_APK_VERSION-$APK_TAIL \

    rm dist/${APK_TNAME}-$AXE_ELECTRUM_APK_VERSION-$UAPK_TAIL
else
    # Build macOS
    sudo rm -rf build
    mkdir -p build && cp contrib/axe/travis/* ./build/
    ./build/before_install-osx.sh
    ./build/travis-build-osx.sh
    cp ${BUILD_DIST_DIR}/${NAME}-${AXE_ELECTRUM_VERSION}-macosx.dmg \
        dist/
fi
