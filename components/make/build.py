from kiln.builders.base import AutotoolsBuild, BuildPaths

class GMake(AutotoolsBuild):
    name    = 'make'
    version = '4.3'
    deps    = ['gnulib', 'glibc']
    source  = {
        'git': 'https://git.savannah.gnu.org/git/make.git',
        'ref': 'v4.3',
    }

    def configure_script(self, paths: BuildPaths) -> str:
        return f"""
cd {paths.source}
GNULIB_SRCDIR={paths.sysroot}/usr/share/gnulib ./bootstrap --no-git --skip-po
cd {paths.build}
{paths.source}/configure --prefix=/usr
"""