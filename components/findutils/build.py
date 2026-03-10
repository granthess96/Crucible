from kiln.builders.base import AutotoolsBuild

class Findutils(AutotoolsBuild):
    name    = 'findutils'
    version = '4.10.0'
    deps    = ['gnulib']
    source  = {
        'git': 'https://git.savannah.gnu.org/git/findutils.git',
        'ref': 'v4.10.0',
    }

    def configure_script(self, paths: BuildPaths) -> str:
        return f"""
cd {paths.source}
GNULIB_SRCDIR={paths.sysroot}/usr/share/gnulib ./bootstrap --no-git --skip-po
./configure --prefix=/usr
"""

