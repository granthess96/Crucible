# components/mpc/build.py
from kiln.builders import AutotoolsBuild

class MPC(AutotoolsBuild):
    name    = 'mpc'
    version = '1.3.1'
    deps    = ['gmp', 'mpfr', 'glibc', 'linux-headers']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/mpc/mpc-1.3.1.tar.gz',
    }
