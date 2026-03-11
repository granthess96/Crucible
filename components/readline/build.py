# components/readline/build.py
from kiln.builders.base import AutotoolsBuild

class Readline(AutotoolsBuild):
    name    = 'readline'
    version = '8.2'
    deps    = ['ncurses']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/readline/readline-8.2.tar.gz',
    }