# components/libpng/build.py
from kiln.builders.base import CMakeBuild

class LibPNG(CMakeBuild):
    name    = 'libpng'
    version = '1.6.44'
    deps    = ['zlib']
    cmake_generator = 'Unix Makefiles'
    source  = {
        'url': 'https://download.sourceforge.net/libpng/libpng-1.6.44.tar.gz',
    }
    configure_args = [
        '-DPNG_BUILD_ZLIB=OFF',
        '-DZLIB_ROOT=/workspace/components/libpng/__sysroot__/usr',
    ]