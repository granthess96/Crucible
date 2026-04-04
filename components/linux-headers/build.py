# Kernel Headers for the Forge base image
import os
from kiln.builders import ScriptBuild, BuildPaths
from kiln.spec import FileSpec

class LinuxHeaders(ScriptBuild):
    name    = 'linux-headers'
    version = '6.12'
    deps    = []
    source  = {
        'url': 'https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.12.tar.xz',
    }

    # -------------------------------------------------------------------------
    # FileSpec: explicitly mark headers as development files
    # -------------------------------------------------------------------------
    # linux-headers only outputs kernel headers via `make headers_install`.
    # All files (usr/include/**) are development files by definition.
    # Path inference correctly classifies .h files as 'dev', so this FileSpec
    # is redundant but documents the intent: all outputs are dev-only.
    # -------------------------------------------------------------------------

    files = [
        # Kernel headers are always development files
        FileSpec("usr/include/**", role="dev"),
    ]

    def configure_command(self, paths: BuildPaths) -> list[str]:
        return []

    def build_script(self, paths: BuildPaths) -> str:
        return f"""
cd /bin
ln -sf bash sh
cd /usr
if [ ! -e "/usr/lib64" ]; then
  ln -s lib lib64
fi
cd {paths.source}
make ARCH=x86_64 \
     INSTALL_HDR_PATH={paths.install}/usr \
     HOSTCC="/usr/bin/gcc" \
     HOSTCFLAGS="-O2 -I/usr/include" \
     HOSTLDFLAGS="" \
     headers_install
"""

    def install_command(self, paths: BuildPaths) -> list[str]:
        return []
