# components/openssl/build.py
from kiln.builders.base import AutotoolsBuild, BuildPaths

class OpenSSL(AutotoolsBuild):
    name    = 'openssl'
    version = '3.4.1'
    deps    = ['zlib']
    source  = {
        'url': 'https://github.com/openssl/openssl/releases/download/openssl-3.4.1/openssl-3.4.1.tar.gz',
    }

    def configure_command(self, paths: BuildPaths) -> list[str]:
        return [
            f'{paths.source}/Configure',
            f'--prefix=/usr',
            f'--with-zlib-include={paths.sysroot}/usr/include',
            f'--with-zlib-lib={paths.sysroot}/usr/lib64',
            'zlib', 'shared', 'linux-x86_64',
        ]

    def install_command(self, paths: BuildPaths) -> list[str]:
        return ['make', f'DESTDIR={paths.install}', 'install_sw']
