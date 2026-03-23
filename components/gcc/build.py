import os
from kiln.builders import AutotoolsBuild, BuildPaths

class GCC(AutotoolsBuild):
    name    = 'gcc'
    version = '13.2.0'       # or '13.3.0'
    source  = {
        'url': 'https://ftp.gnu.org/gnu/gcc/gcc-13.2.0/gcc-13.2.0.tar.xz',
    }

    deps    = ['gmp', 'mpfr', 'mpc', 'binutils', 'glibc', 'linux-headers', 'zlib']

    configure_args = [
        '--enable-languages=c,c++',
        '--disable-multilib',
        '--enable-shared',
        '--disable-bootstrap',
        '--with-system-zlib',
        '--with-gmp={sysroot}/usr',
        '--with-mpfr={sysroot}/usr',
        '--with-mpc={sysroot}/usr',
        '--with-sysroot={sysroot}',
        '--with-native-system-header-dir=/usr/include',
	'--with-sysroot={sysroot}',
	'--with-build-sysroot={sysroot}',
        'LDFLAGS_FOR_TARGTE=-B{sysroot}/usr/lib64/',
    ]
