# components/tar/build.py
from kiln.builders.base import AutotoolsBuild

class Tar(AutotoolsBuild):
    name    = 'tar'
    version = '1.35'
    deps    = ['glibc']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/tar/tar-1.35.tar.xz',
    }
    
    
    def configure_script(self, paths: BuildPaths) -> str:
        return f"""
cd {paths.build}
FORCE_UNSAFE_CONFIGURE=1 {paths.source}/configure --prefix=/usr
"""