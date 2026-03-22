# components/openssl/build.py
from kiln.builders import AutotoolsBuild, BuildPaths

class OpenSSL(AutotoolsBuild):
    name    = 'openssl'
    version = '3.4.1'
    deps    = ['zlib' , 'linux-headers', 'glibc']
    source  = {
        'url': 'https://github.com/openssl/openssl/releases/download/openssl-3.4.1/openssl-3.4.1.tar.gz',
    }

    def configure_command(self, paths: BuildPaths) -> list[str]:
        sysroot = paths.sysroot
        return [
            f'{paths.source}/Configure',
            '--prefix=/usr',
            f'--with-zlib-include={sysroot}/usr/include',
            f'--with-zlib-lib={sysroot}/usr/lib64',
            'zlib', 'shared', 'linux-x86_64',
            f'--sysroot={sysroot}',
            f'-isystem{sysroot}/usr/include',
            f'-L{sysroot}/usr/lib64',
            f'-Wl,--sysroot={sysroot}',
            '-fPIC',
            '-O2',
        ]

    def install_command(self, paths: BuildPaths) -> list[str]:
        return ['make', f'DESTDIR={paths.install}', 'install_sw']
