from kiln.builders.base import CMakeBuild

class LibPNG(CMakeBuild):
    name    = 'libpng'
    version = '1.6.43'
    deps    = ['zlib']
    cmake_generator = 'Unix Makefiles'
    source  = {
        'git': 'https://github.com/pnggroup/libpng',
        'ref': 'v1.6.43',
    }
    configure_args = [
        '-DPNG_BUILD_ZLIB=OFF',
        '-DZLIB_ROOT=/workspace/components/libpng/__sysroot__/usr',
    ]
    
    

