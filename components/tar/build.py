from kiln.builders.base import AutotoolsBuild

class Tar(AutotoolsBuild):
    name    = 'tar'
    version = '1.34'
    deps    = ['gnulib', 'glibc']
    source  = {
        'git': 'https://git.savannah.gnu.org/git/tar.git',
        'ref': 'release_1_34',
    }
    
    def configure_script(self, paths: BuildPaths) -> str:
        return f"""
cd {paths.source}
GNULIB_SRCDIR={paths.sysroot}/usr/share/gnulib ./bootstrap --no-git --skip-po
cd {paths.build}
{paths.source}/configure --prefix=/usr
"""