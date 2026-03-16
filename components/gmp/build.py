# components/gmp/build.py
from kiln.builders.base import AutotoolsBuild

class GMP(AutotoolsBuild):
    name    = 'gmp'
    version = '6.3.0'
    deps    = []
    source  = {
        'url': 'https://gmplib.org/download/gmp/gmp-6.3.0.tar.xz',
    }
    configure_args = [
        '--enable-cxx',
        '--enable-shared',
        '--enable-static',
    ]
    c_flags    = ['-Wno-error=pedantic', '-std=gnu17']
    runtime_globs = []
