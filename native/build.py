"""Build the Oniguruma extension with Cargo; --inplace refreshes a local checkout."""

import os
import sys
import shutil
import argparse
import sysconfig
from pathlib import Path
from subprocess import run


def build_native(root: Path, *, inplace: bool = False) -> Path:
    environment = os.environ.copy()
    environment['PYO3_PYTHON'] = sys.executable
    target = root / 'native' / 'target'
    environment['CARGO_TARGET_DIR'] = str(target)
    run(
        [
            'cargo',
            'build',
            '--release',
            '--locked',
            '--manifest-path',
            str(root / 'native/Cargo.toml'),
        ],
        env=environment,
        check=True,
    )
    if sys.platform == 'win32':
        filename = '_oniguruma.dll'
    elif sys.platform == 'darwin':
        filename = 'lib_oniguruma.dylib'
    else:
        filename = 'lib_oniguruma.so'
    binary = target / 'release' / filename
    if inplace:
        destination = root / 'src/hilite' / ('_oniguruma' + sysconfig.get_config_var('EXT_SUFFIX'))
        shutil.copy2(binary, destination)
        return destination
    return binary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inplace', action='store_true')
    arguments = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    print(build_native(project, inplace=arguments.inplace))
