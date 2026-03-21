# components/mpfr/build.py
from kiln.builders import AutotoolsBuild

class MPFR(AutotoolsBuild):
    name    = 'mpfr'
    version = '4.2.1'
    deps    = ['gmp', 'glibc', 'linux-headers']
    source  = {
        'url': 'https://www.mpfr.org/mpfr-4.2.1/mpfr-4.2.1.tar.xz',
    }
    runtime_globs = []
