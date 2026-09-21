"""Build the required Oniguruma extension for wheels and editable installs."""

import runpy
import sysconfig
from pathlib import Path
from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if self.target_name != 'wheel':
            return
        root = Path(self.root)
        builder = runpy.run_path(str(root / 'native/build.py'))['build_native']
        binary = builder(root, inplace=version == 'editable')
        if version == 'editable':
            # Hatch points at src; the required extension has been built there.
            return
        suffix = sysconfig.get_config_var('EXT_SUFFIX')
        build_data['pure_python'] = False
        build_data['infer_tag'] = True
        build_data['force_include'][str(binary)] = f'hilite/_oniguruma{suffix}'
        build_data['force_include'][str(root / 'native/vendor/oniguruma/COPYING')] = (
            'hilite/licenses/ONIGURUMA.txt'
        )
        build_data['force_include'][str(root / 'native/licenses')] = 'hilite/licenses/rust'
        build_data['force_include'][str(root / 'native/vendor/oniguruma/VERSION.json')] = (
            'hilite/licenses/oniguruma-version.json'
        )
