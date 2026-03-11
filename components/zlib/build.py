# components/zlib/build.py
from kiln.builders.base import CMakeBuild

class ZlibBuild(CMakeBuild):
    name    = 'zlib'
    version = '1.3.2'
    cmake_generator = 'Unix Makefiles'
    deps    = []
    source  = {
        'url': 'https://zlib.net/zlib-1.3.2.tar.gz'
    }
    configure_args = ['-DCMAKE_BUILD_TYPE=Release']