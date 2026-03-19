# components/bzip2/build.py
from kiln.builders import MakeBuild, BuildPaths

class Bzip2(MakeBuild):
    name    = 'bzip2'
    version = '1.0.8'
    deps    = ['glibc']
    source  = {
        'url': 'https://sourceware.org/pub/bzip2/bzip2-1.0.8.tar.gz',
    }

    def install_command(self, paths: BuildPaths) -> list[str]:
        return [
            'make',
            '-C', paths.source,
            f'PREFIX={paths.install}/usr',
        ] + self.install_targets
