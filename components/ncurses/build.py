# components/ncurses/build.py
from kiln.builders.base import AutotoolsBuild

class NcursesBuild(AutotoolsBuild):
    name    = 'ncurses'
    version = '6.5'
    deps    = ['glibc']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/ncurses/ncurses-6.5.tar.gz',
    }
    configure_args = [
        '--with-shared',
        '--enable-widec',
        '--with-cxx-binding',
        '--with-cxx-shared',
        '--without-ada',
        '--enable-pc-files',
        '--disable-db-install',
        '--with-bool=bool',
    ]
    comp_flags = ['-O2', '-std=c++17', '-std=gnu17']
