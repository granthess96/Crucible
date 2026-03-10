from kiln.builders.base import AutotoolsBuild

class Sed(AutotoolsBuild):
    name    = 'sed'
    version = '4.9'
    deps    = ['gnulib', 'glibc']
    source  = {
        'git': 'https://git.savannah.gnu.org/git/sed.git',
        'ref': 'v4.9',
    }

    def configure_script(self, paths: BuildPaths) -> str:
        return f"""
cd {paths.source}
GNULIB_SRCDIR={paths.sysroot}/usr/share/gnulib ./bootstrap --no-git --skip-po
./configure --prefix=/usr
"""