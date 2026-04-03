# components/bash/build.py
from kiln.builders import AutotoolsBuild
from kiln.builders.base import BuildPaths

class BashBuild(AutotoolsBuild):
    name    = 'bash'
    version = '5.3'
    deps    = ['glibc', 'ncurses', 'readline', 'linux-headers']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/bash/bash-5.3.tar.gz',
    }
    configure_args = [
        '--without-bash-malloc',
        '--with-curses',
        '--enable-readline',
        '--disable-loadables',
        '--disable-examples',
    ]

    def install_script(self, paths: BuildPaths) -> str:
        return f"""\
make DESTDIR={paths.install} install

# /bin/sh symlink — assumed present by virtually every build system.
# Bash does not create it; we must.
ln -sf bash {paths.install}/usr/bin/sh
mkdir -p {paths.install}/bin
ln -sf ../usr/bin/bash {paths.install}/bin/sh
"""
