# components/sed/build.py
from kiln.builders import AutotoolsBuild

class Sed(AutotoolsBuild):
    name    = 'sed'
    version = '4.9'
    deps    = ['glibc', 'linux-headers']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/sed/sed-4.9.tar.xz',
    }
