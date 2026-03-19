from kiln.builders import AutotoolsBuild, BuildPaths

class CoreUtils(AutotoolsBuild):
    name    = 'coreutils'
    version = '9.10'
    deps    = ['glibc', 'ncurses']
    source  = {
        'url' : 'https://ftp.gnu.org/gnu/coreutils/coreutils-9.10.tar.xz'                
    }

    def configure_script(self, paths: BuildPaths) -> str:
        return f"""
cd {paths.build}
FORCE_UNSAFE_CONFIGURE=1 {paths.source}/configure --prefix=/usr
"""
