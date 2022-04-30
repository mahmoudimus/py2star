import os
import base64
import argparse

# root_dir = "/Users/mahmoud/src/py/OpenPGP-Python/tests/data"
# output_dir = (
#     "/Users/mahmoud/src/starlarky/larky/src/test/resources/vendor_tests/OpenPGP"
# )
fixtures = {}


def add_fixture(filename):
    with open(filename, "rb") as fixture:
        fixtures[os.path.basename(filename)] = base64.b64encode(fixture.read())


def serialize_fixture_to_file(output_dir, fixture_name):
    output_dir = os.path.join(output_dir, fixture_name)
    with open(output_dir, "w+") as larky_fixture:
        larky_fixture.write(repr(fixtures))
        larky_fixture.flush()


def pack_fixture(root_dir, output_dir, fixture_name="data_test_fixtures.star"):
    for filename in os.listdir(root_dir):
        add_fixture(os.path.join(root_dir, filename))

    serialize_fixture_to_file(output_dir, fixture_name)


def execute(args):
    pack_fixture(args.root_dir, args.output_dir, args.fixture_name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="", add_help=False)
    parser.add_argument("root-dir", dest="root_dir")
    parser.add_argument("output-dir", dest="output_dir")
    parser.add_argument("fixture-filename", dest="fixture_name", required=False, default="data_test_fixtures.star")
    args = parser.parse_args()
    execute(args)