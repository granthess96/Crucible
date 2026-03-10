from kiln.builders.base import AutotoolsBuild

class Grep(AutotoolsBuild):
    name    = 'grep'
    version = '3.11'
    deps    = ['pcre2', 'gnulib', 'glibc']
    source  = {
        'git': 'https://git.savannah.gnu.org/git/grep.git',
        'ref': 'v3.11',
    }

    def configure_script(self, paths: BuildPaths) -> str:
        return f"""
cd {paths.source}
GNULIB_SRCDIR={paths.sysroot}/usr/share/gnulib ./bootstrap --no-git --skip-po
cd {paths.build}
{paths.source}/configure --prefix=/usr
"""
