#!/bin/bash

set -e

PROJECT_ROOT="$(dirname "$(readlink -e "$0")")/../../.."
CONTRIB="$PROJECT_ROOT/contrib"
DISTDIR="$PROJECT_ROOT/dist"
BUILDDIR="/var/build/appimage"
APPDIR="$BUILDDIR/electrum-dash.AppDir"
CACHEDIR="$BUILDDIR/.cache/appimage"

# pinned versions
PYTHON_VERSION=3.6.8
PKG2APPIMAGE_COMMIT="83483c2971fcaa1cb0c1253acd6c731ef8404381"
LIBSECP_VERSION="b408c6a8b287003d1ade5709e6f7bc3c7f1d5be7"

pushd $PROJECT_ROOT
source $CONTRIB/dash/travis/electrum_dash_version_env.sh
popd
VERSION=$DASH_ELECTRUM_VERSION
APPIMAGE="$DISTDIR/Dash-Electrum-$VERSION-x86_64.AppImage"

mkdir -p "$APPDIR" "$CACHEDIR" "$DISTDIR"


. "$CONTRIB"/build_tools_util.sh


info "downloading some dependencies."
download_if_not_exist "$CACHEDIR/functions.sh" "https://raw.githubusercontent.com/AppImage/pkg2appimage/$PKG2APPIMAGE_COMMIT/functions.sh"
verify_hash "$CACHEDIR/functions.sh" "a73a21a6c1d1e15c0a9f47f017ae833873d1dc6aa74a4c840c0b901bf1dcf09c"

download_if_not_exist "$CACHEDIR/appimagetool" "https://github.com/probonopd/AppImageKit/releases/download/11/appimagetool-x86_64.AppImage"
verify_hash "$CACHEDIR/appimagetool" "c13026b9ebaa20a17e7e0a4c818a901f0faba759801d8ceab3bb6007dde00372"

appdir_python() {
  env \
    PYTHONNOUSERSITE=1 \
    LD_LIBRARY_PATH="$APPDIR/usr/lib:$APPDIR/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH+:$LD_LIBRARY_PATH}" \
    "$APPDIR/usr/bin/python3.6" "$@"
}

python='appdir_python'


info "installing pip."
"$python" -m ensurepip


info "installing electrum-dash and its dependencies."
mkdir -p "$CACHEDIR/pip_cache"
"$python" -m pip install --cache-dir "$CACHEDIR/pip_cache" -r "$CONTRIB/deterministic-build/requirements.txt"
"$python" -m pip install --cache-dir "$CACHEDIR/pip_cache" -r "$CONTRIB/deterministic-build/requirements-binaries.txt"
"$python" -m pip install --cache-dir "$CACHEDIR/pip_cache" -r "$CONTRIB/deterministic-build/requirements-hw.txt"
"$python" -m pip install --cache-dir "$CACHEDIR/pip_cache" "$PROJECT_ROOT"


info "copying zbar"
cp "/usr/lib/libzbar.so.0" "$APPDIR/usr/lib/libzbar.so.0"


info "desktop integration."
cp "$PROJECT_ROOT/electrum-dash.desktop" "$APPDIR/electrum-dash.desktop"
cp "$PROJECT_ROOT/electrum_dash/gui/icons/electrum-dash.png" "$APPDIR/electrum-dash.png"


# add launcher
cp "$CONTRIB/dash/travis/apprun.sh" "$APPDIR/AppRun"

info "finalizing AppDir."
(
    export PKG2AICOMMIT="$PKG2APPIMAGE_COMMIT"
    . "$CACHEDIR/functions.sh"

    cd "$APPDIR"
    # copy system dependencies
    # note: temporarily move PyQt5 out of the way so
    # we don't try to bundle its system dependencies.
    mv "$APPDIR/usr/lib/python3.6/site-packages/PyQt5" "$BUILDDIR"
    copy_deps; copy_deps; copy_deps
    move_lib
    mv "$BUILDDIR/PyQt5" "$APPDIR/usr/lib/python3.6/site-packages"

    # apply global appimage blacklist to exclude stuff
    # move usr/include out of the way to preserve usr/include/python3.6m.
    mv usr/include usr/include.tmp
    delete_blacklisted
    mv usr/include.tmp usr/include
)


info "stripping binaries from debug symbols."
strip_binaries()
{
  chmod u+w -R "$APPDIR"
  {
    printf '%s\0' "$APPDIR/usr/bin/python3.6"
    find "$APPDIR" -type f -regex '.*\.so\(\.[0-9.]+\)?$' -print0
  } | xargs -0 --no-run-if-empty --verbose -n1 strip
}
strip_binaries

remove_emptydirs()
{
  find "$APPDIR" -type d -empty -print0 | xargs -0 --no-run-if-empty rmdir -vp --ignore-fail-on-non-empty
}
remove_emptydirs


info "removing some unneeded stuff to decrease binary size."
rm -rf "$APPDIR"/usr/lib/python3.6/test
rm -rf "$APPDIR"/usr/lib/python3.6/config-3.6m-x86_64-linux-gnu
rm -rf "$APPDIR"/usr/lib/python3.6/site-packages/PyQt5/Qt/translations/qtwebengine_locales
rm -rf "$APPDIR"/usr/lib/python3.6/site-packages/PyQt5/Qt/resources/qtwebengine_*
rm -rf "$APPDIR"/usr/lib/python3.6/site-packages/PyQt5/Qt/qml
rm -rf "$APPDIR"/usr/lib/python3.6/site-packages/PyQt5/Qt/lib/libQt5Web*
rm -rf "$APPDIR"/usr/lib/python3.6/site-packages/PyQt5/Qt/lib/libQt5Designer*
rm -rf "$APPDIR"/usr/lib/python3.6/site-packages/PyQt5/Qt/lib/libQt5Qml*
rm -rf "$APPDIR"/usr/lib/python3.6/site-packages/PyQt5/Qt/lib/libQt5Quick*
rm -rf "$APPDIR"/usr/lib/python3.6/site-packages/PyQt5/Qt/lib/libQt5Location*
rm -rf "$APPDIR"/usr/lib/python3.6/site-packages/PyQt5/Qt/lib/libQt5Test*
rm -rf "$APPDIR"/usr/lib/python3.6/site-packages/PyQt5/Qt/lib/libQt5Xml*


info "creating the AppImage."
(
    cd "$BUILDDIR"
    chmod +x "$CACHEDIR/appimagetool"
    "$CACHEDIR/appimagetool" --appimage-extract
    env VERSION="$VERSION" ./squashfs-root/AppRun --no-appstream --verbose "$APPDIR" "$APPIMAGE"
)


info "done."
ls -la "$DISTDIR"
sha256sum "$DISTDIR"/*
