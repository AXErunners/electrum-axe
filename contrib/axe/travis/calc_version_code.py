#!/usr/bin/env python3

import os


apk_version = os.environ.get('AXE_ELECTRUM_APK_VERSION')
android_arch = os.environ.get('APP_ANDROID_ARCH')
apk_version_code = sum((map(lambda x: (100**(4-x[0]))*int(x[1]),
                            enumerate(apk_version.split('.')))))
if android_arch == 'arm64-v8a':
    apk_version_code += 1

print(apk_version_code)
