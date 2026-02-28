from kiln.builders.base import ScriptBuild, BuildPaths

class KernelbBuild(ScriptBuild):
    name    = "kernel"
    version = "6.18.12"
    deps    = []
    source  = {
        "git": "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git",
        "ref": "v6.18.12",
    }

    def build_command(self, paths: BuildPaths) -> list[str]:
        return ['make', 'headers_install',
                'ARCH=x86_64',
                f'INSTALL_HDR_PATH={paths.install}/usr']

    def configure_command(self, paths: BuildPaths) -> list[str]:
        return []   # no configure step
