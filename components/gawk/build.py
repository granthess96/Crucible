# components/gawk/build.py
from kiln.builders.base import AutotoolsBuild

class Gawk(AutotoolsBuild):
    name    = 'gawk'
    version = '5.3.2'
    deps    = []
    source  = {
        'url': 'https://ftp.gnu.org/gnu/gawk/gawk-5.3.2.tar.xz',
    }