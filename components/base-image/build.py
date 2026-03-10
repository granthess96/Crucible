from kiln.builders.base import ScriptBuild, BuildPaths

class BaseImage(ScriptBuild):
    name    = 'base-image'
    version = '1.0'
    deps    = [
        'linux-headers',
        'glibc',
        'zlib',
        'ncurses',
        'readline',
        'bash',
        'coreutils',
        'sed',
        'grep',
        'gawk',
        'findutils',
        'pcre2',
        'tar',
        'xz',
        'gzip',
        'bzip2',
        'make'
#        'perl',
#        'm4',
#        'autoconf',
#        'automake',
#        'bison',
#        'gperf',
#        'gettext',
#        'help2man',
#        'texinfo',
    ]
    source  = {}   # no upstream source — pure assembly, Option C TODO

    def configure_command(self, paths: BuildPaths) -> list[str]:
        return []

    def build_command(self, paths: BuildPaths) -> list[str]:
        return []

    def install_command(self, paths: BuildPaths) -> list[str]:
        return []
