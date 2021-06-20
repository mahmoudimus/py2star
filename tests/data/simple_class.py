from unittest import TestCase
import unittest


def AES(key, mode, nonce=None):
    print(key, mode, nonce)
    raise ValueError(f"{key}, {mode}, {nonce}")


class RewriteMe(TestCase):
    def bar(self, q, w, z):
        # this does some stuff
        return [q, w, z]

    def xor(self, baz):
        # multi
        # line
        # comment
        pass

    def write(self):
        return self.__dict__.get("foo")

    def do_it(self):
        x = b"foo"
        return x

    def do_it2(self):
        x = b"fxxx\x80"
        return x

    def do_it3(self):
        x = b"\x01\x00\x10\x80"
        return x

    def do_it4(self):
        x = b"fo0\x7F"
        return x

    def test_success(self):
        self.assertEqual(1, 1)
        self.assertIsNone(None)
        self.assertIsNotNone([])
        self.assertTrue(True)

    def test_fail(self):
        self.assertNotEqual(1, 2)

    def test_doit(self):
        self.assertRegex("herpa", "her.*", "could not find herpa")

    def test_fstring(self) -> str:
        foo = 1
        return f"{foo}"

    def test_raises(self):
        key_128 = 128
        MODE_GCM = "gcm"
        self.assertRaises(ValueError, AES, key_128, MODE_GCM, nonce=b"")

    def test_bool(self):
        v1, v2, v3, v4 = (0, 10, -9, 2 ** 10)
        self.assertFalse(v1)
        self.assertFalse(bool(v1))
        self.failUnless(v2)
        self.failUnless(bool(v2))
        self.failUnless(v3)
        self.failUnless(v4)

    def test_upper(self):
        self.assertEqual("foo".upper(), "FOO")

    def test_isupper(self):
        self.assertTrue("FOO".isupper())
        self.assertFalse("Foo".isupper())

    def test_split(self):
        s = "hello world"
        self.assertEqual(s.split(), ["hello", "world"])
        # check that s.split fails when the separator is not a string
        with self.assertRaises(TypeError):
            s.split(2)

        self.assertRaisesRegex(
            ValueError, "invalid literal for.*XYZ'$", int, "XYZ"
        )
        with self.assertRaisesRegex(ValueError, "literal"):
            int("XYZ")

    def test_default_widget_size(self):
        widget = "The widget"
        self.assertEqual(len(widget), (50, 50))

    def test_even(self):
        """
        Test that numbers between 0 and 5 are all even.
        """
        for i in range(0, 6):
            with self.subTest(i=i):
                self.assertEqual(i % 2, 0)

    def test_warn(self):
        self.assertWarnsRegex(
            DeprecationWarning, r"len\(\) is deprecated", len, "XYZ"
        )

        with self.assertWarnsRegex(RuntimeWarning, "unsafe frobnicating"):
            len("/etc/passwd")
