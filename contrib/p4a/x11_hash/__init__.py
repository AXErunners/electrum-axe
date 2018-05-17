from pythonforandroid.recipe import CythonRecipe


class X11HashRecipe(CythonRecipe):

    url = 'https://files.pythonhosted.org/packages/source/x/x11_hash/x11_hash-{version}.tar.gz'
    md5sum = 'bc08267fee5dedef5e67b60dca59ef00'
    version = '1.4'
    depends = ['python3crystax']

    def should_build(self, arch):
        """It's faster to build than check"""
        return True


recipe = X11HashRecipe()
