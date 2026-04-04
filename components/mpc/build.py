# components/mpc/build.py
from kiln.builders import AutotoolsBuild

class MPC(AutotoolsBuild):
    name    = 'mpc'
    version = '1.3.1'
    deps    = ['gmp', 'mpfr', 'glibc', 'linux-headers']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/mpc/mpc-1.3.1.tar.gz',
    }
    configure_args = [
        '--with-gmp={sysroot}/usr',
        '--with-mpfr={sysroot}/usr',
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

