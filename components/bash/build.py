# components/bash/build.py
from kiln.builders.base import AutotoolsBuild

class BashBuild(AutotoolsBuild):
    name    = 'bash'
    version = '5.3'
    deps    = ['glibc', 'ncurses', 'readline']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/bash/bash-5.3.tar.gz',
    }
    configure_args = [
        '--prefix=/usr',
        '--without-bash-malloc',
        '--with-curses',
        '--enable-readline',
        '--disable-loadables',
        '--disable-examples',
    ]
