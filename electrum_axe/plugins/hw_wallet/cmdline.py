from electrum_axe.util import print_error, print_stderr, raw_input


class CmdLineHandler:

    def get_passphrase(self, msg, confirm):
        import getpass
        print_stderr(msg)
        return getpass.getpass('')

    def get_pin(self, msg):
        t = { 'a':'7', 'b':'8', 'c':'9', 'd':'4', 'e':'5', 'f':'6', 'g':'1', 'h':'2', 'i':'3'}
        print_stderr(msg)
        print_stderr("a b c\nd e f\ng h i\n-----")
        o = raw_input()
        try:
            return ''.join(map(lambda x: t[x], o))
        except KeyError as e:
            raise Exception("Character {} not in matrix!".format(e)) from e

    def prompt_auth(self, msg):
        import getpass
        print_stderr(msg)
        response = getpass.getpass('')
        if len(response) == 0:
            return None
        return response

    def yes_no_question(self, msg):
        print_stderr(msg)
        return raw_input() in 'yY'

    def stop(self):
        pass

    def show_message(self, msg, on_cancel=None):
        print_stderr(msg)

    def show_error(self, msg, blocking=False):
        print_stderr(msg)

    def update_status(self, b):
        print_error('hw device status', b)

    def finished(self):
        pass
