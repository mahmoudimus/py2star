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
def source_tree(simple_class):
    return cst.parse_module(simple_class)


@pytest.fixture()
def fixture(fixture_file):
    with open(fixture_file) as f:
        return f.read()
