from .fixture_data import Foo


class RewriteMe(Foo):
    def __init__(self):
        """Do stuff"""
        super(Foo).__init__()

    def bar(self,
            q,
            w,
            z):
        # this does some stuff
        return list(q, w, z)

    def bar(self, baz):
        # multi
        # line
        # comment
        pass

    def write(self):
        pass