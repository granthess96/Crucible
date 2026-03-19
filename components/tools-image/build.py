# components/tools-image/build.py
from kiln.builders import ImageDef

class ToolsImage(ImageDef):
    name    = 'tools-image'
    version = '1.0'
    deps    = [
        'gmp',
        'mpfr',
        'mpc',
        'binutils',
        'gcc',
    ]
    source  = {}
