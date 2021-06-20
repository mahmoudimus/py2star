import ast

import libcst as cst
import pytest


_DATA_DIR = "tests/data"


@pytest.fixture()
def fixture_file() -> str:
    return f"{_DATA_DIR}/fixture_data.py"


def _simple_fixture():
    v = None
    with open(f"{_DATA_DIR}/simple_class.py") as f:
        v = f.read()
    return v


@pytest.fixture()
def simple_class():
    return _simple_fixture()


@pytest.fixture(scope="class")
def simple_class_before(request):
    request.cls.before_transform = _simple_fixture()


@pytest.fixture()
def sample_test():
    v = None
    with open(f"{_DATA_DIR}/sample_test.py") as f:
        v = f.read()
    return v


@pytest.fixture()
def toplevel_func_fixture():
    v = None
    with open(f"{_DATA_DIR}/toplevelfunctions.py") as f:
        v = f.read()
    return v


@pytest.fixture()
def program(simple_class) -> ast.Module:
    m = ast.parse(simple_class)
    return m


@pytest.fixture()
def source_tree(simple_class):
    return cst.parse_module(simple_class)


@pytest.fixture()
def complex_class(sample_test):
    return ast.parse(sample_test)


@pytest.fixture()
def toplevel_functions(toplevel_func_fixture):
    return ast.parse(toplevel_func_fixture)


@pytest.fixture()
def fixture(fixture_file):
    with open(fixture_file) as f:
        return f.read()


@pytest.fixture()
def lib2to3_xfrms():
    return r"""
load("@stdlib//pytest","pytest")
load("@stdlib//re","re")
load("@vendor//asserts","asserts")
load("@stdlib//unittest","unittest")


def AES(key, mode, nonce=None):
    print(key, mode, nonce)
    raise ValueError(f"{key}, {mode}, {nonce}")


def RewriteMe_bar(self, q, w, z):
        # this does some stuff
    return [q, w, z]

def RewriteMe_xor(self, baz):
        # multi
        # line
        # comment
    pass

def RewriteMe_write(self):
    return self.__dict__.get("foo")

def RewriteMe_do_it(self):
    x = b"foo"
    return x

def RewriteMe_do_it2(self):
    x = b"fxxx\x80"
    return x

def RewriteMe_do_it3(self):
    x = b"\x01\x00\x10\x80"
    return x

def RewriteMe_do_it4(self):
    x = b"fo0\x7F"
    return x

def RewriteMe_test_success(self):
    asserts.assert_that(1).is_equal_to(1)

def RewriteMe_test_fail(self):
    asserts.assert_that(1).is_equal_to(2)

def RewriteMe_test_doit(self):
    asserts. re.search("her.*", "herpa"), "could not find herpa"

def RewriteMe_test_fstring(self) -> str:
    foo = 1
    return f"{foo}"

def RewriteMe_test_raises(self):
    key_128 = 128
    MODE_GCM = "gcm"
    asserts.assert_fails(lambda : AES(key_128, MODE_GCM, nonce=b""), ".*?ValueError")

def RewriteMe_test_bool(self):
    v1, v2, v3, v4 = (0, 10, -9, 2 ** 10)
    asserts.assert_that(v1).is_false()
    asserts.assert_that(bool(v1)).is_false()
    asserts.assert_that(v2).is_true()
    asserts.assert_that(bool(v2)).is_true()
    asserts.assert_that(v3).is_true()
    asserts.assert_that(v4).is_true()"""
