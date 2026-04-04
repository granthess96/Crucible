# components/mpfr/build.py
from kiln.builders import AutotoolsBuild
from kiln.builders.base import BuildPaths

class MPFR(AutotoolsBuild):
    name    = 'mpfr'
    version = '4.2.1'
    deps    = ['gmp', 'glibc', 'linux-headers']
    source  = {
        'url': 'https://www.mpfr.org/mpfr-4.2.1/mpfr-4.2.1.tar.xz',
    }
    configure_args = [
        '--with-gmp={sysroot}/usr',
    ]

    def install_script(self, paths: BuildPaths) -> str:
        return f"""\
make DESTDIR={paths.install} install

find {paths.install} -name '*.la' | while read la; do
    sed -i \\
        -e "s|libdir='/usr/lib64'|libdir='{paths.sysroot}/usr/lib64'|g" \\
        -e "s| /usr/lib64/| {paths.sysroot}/usr/lib64/|g" \\
        -e "s|libdir='/usr/lib'|libdir='{paths.sysroot}/usr/lib'|g" \\
        -e "s| /usr/lib/| {paths.sysroot}/usr/lib/|g" \\
        "$la"
done
"""
