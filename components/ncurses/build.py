from kiln.builders import AutotoolsBuild

class Ncurses(AutotoolsBuild):
    name    = 'ncurses'
    version = '6.5'
    deps    = ['glibc', 'linux-headers']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/ncurses/ncurses-6.5.tar.gz',
    }
    configure_args = [
        '--with-shared',
        '--without-debug',
        '--enable-widec',
        '--with-cxx-binding',
        '--without-ada',
    ]

    c_flags = ['-std=gnu17']
