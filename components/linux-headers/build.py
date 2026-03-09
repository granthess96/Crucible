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

    def configure_command(self, paths: BuildPaths) -> list[str]:
        return []

    def build_script(self, paths: BuildPaths) -> str:
        return f"""
cd {paths.source}
make headers_install ARCH=x86_64 INSTALL_HDR_PATH={paths.install}/usr
"""

    def install_command(self, paths: BuildPaths) -> list[str]:
        return []