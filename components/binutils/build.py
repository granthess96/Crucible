# components/binutils/build.py
from kiln.builders import AutotoolsBuild
from kiln.spec import FileSpec

class Binutils(AutotoolsBuild):
    name    = 'binutils'
    version = '2.44'
    deps    = ['glibc', 'linux-headers']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/binutils/binutils-2.44.tar.xz',
    }
    configure_args = [
        '--enable-shared',
        '--enable-plugins',
        '--disable-werror',
    ]

    files = [
        # Linker scripts — consumed at link time, not at runtime
        FileSpec("usr/lib64/ldscripts/**",              role="dev"),

        # BFD plugins — only meaningful in a build/tool environment
        FileSpec("usr/lib64/bfd-plugins/**",            role="tool"),

        # Target-triple-prefixed tree (e.g. usr/x86_64-linux-gnu/)
        # Linker scripts within it are dev; everything else is tool.
        FileSpec("usr/*/lib/ldscripts/**",              role="dev"),
        FileSpec("usr/*/*/ldscripts/**",                role="dev"),
        FileSpec("usr/*/bin/**",                        role="tool"),
        FileSpec("usr/*/lib/**",                        role="dev"),

        # User-facing binutils executables
        FileSpec("usr/bin/**",                          role="tool"),
    ]
