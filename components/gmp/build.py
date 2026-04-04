# components/gmp/build.py
from kiln.builders import AutotoolsBuild
from kiln.builders.base import BuildPaths

class GMP(AutotoolsBuild):
    name    = 'gmp'
    version = '6.3.0'
    deps    = ['glibc', 'linux-headers']
    source  = {
        'url': 'https://gmplib.org/download/gmp/gmp-6.3.0.tar.xz',
    }
    configure_args = [
        '--enable-cxx',
        '--enable-shared',
        '--enable-static',
    ]
    c_flags = ['-Wno-error=pedantic', '-std=gnu17', '-fPIC', '-DPIC']

    def install_script(self, paths: BuildPaths) -> str:
        return f"""\
make DESTDIR={paths.install} install

# Rewrite .la dependency paths from /usr/lib64 to sysroot-relative paths.
# Libtool records the install prefix at build time; downstream builds
# (mpfr, mpc, gcc) follow these paths and fail if they point outside the sysroot.
find {paths.install} -name '*.la' | while read la; do
    sed -i \\
        -e "s|libdir='/usr/lib64'|libdir='{paths.sysroot}/usr/lib64'|g" \\
        -e "s| /usr/lib64/| {paths.sysroot}/usr/lib64/|g" \\
        -e "s|libdir='/usr/lib'|libdir='{paths.sysroot}/usr/lib'|g" \\
        -e "s| /usr/lib/| {paths.sysroot}/usr/lib/|g" \\
        "$la"
done
"""
