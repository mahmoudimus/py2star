from unittest import TestCase
import unittest


class RewriteMe(TestCase):

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

    def doit(self):
        x = b'foo'
        return x

    def test_success(self):
        self.assertEqual(1, 1)

    def test_fail(self):
        self.assertEqual(1, 2)

    def test_doit(self):
        self.assertRegex("herpa", "her.*", "could not find herpa")
