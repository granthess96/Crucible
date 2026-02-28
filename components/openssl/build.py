import os
from kiln.builders.base import AutotoolsBuild, BuildPaths

class OpenSSL(AutotoolsBuild):
    name    = 'openssl'
    version = '3.2.1'
    deps    = ['zlib']
    source  = {
        'git': 'https://github.com/openssl/openssl',
        'ref': 'openssl-3.2.1',
    }

    def configure_command(self, paths: BuildPaths) -> list[str]:
        return [
            f'{paths.source}/Configure',
            f'--prefix={paths.install}',
            f'--with-zlib-include={paths.sysroot}/usr/include',
            f'--with-zlib-lib={paths.sysroot}/usr/lib',
            'zlib', 'shared', 'linux-x86_64',
        ]

    def install_command(self, paths: BuildPaths) -> list[str]:
        return ['make', 'install_sw']   # skip docs/man pages
