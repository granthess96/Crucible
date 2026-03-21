# components/gzip/build.py
from kiln.builders import AutotoolsBuild

class Gzip(AutotoolsBuild):
    name    = 'gzip'
    version = '1.13'
    deps    = ['glibc', 'linux-headers']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/gzip/gzip-1.13.tar.xz',
    }
