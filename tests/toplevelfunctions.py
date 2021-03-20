load("@stdlib//re", "re")
load("@vendor//asserts", "asserts")
load("@stdlib//builtins", "builtins")


def bar(q, w, z):
    return list(q, w, z)


def bar(baz):
    pass


def write():
    pass


def doit():
    x = builtins.bytes("foo")
    return x


def test_success():
    asserts.assert_that(1).is_equal_to(1)


def test_fail():
    asserts.assert_that(1).is_equal_to(2)


def test_doit():
    asserts.assert_that(re.search("her.*", "herpa")).is_not_None()


def test_fstring() -> str:
    foo = 1
    return f"{foo}"
