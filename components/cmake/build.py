from kiln.builders import AutotoolsBuild

class CMake(AutotoolsBuild):
    name    = 'cmake'
    version = '3.31.6'
    deps    = ['glibc', 'linux-headers', 'zlib', 'openssl']
    source  = {
        'url': 'https://cmake.org/files/v3.31/cmake-3.31.6.tar.gz',
    }
    configure_args = [
        '--prefix=/usr',
        '--sysroot=/sysroot',
        '--parallel=$(nproc)',
        '--no-system-jsoncpp',
        '--no-system-librhash',
        '--system-zlib',
        '--system-openssl',
        '--with-zlib=/sysroot/usr',
        '--with-openssl=/sysroot/usr',
    ]