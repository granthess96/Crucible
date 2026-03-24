from kiln.builders import AutotoolsBuild


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
    cxx_flags = ["-O2", "-D_FORTIFY_SOURCE=2"]   # fixed typo: _SORUCE -> _SOURCE
    link_flags = ["-Wl,-z,relro"]

    # -------------------------------------------------------------------------
    # Glibc installs into a multiarch layout under usr/lib/x86_64-linux-gnu/.
    # The base class globs cover *.so and *.so.* recursively, which catches
    # libc.so.6, libm.so.6, libpthread.so.0, ld-linux-x86-64.so.2 etc.
    #
    # Additions needed beyond the base class:
    #
    # runtime:
    #   gconv/          — iconv/locale conversion modules (.so files loaded
    #                     at runtime by iconv_open(); absence causes locale
    #                     failures in downstream components)
    #   usr/libexec/**  — pt_chown and other glibc helper executables
    #   var/db/Makefile — glibc locale database build helper (harmless to include)
    #
    # buildtime:
    #   **/*.o          — crt1.o, crti.o, crtn.o, Scrt1.o, gcrt1.o live in
    #                     usr/lib/x86_64-linux-gnu/ and are required to link
    #                     any C program. The base class covers *.o but be
    #                     explicit here for clarity.
    #   **/gconv/*.so   — some build systems probe gconv at configure time;
    #                     listed in both so a buildtime-only sysroot works too.
    # -------------------------------------------------------------------------

#    runtime_globs = AutotoolsBuild.runtime_globs + [
#        "usr/libexec/**",
#        "usr/lib/**/gconv/**",
#        "var/**",
#        "lib64/**",
#        "sbin/**",
#        "usr/libexec/**",
#        "usr/lib/***/gconv/**",
#        "usr/lib64/gconv/**",
#    ]

#    buildtime_globs = AutotoolsBuild.buildtime_globs + [
#        "usr/lib/**/*.o",
#        "usr/lib/**/gconv/**",
# ]
