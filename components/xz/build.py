from kiln.builders.base import AutotoolsBuild, BuildPaths

class Xz(AutotoolsBuild):
    name    = 'xz'
    version = '5.2.5'
    deps    = ['gnulib', 'glibc']
    source  = {
        'git': 'https://github.com/tukaani-project/xz.git',
        'ref': 'v5.2.5',
    }
    
    def configure_script(self, paths: BuildPaths) -> str:
        return f"""
cd {paths.source}
GNULIB_SRCDIR={paths.sysroot}/usr/share/gnulib ./autogen.sh
cd {paths.build}
{paths.source}/configure --prefix=/usr
"""    