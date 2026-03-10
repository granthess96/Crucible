from kiln.builders.base import AutotoolsBuild

class Readline(AutotoolsBuild):
    name    = 'readline'
    version = '8.2'
    deps    = ['ncurses']
    source  = {
        'git': 'https://git.savannah.gnu.org/git/readline.git',
        'ref': 'readline-8.2'

    }
