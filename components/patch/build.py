from kiln.builders.base import AutotoolsBuild

class Patch(AutotoolsBuild):
    name    = 'patch'
    version = '2.7.6'
    deps    = ['glibc', 'linux-headers']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/patch/patch-2.7.6.tar.xz',
    }
    configure_args = [
        '--prefix=/usr',
        '--sysroot=/sysroot',
        '--disable-nls',
    ]
