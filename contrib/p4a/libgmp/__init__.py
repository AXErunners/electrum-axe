from pythonforandroid.recipe import Recipe
from pythonforandroid.toolchain import shprint, current_directory
from multiprocessing import cpu_count
from os.path import join, exists
from os import environ
import sh


class LibGMPRecipe(Recipe):

    url = 'https://gmplib.org/download/gmp/gmp-6.1.2.tar.xz'
    md5sum = 'f58fa8001d60c4c77595fbbb62b63c1d'
    version = '6.1.2'

    def select_build_arch(self, arch):
        if 'arm64' in arch.arch:
            return 'arm64'
        else:
            return 'arm'

    def get_recipe_env(self, arch):
        # We don't use the normal env because we
        # are building with a standalone toolchain
        env = environ.copy()
        env['ARCH'] = _arch = self.select_build_arch(arch)
        env['GMP_ROOT'] = self.get_build_dir(arch.arch)
        env['CROSSHOME'] = join(env['GMP_ROOT'],
                                'standalone-%s-toolchain' % env['ARCH'])
        env['PATH'] = '%s:%s' % (join(env['CROSSHOME'], 'bin'),
                                 env['PATH'])
        # flags from https://github.com/Rupan/gmp
        env['BASE_CFLAGS'] = ('-O2 -g -pedantic -fomit-frame-pointer'
                              ' -Wa,--noexecstack -ffunction-sections'
                              ' -funwind-tables -no-canonical-prefixes'
                              ' -fno-strict-aliasing')
        if _arch.endswith('arm64'):
            env['LDFLAGS'] = ('-Wl,--no-undefined -Wl,-z,noexecstack'
                              ' -Wl,-z,relro -Wl,-z,now')
            env['CFLAGS'] = (env['BASE_CFLAGS'] +
                             ' -fstack-protector-strong -finline-limit=300'
                             ' -funswitch-loops')
        else:
            env['LDFLAGS'] = ('-Wl,--fix-cortex-a8 -Wl,--no-undefined '
                              '-Wl,-z,noexecstack -Wl,-z,relro -Wl,-z,now')
            env['CFLAGS'] = (env['BASE_CFLAGS'] +
                             ' -fstack-protector -finline-limit=64'
                             ' -march=armv7-a -mfloat-abi=softfp -mfpu=vfp')
        return env

    def prebuild_arch(self, arch):
        super(LibGMPRecipe, self).prebuild_arch(arch)
        env = self.get_recipe_env(arch)
        with current_directory(self.get_build_dir(arch.arch)):
            if not exists(env['CROSSHOME']):
                # Make custom toolchain
                py3 = sh.Command('python3')
                shprint(py3,
                        join(self.ctx.ndk_dir,
                             'build/tools/make_standalone_toolchain.py'),
                        '--arch=%s' % env['ARCH'],
                        '--api=%s' % self.ctx.android_api,
                        '--install-dir=%s' % env['CROSSHOME'])

    def build_arch(self, arch):
        super(LibGMPRecipe, self).build_arch(arch)
        env = self.get_recipe_env(arch)
        if env['ARCH'].endswith('arm64'):
            _HOST = 'aarch64-linux-android'
            MPN_PATH = 'arm64 generic'
        else:
            _HOST = 'arm-linux-androideabi'
            MPN_PATH = 'arm/v6t2 arm/v6 arm/v5 arm generic'
        with current_directory(self.get_build_dir(arch.arch)):
            dst_dir = join(self.get_build_dir(arch.arch), 'dist')
            shprint(sh.Command('./configure'),
                    '--host={}'.format(_HOST),
                    '--disable-shared',
                    '--prefix={}'.format(dst_dir),
                    'MPN_PATH={}'.format(MPN_PATH),
                    _env=env)
            shprint(sh.sed, '-i.bak', '/HAVE_LOCALECONV 1/d',
                    './config.h', _env=env)
            shprint(sh.make, '-j%s' % cpu_count(), _env=env)
            shprint(sh.make, 'install', _env=env)
            libs = ['dist/lib/libgmp.a']
            self.install_libs(arch, *libs)


recipe = LibGMPRecipe()
