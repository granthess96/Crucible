from kiln.builders import AutotoolsBuild, BuildPaths

class GCC(AutotoolsBuild):
    name    = 'gcc'
    version = '13.2.0'
    deps    = ['gmp', 'mpfr', 'mpc', 'binutils', 'glibc', 'linux-headers', 'zlib', "libxcrypt"]
    source  = {
        'url': 'https://ftp.gnu.org/gnu/gcc/gcc-13.2.0/gcc-13.2.0.tar.xz',
    }
    configure_args = [
        '--enable-languages=c,c++',
        '--disable-multilib',
        '--enable-shared',
        '--disable-bootstrap',
        '--with-system-zlib',
        '--with-gmp={sysroot}/usr',
        '--with-mpfr={sysroot}/usr',
        '--with-mpc={sysroot}/usr',
        '--with-sysroot={sysroot}',
        '--with-build-sysroot={sysroot}',
        '--with-native-system-header-dir=/usr/include',
        'CFLAGS_FOR_TARGET=-O2 -fPIC --sysroot={sysroot} -isystem{sysroot}/usr/include',
        'CXXFLAGS_FOR_TARGET=-O2 -fPIC --sysroot={sysroot} -isystem{sysroot}/usr/include',
        'LDFLAGS_FOR_TARGET=-B{sysroot}/usr/lib64/ -L{sysroot}/usr/lib64/ -L{sysroot}/lib64/',
    ]
    
    build_env = {
        "LIBRARY_PATH": "{sysroot}/usr/lib64:{sysroot}/lib64",
    }

    buildtime_globs = AutotoolsBuild.buildtime_globs + [
        "usr/lib64/gcc/**",           # all gcc internal headers, plugins, crt files
        "usr/lib64/*.la",             # libtool archives (already in base after fix)
        "usr/lib64/*.spec",           # gcc spec files
   ]
