from kiln.builders.base import AutotoolsBuild

class Bison(AutotoolsBuild):
    name    = 'bison'
    version = '3.8.2'
    deps    = ['glibc', 'linux-headers', 'm4']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/bison/bison-3.8.2.tar.xz',
    }
    configure_args = [
        '--prefix=/usr',
        '--sysroot=/sysroot',
        '--disable-nls',
    ]
