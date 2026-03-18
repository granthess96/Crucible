from kiln.builders import AutotoolsBuild

class GlibcBuild(AutotoolsBuild):
    name    = "glibc"
    version = "2.38"
    deps    = ['linux-headers']
    weight  = 6
    source  = {
        "url": "https://ftp.gnu.org/gnu/glibc/glibc-2.38.tar.xz"
    }

    configure_args = [
        '--prefix=/usr',
        '--enable-kernel=6.1',
        '--disable-werror',
        '--with-headers=/workspace/components/glibc/__sysroot__/usr/include',
    ]
    
    c_flags = ["-O2", "-D_FORTIFY_SOURCE=2"]   
    cxx_flags = ["-O2", "-D_FORTIFY_SORUCE=2"]
    link_flags = ["-Wl,-z,relro"]
