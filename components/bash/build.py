from kiln.builders.base import AutotoolsBuild

class BashBuild(AutotoolsBuild):
    name    = "bash"
    version = "5.3"
    deps    = ['glibc', 'ncurses']
    source  = {
        "git": "https://git.savannah.gnu.org/git/bash.git",
        "ref": "bash-5.3",
    }
    
    configure_args = ['--prefix=/usr', 
                        '--without-bash-malloc',
                        '--with-curses',
                        '--enable-readline',
                        '--disable-loadables',
                        '--disable-examples'
                      ]
    
    comp_flags = ['-O2', '-std=c++17', '-std=gnu17', '-I/usr/include']
    link_flags = []
