from kiln.builders import AutotoolsBuild

class M4(AutotoolsBuild):
    name    = 'm4'
    version = '1.4.20'
    deps    = ['glibc', 'linux-headers']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/m4/m4-1.4.20.tar.xz',
    }
    configure_args = [
        '--prefix=/usr',
        '--disable-nls',
    ]
