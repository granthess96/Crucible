# components/zlib/build.py
from kiln.builders import CMakeBuild

class Zlib(CMakeBuild):
    name    = 'zlib'
    version = '1.3.2'
    cmake_generator = 'Unix Makefiles'
    deps    = ['glibc','linux-headers']
    source  = {
        'url': 'https://zlib.net/zlib-1.3.2.tar.gz'
    }

    configure_args = [
        '-DCMAKE_INSTALL_PREFIX=/usr',
    ]
