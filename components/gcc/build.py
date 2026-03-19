# components/gcc/build.py
import os
from kiln.builders import AutotoolsBuild, BuildPaths

sysroot_path = os.path.abspath('../__sysroot__')

class GCC(AutotoolsBuild):
    name    = 'gcc'
    version = '15.2.0'
    deps    = ['gmp', 'mpfr', 'mpc', 'binutils', 'glibc']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/gcc/gcc-15.2.0/gcc-15.2.0.tar.xz',
    }
    configure_args = [
        '--enable-languages=c,c++',
        '--disable-multilib',
        '--enable-shared',
#        '--disable-werror',
#        '--disable-bootstrap',
        '--with-system-zlib',
#        'CC=/opt/tools/gcc-10/bin/gcc10-gcc',
#        'CXX=/opt/tools/gcc-10/bin/gcc10-g++',
        '--with-gmp=../__sysroot__/usr',
        '--with-mpfr=../__sysroot__/usr',
        f'--with-mpc={sysroot_path}/usr',
        '--with-sysroot=/workspace/components/gcc/__sysroot__',
#        '--with-host-libstdcxx',
#        '--with-native-system-header-dir=/usr/include'

    ]
