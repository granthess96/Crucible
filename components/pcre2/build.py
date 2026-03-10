from kiln.builders.base import CMakeBuild

class PCRE2(CMakeBuild):
    name    = 'pcre2'
    version = '10.47'
    deps    = []
    source  = {
        'git': 'https://github.com/PCRE2Project/pcre2',
        'ref': 'pcre2-10.47',
    }
