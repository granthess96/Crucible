# components/findutils/build.py
from kiln.builders import AutotoolsBuild

class Findutils(AutotoolsBuild):
    name    = 'findutils'
    version = '4.10.0'
    deps    = ['glibc', 'linux-headers']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/findutils/findutils-4.10.0.tar.xz',
    }
