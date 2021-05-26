import ast

import libcst as cst
import pytest


_DATA_DIR = "tests/data"


@pytest.fixture()
def fixture_file() -> str:
    return f"{_DATA_DIR}/fixture_data.py"


@pytest.fixture()
def simple_class():
    v = None
    with open(f"{_DATA_DIR}/simple_class.py") as f:
        v = f.read()
    return v


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
