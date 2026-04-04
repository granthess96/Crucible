from kiln.builders import AutotoolsBuild
from kiln.spec import FileSpec

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
        "LIBRARY_PATH": "{sysroot}/usr/lib64:{sysroot}/lib64:{sysroot}/usr/lib:{sysroot}/lib",
    }

    # -------------------------------------------------------------------------
    # FileSpec overrides for GCC packaging
    # -------------------------------------------------------------------------
    # GCC's internal structure is complex because it contains:
    # 1. Host tools (cc1, collect2) -> 'tool'
    # 2. Target runtime libs (libgcc_s.so) -> 'runtime'
    # 3. Development headers/objects (crtbegin.o, unwind.h) -> 'dev'
    # -------------------------------------------------------------------------
    files = [
        # 1. Main Binaries (the compiler driver)
        FileSpec("usr/bin/**", role="tool"),

        # 2. GCC Internal Directory (The heart of the compiler)
        # This contains cc1, collect2 (tool), but also crt*.o and headers (dev)
        # We classify the whole tree as 'tool' and then override specific dev parts.
        FileSpec("usr/lib/gcc/**", role="tool"),
        FileSpec("usr/lib64/gcc/**", role="tool"),
        
        # Override: Static libs and objects within the gcc tree are for development
        FileSpec("usr/lib/gcc/**/*.[ao]", role="dev"),
        FileSpec("usr/lib64/gcc/**/*.[ao]", role="dev"),
        FileSpec("usr/lib/gcc/**/include/**", role="dev"),
        FileSpec("usr/lib64/gcc/**/include/**", role="dev"),

        # 3. Runtime Libraries
        # libgcc_s, libstdc++, etc. The .so.major files are runtime.
        # Note: path_role() usually handles .so.1 correctly, but we ensure it here.
        FileSpec("usr/lib64/*.so.*", role="runtime"),
        
        # 4. Development Symlinks and Archives
        # The .so symlinks and .a archives are strictly for linking.
        FileSpec("usr/lib64/*.so", role="dev"),
        FileSpec("usr/lib64/*.a", role="dev"),
        
        # 5. Metadata and Build Artifacts
        FileSpec("usr/lib64/*.la", role="exclude"),
        FileSpec("usr/lib64/*.spec", role="dev"),  # GCC specs are used at link-time
    ]
