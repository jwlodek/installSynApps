

from pathlib import Path
from installSynApps.data_model import InstallConfiguration, InstallModule
from subprocess import Popen
import subprocess
import os
import installSynApps.logger as logger
from installSynApps.utils import check_dependency_in_path
from .clone import clone_single_module
from .utils import get_module_configure_dirs

# Currently only support auto-fetching dependencies w/ dnf
BASE_DEPS_DNF = set([
    "re2c",
    "readline-devel",
    "libxml2-devel",
    "pcre-devel",
    "libtirpc-devel",
    "libusbx-devel",
    "git",
    "make",
    "gcc",
    "gcc-g++",
    "libXext-devel",
    "perl-devel",
    "libraw1394",
    "boost-devel",
    "libusb-devel",
    "rpcgen",
    "net-snmp-devel",
    "motif-devel",
    "libXt-devel",
    "zeromq-devel",
    "giflib-devel",
    "libXtst-devel"
])

def acquire_dependecies():
    """Method that runs dependency install shell/batch script

    Parameters
    ----------
    dependency_script_path : str
        path to dependency shell/batch script
    """

    logger.debug("Installing dependency packages...")
    try:
        check_dependency_in_path("dnf")
    except RuntimeError:
        logger.debug("Dependency auto-installation only supported on RH derivatives.")
    else:
        cmd = []
        if os.geteuid == 0:
            pass
        else:
            try:
                check_dependency_in_path("dzdo")
                cmd.append("dzdo")
            except RuntimeError:
                cmd.append("sudo")
        cmd.extend(["dnf", "install", "-y"])

        for pkg in BASE_DEPS_DNF:
            logger.debug(f"Installing {pkg} with dnf...")
            subprocess.call(cmd + pkg)





