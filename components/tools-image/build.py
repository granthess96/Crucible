# components/tools-image/build.py
from kiln.builders import ImageDef

class ToolsImage(ImageDef):
    name    = 'tools-image'
    version = '1.0'
    deps    = [
        'gmp',
        'libxcrypt',
        'mpfr',
        'mpc',
        'binutils',
        'gcc',
        'zlib',
        'glibc',
        'linux-headers',
    ]
    source  = {}
