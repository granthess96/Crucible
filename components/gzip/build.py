from kiln.builders.base import AutotoolsBuild, BuildPaths

class Gzip(AutotoolsBuild):
    name    = 'gzip'
    version = '1.12'
    deps    = ['gnulib', 'glibc']
    source  = {
        'git': 'https://git.savannah.gnu.org/git/gzip.git',
        'ref': 'v1.12',
    }

    def configure_script(self, paths: BuildPaths) -> str:
        return f"""
cd {paths.source}
GNULIB_SRCDIR={paths.sysroot}/usr/share/gnulib ./bootstrap --no-git --skip-po
cd {paths.build}
{paths.source}/configure --prefix=/usr
"""