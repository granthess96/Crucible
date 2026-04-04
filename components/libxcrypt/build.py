from kiln.builders import AutotoolsBuild

class Libxcrypt(AutotoolsBuild):
    name    = 'libxcrypt'
    version = '4.4.36'
    deps    = ['glibc', 'linux-headers']
    
    source  = {
        'url': 'https://github.com/besser82/libxcrypt/releases/download/v4.4.36/libxcrypt-4.4.36.tar.xz',
    }

    # --enable-obsolete-api is crucial if you are fixing a "crypt.h" 
    # issue for a GCC build or legacy software.
    configure_args = [
        '--enable-hashes=all',
        '--enable-obsolete-api=glibc',
        '--disable-static',
    ]

    c_flags = ['-O2']

    def finalize_build_flags(self):
        """Stage0 bootstrap requires additional flag; stage1+ doesn't."""
        if self.bootstrap_stage == 'stage0':
            self.c_flags = ['-O2', '-Wno-error=unterminated-string-initialization']
