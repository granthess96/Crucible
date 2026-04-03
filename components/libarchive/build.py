# components/gawk/build.py
from kiln.builders import AutotoolsBuild

class Libarchive(AutotoolsBuild):
    name    = 'libarchive'
    version = '3.8.6'

    deps    = [
        'glibc',
        'linux-headers',
    ]

    source  = {
        'url': 'https://github.com/libarchive/libarchive/releases/download/v3.8.6/libarchive-3.8.6.tar.xz',
    }
