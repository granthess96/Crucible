from kiln.builders.base import ScriptBuild, BuildPaths

class Perl(ScriptBuild):
    name    = 'perl'
    version = '5.40.0'
    deps    = ['glibc', 'linux-headers', 'zlib']
    source  = {
        'url': 'https://www.cpan.org/src/5.0/perl-5.40.0.tar.xz',
    }

    def configure_command(self, paths: BuildPaths) -> list[str]:
        return []

    def build_script(self, paths: BuildPaths) -> str:
        return f"""
cd {paths.source}
./Configure -des \
    -Dprefix=/usr \
    -Dsysroot={paths.sysroot} \
    -Dincpth={paths.sysroot}/usr/include \
    -Dlibpth={paths.sysroot}/usr/lib64 {paths.sysroot}/usr/lib \
    -Duseshrplib \
    -Dusethreads \
    -Doptimize='-O2' \
    -Dcc=gcc
make -j$(nproc)
"""

    def install_command(self, paths: BuildPaths) -> list[str]:
        return ['make', f'DESTDIR={paths.install}', 'install']
