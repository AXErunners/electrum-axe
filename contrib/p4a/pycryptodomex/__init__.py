from pythonforandroid.recipe import PythonRecipe


class PycryptodomeXRecipe(PythonRecipe):
    version = '3.6.3'
    url = ('https://files.pythonhosted.org/packages/e6/5a/'
           'cf2bd33574f8f8711bad12baee7ef5c9c53a09c338cec241abfc0ba0cf63/'
           'pycryptodomex-3.6.3.tar.gz')
    md5sum = 'ed1dc06ca4ba6a058ef47db56462234f'
    depends = ['setuptools', 'cffi']


recipe = PycryptodomeXRecipe()
