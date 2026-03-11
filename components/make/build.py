# components/make/build.py
from kiln.builders.base import AutotoolsBuild

class Make(AutotoolsBuild):
    name    = 'make'
    version = '4.4.1'
    deps    = ['glibc']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/make/make-4.4.1.tar.gz',
    }