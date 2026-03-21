from kiln.builders import ScriptBuild, BuildPaths

class Gnulib(ScriptBuild):
    name    = 'gnulib'
    version = '2024-a65f999'   # date or short SHA for human readability
    deps    = ['glibc', 'linux-headers']
    source  = {
        'git': 'https://git.savannah.gnu.org/git/gnulib.git',
        'ref': 'a65f999035e18eb802e5cf8b624ae15620ee67fa',
    }

    def configure_command(self, paths: BuildPaths) -> list[str]:
        return []

    def build_command(self, paths: BuildPaths) -> list[str]:
        return []

    def install_script(self, paths: BuildPaths) -> str:
        return f"""
mkdir -p {paths.install}/usr/share/gnulib
cp -a {paths.source}/. {paths.install}/usr/share/gnulib/
"""

    # Override globs — gnulib is a source tree, not a normal library
    runtime_globs   = []
    buildtime_globs = ['usr/share/gnulib/**']
