from kiln.builders.base import MakeBuild, BuildPaths

class Bzip2(MakeBuild):
    name    = 'bzip2'
    version = '1.0.8'
    deps    = ['glibc']
    source  = {
        'git': 'https://gitlab.com/bzip2/bzip2.git',
        'ref': 'bzip2-1.0.8',
    }
    
    