from kiln.builders import AutotoolsBuild, BuildPaths

class Python3(AutotoolsBuild):
    name    = 'python3'
    version = '3.13.2'
    deps    = ['glibc', 'linux-headers', 'zlib']
    source  = {
        'url': 'https://www.python.org/ftp/python/3.13.2/Python-3.13.2.tar.xz',
    }
    configure_args = [
        '--without-ensurepip',
        '--disable-test-modules',
        '--without-decimal-contextvar',
        '--disable-ipv6',
        '--without-ssl',
        '--without-readline',
        '--without-curses',
        '--without-dbm',
        '--without-gdbm',
        '--without-tkinter',
        '--with-zlib=/{sysroot}/usr',
    ]
