from kiln.builders.base import AutotoolsBuild, BuildPaths

class CoreUtils(AutotoolsBuild):
    name    = 'coreutils'
    version = '9.5'
    deps    = ['gnulib', 'glibc', 'ncurses']
    source  = {
        'git': 'https://git.savannah.gnu.org/git/coreutils.git',
        'ref': 'v9.5',
    }

    def configure_script(self, paths: BuildPaths) -> str:
        return f"""
cd {paths.source}
GNULIB_SRCDIR={paths.sysroot}/usr/share/gnulib ./bootstrap --no-git --skip-po
./configure --prefix=/usr
"""