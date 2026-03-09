import os
from kiln.builders.base import ScriptBuild, BuildPaths

class LinuxHeaders(ScriptBuild):
    name    = 'linux-headers'
    version = '6.12'
    deps    = []
    source  = {
        'git': 'https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git',
        'ref': 'v6.12',
    }

    def build_script(self, paths: BuildPaths) -> str:
        return f"""
cd {paths.source}
make headers_install ARCH=x86_64 INSTALL_HDR_PATH={paths.install}/usr
"""

    def configure_command(self, paths: BuildPaths) -> list[str]:
        return []   # no configure step

    def install_command(self, paths: BuildPaths) -> list[str]:
        return []   # install happens in build_script
