from kiln.builders import AutotoolsBuild

class Flex(AutotoolsBuild):
    name    = 'flex'
    version = '2.6.4'
    deps    = ['glibc', 'linux-headers', 'm4']
    source  = {
        'url': 'https://github.com/westes/flex/releases/download/v2.6.4/flex-2.6.4.tar.gz',
    }
