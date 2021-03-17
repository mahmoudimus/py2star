import unittest


class RewriteMe(unittest.TestCase):

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

    def test_success(self):
        self.assertEqual(1, 1)

    def test_fail(self):
        self.assertEqual(1, 2)