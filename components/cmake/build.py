from kiln.builders import CMakeBuild
from kiln.spec import FileSpec

class CMake(CMakeBuild):
    name    = 'cmake'
    version = '3.31.6'
    deps    = ['glibc', 'linux-headers', 'zlib', 'openssl', 'gcc', 'binutils', 'curl']
    source  = {
        'url': 'https://cmake.org/files/v3.31/cmake-3.31.6.tar.gz',
    }

    configure_args = [
        '-DCMAKE_USE_OPENSSL=ON',
        '-DZLIB_ROOT={sysroot}/usr',
        '-DOPENSSL_ROOT_DIR={sysroot}/usr',
        '-DBUILD_TESTING=OFF',
        '-DCMAKE_BUILD_TYPE=Release',
        '-DCMAKE_USE_SYSTEM_ZLIB=ON',
        '-DCMAKE_USE_SYSTEM_CURL=ON',
        # Lock find_* calls to sysroot only — prevents host library contamination
        '-DCMAKE_FIND_ROOT_PATH={sysroot}/usr',
        '-DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY',
        '-DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY',
        '-DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ONLY',
    ]

    #cxx_flags = ['-static-libgcc -static-libstdc++']

    files = [
        FileSpec("usr/bin/**",          role="tool"),
        FileSpec("usr/share/cmake*/**", role="tool"),
        FileSpec("usr/lib64/cmake/**",  role="dev"),
    ]
