from kiln.builders import CMakeBuild

class CMake(CMakeBuild):
    name    = 'cmake'
    version = '3.31.6'
    deps    = ['glibc', 'linux-headers', 'zlib', 'openssl']
    source  = {
        'url': 'https://cmake.org/files/v3.31/cmake-3.31.6.tar.gz',
    }
    
    configure_args = [
       '-DCMAKE_USE_OPENSSL=ON',
       '-DZLIB_ROOT={sysroot}/usr',
       '-DOPENSSL_ROOT_DIR={sysroot}/usr',
       '-DBUILD_TESTING=OFF',
       '-DCMAKE_BUILD_TYPE=Release',
       '-DCMAKE_USE_SYSTEM_ZLIB=ON',      # use sysroot zlib, not bundled
       '-DCMAKE_USE_SYSTEM_CURL=OFF',     # keep bundled curl (no curl in sysroot)
    ]
