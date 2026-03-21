# components/gawk/build.py
from kiln.builders import AutotoolsBuild

class Gawk(AutotoolsBuild):
    name    = 'gawk'
    version = '5.3.2'
    deps    = ['glibc', 'linux-headers']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/gawk/gawk-5.3.2.tar.xz',
    }
