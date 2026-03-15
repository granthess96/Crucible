# components/libpng/build.py
from kiln.builders.base import CMakeBuild

class LibPNG(CMakeBuild):
    name    = 'libpng'
    version = '1.6.44'
    deps    = ['zlib']
    source  = {
        'url': 'https://download.sourceforge.net/libpng/libpng-1.6.44.tar.gz',
    }