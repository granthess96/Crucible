from kiln.builders import BuildDef, BuildPaths

class Filesystem(BuildDef):
    name    = 'filesystem'
    version = '1.0'
    deps    = []
    source = {
        "source_type": "none"
    }

    runtime_globs = BuildDef.runtime_globs + [
        "**",
    ]

    buildtime_globs = BuildDef.buildtime_globs + [
        "**",
    ]

    
    # --- Add these to satisfy BuildDef requirements ---
    def configure_command(self, paths: BuildPaths) -> list[str]:
        return [] # No-op

    def build_command(self, paths: BuildPaths) -> list[str]:
        return [] # No-op

    def install_command(self, paths: BuildPaths) -> list[str]:
        return [] # We are using install_script instead

    def install_script(self, paths: BuildPaths) -> str:
        return f"""
mkdir -p {paths.install}/usr/bin
mkdir -p {paths.install}/usr/lib
mkdir -p {paths.install}/usr/lib64
mkdir -p {paths.install}/usr/sbin
mkdir -p {paths.install}/usr/include
mkdir -p {paths.install}/usr/share
mkdir -p {paths.install}/usr/libexec
mkdir -p {paths.install}/etc
mkdir -p {paths.install}/var
mkdir -p {paths.install}/tmp
mkdir -p {paths.install}/proc
mkdir -p {paths.install}/sys
mkdir -p {paths.install}/dev
mkdir -p {paths.install}/run
ln -sfn usr/bin  {paths.install}/bin
ln -sfn usr/lib  {paths.install}/lib
ln -sfn usr/lib64 {paths.install}/lib64
ln -sfn usr/sbin {paths.install}/sbin
"""
