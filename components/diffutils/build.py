# components/diffutils/build.py
from kiln.builders import AutotoolsBuild
from kiln.spec import FileSpec

class Diffutils(AutotoolsBuild):
    name    = 'diffutils'
    version = '3.10'
    deps    = ['glibc', 'linux-headers']
    source  = {
        'url': 'https://ftp.gnu.org/gnu/diffutils/diffutils-3.10.tar.xz',
    }

    files = [
        FileSpec("usr/bin/**", role="tool"),
    ]
