# components/bash/build.py
from kiln.builders.base import AutotoolsBuild

class BashBuild(AutotoolsBuild):
    name    = 'bash'
    version = '5.2'
    deps    = ['glibc', 'ncurses', 'readline']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/bash/bash-5.2.tar.gz',
    }
    configure_args = [
        '--without-bash-malloc',
        '--with-curses',
        '--enable-readline',
        '--disable-loadables',
        '--disable-examples',
    ]