# components/xz/build.py
from kiln.builders import AutotoolsBuild

class Xz(AutotoolsBuild):
    name    = 'xz'
    version = '5.6.3'
    deps    = ['glibc', 'linux-headers']
    source  = {
        'url': 'https://github.com/tukaani-project/xz/releases/download/v5.6.3/xz-5.6.3.tar.xz',
    }