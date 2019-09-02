from pythonforandroid.recipe import CythonRecipe
from pythonforandroid.toolchain import shutil
from os.path import join


class BlsPyRecipe(CythonRecipe):

    url = ('https://files.pythonhosted.org/packages/82/74/'
           'e9ae900370181d162db5c77ba1e636045358bbae152aef10ba3eace41c15/'
           'python-bls-0.1.8.tar.gz')
    md5sum = 'e264187b7b1768cd620827debddfffda'
    version = '0.1.8'
    depends = ['python3', 'setuptools', 'libgmp']

    def build_arch(self, arch):
        # copy gmp.h from libgmp/dist/include to extmod/bls_py
        self_build_dir = self.get_build_dir(arch.arch)
        libgmp_build_dir = self_build_dir.replace('bls_py', 'libgmp')
        libgmp_build_dir = libgmp_build_dir.replace('-python3', '')
        local_path = join(self_build_dir, 'extmod', 'bls_py', 'gmp.h')
        libgmp_path = join(libgmp_build_dir, 'dist', 'include', 'gmp.h')
        shutil.copyfile(libgmp_path, local_path)
        super(BlsPyRecipe, self).build_arch(arch)


recipe = BlsPyRecipe()
