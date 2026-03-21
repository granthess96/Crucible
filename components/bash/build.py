# components/bash/build.py
from kiln.builders import AutotoolsBuild

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
