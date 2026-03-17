from kiln.builders.base import AutotoolsBuild

class GlibcBuild(AutotoolsBuild):
    name    = "glibc"
    version = "2.38"
    deps    = ['linux-headers']
    weight  = 6
    source  = {
        "url": "https://ftp.gnu.org/gnu/glibc/glibc-2.38.tar.xz"
#        "git": "https://sourceware.org/git/glibc.git",
#        "ref": "glibc-2.42",
    }

    configure_args = [
        '--enable-kernel=6.1',
        '--disable-werror',
        '--with-headers=/workspace/components/glibc/__sysroot__/usr/include',
    ]
    
    comp_flags = ['-O2', "-D_FORTIFY_SOURCE=2"]   
    link_flags = ['-Wl,-z,relro']
