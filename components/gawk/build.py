from kiln.builders.base import AutotoolsBuild

class Gawk(AutotoolsBuild):
    name    = 'gawk'
    version = '5.3.2'
    deps    = []
    source  = {
        'git': 'https://git.savannah.gnu.org/git/gawk.git',
        'ref': 'gawk-5.3.2',
    }
