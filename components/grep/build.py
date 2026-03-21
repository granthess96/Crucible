from kiln.builders import AutotoolsBuild

class Grep(AutotoolsBuild):
    name    = 'grep'
    version = '3.11'
    deps    = ['pcre2', 'glibc', 'linux-headers']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/grep/grep-3.11.tar.xz',
    }
