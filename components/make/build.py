# components/make/build.py
from kiln.builders import AutotoolsBuild

class Make(AutotoolsBuild):
    name    = 'make'
    version = '4.4.1'
    deps    = ['glibc', 'linux-headers']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/make/make-4.4.1.tar.gz',
    }
