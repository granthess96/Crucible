from kiln.builders import AutotoolsBuild
from kiln.spec import FileSpec


class GlibcBuild(AutotoolsBuild):
    name    = "glibc"
    version = "2.38"
    deps    = ['linux-headers']
    build_weight  = 6
    source  = {
        "url": "https://ftp.gnu.org/gnu/glibc/glibc-2.38.tar.xz"
    }

    configure_args = [
        '--enable-kernel=6.1',
        '--disable-werror',
        '--with-headers=/{sysroot}/usr/include',
    ]

    c_flags   = ["-O2", "-D_FORTIFY_SOURCE=2"]
    cxx_flags = ["-O2", "-D_FORTIFY_SOURCE=2"]
    link_flags = ["-Wl,-z,relro"]

    # -------------------------------------------------------------------------
    # FileSpec overrides for glibc packaging
    # -------------------------------------------------------------------------
    # Glibc installs into a multiarch layout under lib64/x86_64-linux-gnu/.
    # Path inference handles most files correctly, but glibc has special cases:
    #
    # 1. ld-linux-x86-64.so.2 (the dynamic loader):
    #    - Role: runtime (primary use case as ELF interpreter)
    #    - Note: versioned .so files normally go to runtime, which is correct here
    #
    # 2. gconv/ modules (iconv locale conversion):
    #    - Role: runtime (loaded at runtime by iconv_open())
    #    - Absence causes locale failures in downstream components
    #
    # 3. usr/libexec/pt_chown and other helper executables:
    #    - Role: runtime (support utilities called at runtime)
    #
    # 4. var/db/Makefile (locale database build helper):
    #    - Role: exclude (harmless but not needed in final package)
    # -------------------------------------------------------------------------

    files = [
        # gconv modules are runtime data (needed for locale support)
        FileSpec("**/gconv/**", role="runtime"),

        # libexec utilities are runtime support tools
        FileSpec("usr/libexec/**", role="runtime"),

        # Exclude build-time locale database helpers
        FileSpec("var/db/Makefile", role="exclude"),
    ]
