# components/mpc/build.py
from kiln.builders import AutotoolsBuild

class MPC(AutotoolsBuild):
    name    = 'mpc'
    version = '1.3.1'
    deps    = ['gmp', 'mpfr']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/mpc/mpc-1.3.1.tar.gz',
    }
    runtime_globs = []
