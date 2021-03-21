import pathlib
import re
import sys
from glob import glob
from os.path import basename
from os.path import splitext

import setuptools

VERSION_FILE = 'py2star/__init__.py'
REQUIREMENTS = 'requirements.txt'
TEST_REQUIREMENTS = 'test-requirements.txt'


def _excluded(pathobj: pathlib.Path) -> bool:
    """
    Exclude certain directories or filenames from being found:

    if directory: x.as_posix().startswith()
    if filename: x.name.startswith()

    """
    return any((
        pathobj.as_posix().startswith('venv'),
        pathobj.as_posix().startswith('virtualenv'),
    ))


def _find_file(fname: str,
               directory: pathlib.Path = pathlib.Path('.')) -> pathlib.Path:
    """
    Find files relative to the directory parameter.
    """
    for filename in directory.glob('**/' + fname):
        if _excluded(filename):
            continue
        return filename
    else:
        raise FileNotFoundError(
            '{fname} could not be found, recursively'
            .format(fname=fname))


def _readlines(filename: str):
    lines = []
    try:
        filename = _find_file(filename)
        with open(filename.as_posix()) as f:
            for line in f:
                lines.append(line.replace('\n', ''))
    except (FileNotFoundError, IOError) as e:
        print(e, file=sys.stderr)
    return lines


extras_require = {
    'tests': _readlines(TEST_REQUIREMENTS)
}

setuptools.setup(
    name='py2star',
    version=(
        re.compile(r".*__version__ = (.*)", re.S)
            .match('\n'.join(_readlines(VERSION_FILE)))
            .group(1)
    ).strip('\"\''),
    url='https://github.com/mahmoudimus/py2star',
    license='BSD',
    author='mahmoudimus',
    author_email='mahmoud - @ - linux.com',
    description='',
    long_description='\n'.join(_readlines('README.md')),
    long_description_content_type="text/markdown",
    packages=setuptools.find_packages('src'),
    package_dir={'': 'src'},
    py_modules=[splitext(basename(path))[0] for path in glob('src/py2star/*.py')],
    include_package_data=True,
    zip_safe=False,
    platforms='any',
    install_requires=_readlines(REQUIREMENTS),
    extras_require=extras_require,
    setup_requires=['pytest-runner'],
    tests_require=extras_require['tests'],
    # entry_points={
    #         'console_scripts': [
    #             '{{ cookiecutter.command_line_interface_bin_name }} = {{ cookiecutter.package_name }}.cli:main',
    #         ]
    #     },
    classifiers=[
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Software Development :: Libraries :: Python Modules'
    ],
    # data_files=[
    #      ('', ['config.yaml'])
    # ]
)
