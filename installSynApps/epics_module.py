
from pathlib import Path
from . import logger
from .utils import get_module_configure_dirs, does_git_checked_out_version_match
import shutil
import os
from subprocess import PIPE, Popen
import re

# Variables set in RELEASE file that are not module dependencies
NON_DEP_RELEASES = [
    "SUPPORT", 
    "UTILS", 
    "TEMPLATE_TOP", 
    "TEMPLATE_CONFIG", 
    "TEMPLATE_RELEASE", 
    "TEMPLATE_SITE", 
    "TEMPLATE_CONFIG_SITE",
]


# Because EPICS versioning is not as standardized as it should be, certain modules cannot be properly auto updated.
# Ex. Calc version R3-7-3 is most recent, but R5-* exists?
UPDATE_TAGS_BLACKLIST = ["SSCAN", "CALC", "STREAM"]


class EpicsModule:
    """Class that represents individual install module

    Attributes
    ----------
    name : str
        the name of the module
    version : str
        the desired module tag, or alternatively master
    rel_path : str
        relative path to module
    abs_path : str
        absolute path to module
    url_type : str
        either GIT_URL if using git version control, or WGET_URL if sources hosted in .tar.gz file
    url : str
        url where the git repository or wget download resies
    repository : str
        name of the git repo to clone or wget file to download
    clone : str
        YES or NO, flag to clone the module
    build : str
        YES or NO, flag to build the module
    package : str
        YES or NO, flag to package the module
    custom_build_script_path : str
        path to script used to build module instead of just make
    dependencies : list of str
        list of modules identified as dependencies for module
    """

    def __init__(self, module_name: str, module_config: dict[str, dict[str, str]], parent_build_loc: Path):
        """Constructor for the InstallModule class
        """

        self.name = module_name
        self.dir_name = self.name.lower().replace("_", "-")
        self.version = module_config["VERSION"]
        self.url = module_config["URL"]
        self.parent_build_loc = parent_build_loc

        self.built = module_config["BUILT"]
        self.installed = module_config["INSTALLED"]

        self.build_cmd = None
        if "BUILD_CMD" in module_config:
            self.build_cmd = module_config["BUILD_CMD"]

        self.recursive_clone = False
        if "RECURSIVE" in module_config and module_config["RECURSIVE"]:
            self.recursive_clone = True

        if "STATE" in module_config:
            self.cloned = module_config["STATE"] & 1
            self.built = module_config["STATE"] & 2
            self.installed = module_config["STATE"] & 4
            

        # List of epics modules that this module depends on
        self.dependencies = []

    @property
    def abs_path(self):
        return os.path.join(self.parent_build_loc, self.dir_name)



    def get_module_configure_dirs(self) -> list[tuple[Path, list[str]]]:
        configure_dirs = []
        for dirpath, _, _ in os.walk(self.abs_path):
            if os.path.basename(dirpath) == "configure":
                configure_dirs.append(dirpath)
        return configure_dirs
    


    def clone_and_checkout(self) -> bool:
        """Function responsible for cloning each module into the appropriate location

        First checks if the module uses git or a download, and whether it needs to be recursive
        then, uses the information in the module object along with subprocess commands to clone the module.

        Parameters
        ----------
        module : InstallModule
            InstallModule currently being cloned
        recursive=False
            Flag that decides if git clone should be done recursively
        """


        logger.debug(f"Cloning module {self.name}...")


        if self.cloned:
            logger.write(f"Module {self.name} already cloned w/ version {self.version} checked out.")
            return True
        elif not os.path.exists(self.abs_path):
            # Clear any build state
            self.built = False
            self.installed = False

            cmd = ["git", "clone"]
            if self.recursive_clone:
                cmd.append("--recursive")
            cmd.extend([self.url, self.abs_path])

            logger.print_command(cmd)
            p = Popen(cmd)
            p.wait()

            if p.returncode != 0:
                logger.write(f"Failed to clone module {self.name}!")
                return False

            if self.recursive_clone:
                cmd = ["git", "-C", self.abs_path, "submodule", "update"]
                logger.print_command(cmd)
                p = Popen(cmd)
                p.wait()

            if p.returncode != 0:
                logger.write(f"Failed to update submodules for module {self.name}.")
                return False
            
            logger.write(f"Cloned module {self.name} successfully, checking out specified version...")

        cmd = ["git", "-C", self.abs_path, "checkout", "-q", self.version]
        logger.print_command(cmd)
        p = Popen(cmd)
        p.wait()

        if p.returncode != 0:
            logger.write(f"Checkout of version {self.version} failed for module {self.name}.")
            return False

        logger.write(f"Checked out version {self.version}, updating dependency information...")
        configure_dirs = get_module_configure_dirs(self.abs_path)
        for configure_dir, filenames in configure_dirs:
            for file in filenames:
                if file.startswith("RELEASE"):
                    with open(os.path.join(configure_dir, "RELEASE"), "r") as fp:
                        lines = fp.readlines()
                        for line in lines:
                            line = re.sub(r'(?m)^ *#.*\n?', '', line)
                            if "=" in line:
                                dep = line.split("=")[0].strip()
                                if dep not in NON_DEP_RELEASES and dep != self.name and self.name != "EPICS_BASE":
                                    self.dependencies.append(dep)
                                    logger.debug(f"Detected dependency: {dep}")

        return True


    @property
    def cloned(self):
        checks = [
            ["describe", "--exact-match", "--tags"],
            ["rev-parse", "--short"]
        ]
        for check in checks:
            p = Popen(["git", "-C", str(self.abs_path)] + check + ["HEAD"], stdout=PIPE, stderr=PIPE)
            out, _ = p.communicate()
            if p.returncode == 0 and out.decode("utf-8") == self.version:
                return True

        return False


    def auto_update_version(self):
        """Automatically attempts to select the most recent tagged release, or most recent commit hash.
        """

        if self.name not in UPDATE_TAGS_BLACKLIST:
            cmd = ["git", "ls-remote", "--tags", self.url]
            logger.print_command(cmd)
            p = Popen(cmd, stdout=PIPE, stderr=PIPE)
            out, _ = p.communicate()
            ret = out.decode("utf-8")
            
            best_tag = None
            for tag_info in ret.splitlines():
                tag = tag_info.rsplit("/")[-1]

                if best_tag is None:
                    best_tag = tag
                else:
                    best_tag_ver_str_list = re.split(r"\D+", best_tag)
                    best_tag_ver_str_list = [num for num in best_tag_ver_str_list if num.isnumeric()]
                    best_tag_version_numbers = list(map(int, best_tag_ver_str_list))
                    
                    tag_ver_str_list = re.split(r"\D+", tag)
                    tag_ver_str_list = [num for num in tag_ver_str_list if num.isnumeric()]
                    tag_version_numbers = list(map(int, tag_ver_str_list))
                    for i in range(len(tag_version_numbers)):
                        if best_tag.startswith("R") and not tag.startswith("R"):
                            break
                        elif not best_tag.startswith("R") and tag.startswith("R"):
                            best_tag = tag
                            best_tag_version_numbers = tag_version_numbers
                            break
                        elif i == len(best_tag_version_numbers) or tag_version_numbers[i] > best_tag_version_numbers[i]:
                            best_tag = tag
                            best_tag_version_numbers = tag_version_numbers
                            break
                        elif tag_version_numbers[i] < best_tag_version_numbers[i]:
                            break

                tag_updated = False
                module_ver_str_list = re.split(r"\D+", self.version)
                module_ver_str_list = [num for num in module_ver_str_list if num.isnumeric()]
                module_version_numbers = list(map(int, module_ver_str_list))

                for i in range(len(best_tag_version_numbers)):
                    if i == len(module_version_numbers) or best_tag_version_numbers[i] > module_version_numbers[i]:
                        tag_updated = True
                        logger.write(f"Updating {self.name} from version {self.version} to version {best_tag}")
                        self.version = best_tag
                        break
                    elif best_tag_version_numbers[i] < module_version_numbers[i]:
                        break
                if not tag_updated:
                    logger.debug(f"Module {self.name} already at latest version: {self.version}")


    def as_dict(self) -> dict:
        as_dict = {}
        as_dict["URL"] = self.url
        as_dict["VERSION"] = self.version
        if self.build_cmd is not None:
            as_dict["BUILD_CMD"] = self.build_cmd
        if self.recursive_clone:
            as_dict["RECURSIVE"] = True
        as_dict["STATE"] = 1 * self.cloned + 2 * self.built + 4 * self.installed
        as_dict["DEPS"] = self.dependencies

        return as_dict
