"""
Runs each program in tests/e2e/ with CPython, larkifies it, runs the result
in Larky, and compares what they print.

Needs Java and a starlarky build; skipped unless LARKY_JAR points at
starlarky's larky/target/larky-*-jar-with-dependencies.jar. A program can
set pipeline options on its first line:

    # options: use_mutablestruct=True
"""
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

from py2star import pipeline

HERE = pathlib.Path(__file__).parent
PROGRAMS = sorted((HERE / "e2e").glob("*.py"))
LARKY_JAR = os.environ.get("LARKY_JAR")

pytestmark = pytest.mark.skipif(
    not LARKY_JAR or not shutil.which("javac"),
    reason="set LARKY_JAR to a starlarky jar-with-dependencies (needs a JDK)",
)


@pytest.fixture(scope="session")
def runner(tmp_path_factory):
    out = tmp_path_factory.mktemp("runner")
    subprocess.run(
        ["javac", "-cp", LARKY_JAR, "-d", str(out), str(HERE / "larky" / "RunStar.java")],
        check=True,
    )
    return ["java", "-cp", f"{LARKY_JAR}{os.pathsep}{out}", "RunStar"]


def _options(source):
    match = re.match(r"# options: (.*)", source)
    return eval(f"dict({match.group(1)})") if match else {}


def _normalize(lines):
    # CPython reprs strings with single quotes, Larky with double quotes
    return [line.replace("'", '"') for line in lines]


@pytest.mark.parametrize("program", PROGRAMS, ids=[p.stem for p in PROGRAMS])
def test_program(program, runner, tmp_path):
    source = program.read_text()
    expected = subprocess.run(
        [sys.executable, str(program)], capture_output=True, text=True, check=True
    ).stdout.splitlines()

    star = tmp_path / f"{program.stem}.star"
    options = pipeline.Options(**_options(source))
    star.write_text(pipeline.larkify(source, options=options).code)
    result = subprocess.run(runner + [str(star)], capture_output=True, text=True)

    assert f"OK {star}" in result.stdout, result.stdout + result.stderr
    printed = [
        re.sub(r"^\d{4} [\d:.]+ INFO: ", "", line)
        for line in result.stdout.splitlines()
        if " INFO: " in line
    ]
    assert _normalize(printed) == _normalize(expected)
