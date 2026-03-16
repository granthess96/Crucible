# components/gcc/build.py
from kiln.builders.base import AutotoolsBuild, BuildPaths

class GCC(AutotoolsBuild):
    name    = 'gcc'
    version = '13.2.0'
    deps    = ['gmp', 'mpfr', 'mpc', 'binutils']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/gcc/gcc-13.2.0/gcc-13.2.0.tar.xz',
    }
    configure_args = [
        '--enable-languages=c,c++',
        '--disable-multilib',
        '--enable-shared',
        '--disable-werror',
        '--disable-bootstrap',
        '--with-system-zlib',
        'CC=/opt/tools/gcc-10/bin/gcc10-gcc',
        'CXX=/opt/tools/gcc-10/bin/gcc10-g++',
    ]
