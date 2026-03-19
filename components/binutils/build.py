# components/binutils/build.py
from kiln.builders import AutotoolsBuild

class Binutils(AutotoolsBuild):
    name    = 'binutils'
    version = '2.44'
    deps    = []
    source  = {
        'url': 'https://ftp.gnu.org/gnu/binutils/binutils-2.44.tar.xz',
    }
    configure_args = [
        '--enable-shared',
        '--enable-plugins',
        '--disable-werror',
    ]
