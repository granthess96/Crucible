from kiln.builders import AutotoolsBuild

class Readline(AutotoolsBuild):
    name    = 'readline'
    version = '8.2'
    deps    = ['glibc', 'linux-headers', 'ncurses']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/readline/readline-8.2.tar.gz',
    }

    configure_args = [
        '--with-curses={sysroot}/usr',
        '--enable-shared',
    ]
