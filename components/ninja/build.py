from kiln.builders import CMakeBuild

class Ninja(CMakeBuild):
    name    = 'ninja'
    version = '1.12.1'
    deps    = ['glibc', 'linux-headers', 'cmake']
    source  = {
        'url': 'https://github.com/ninja-build/ninja/archive/refs/tags/v1.12.1.tar.gz',
    }
    configure_args = [
        '-DCMAKE_INSTALL_PREFIX=/usr',
        '-DBUILD_TESTING=OFF',
    ]
