"""A file containing representations of install configurations.

The core Data representations for installSynApps. 

EpicsModule objects are used to represent each module defined in the configuration.
They store all module-specific information pertinent to building and cloning it.

An InstallConfiguration object is parsed from a configuration, and is then used throughout the build process.
"""

import os
from pathlib import Path
import re
from subprocess import Popen, PIPE

from installSynApps.epics_module import EpicsModule
from . import logger
import json
from .utils import get_commit_hash_given_version


class EpicsEnvironment:
    """
    Class that represents an Install Configuration for installSynApps
    
    It stores the top level install_location, the path to the configuration files,
    any OS specific configurations, and the actual list of modules that will be 
    installed.

    Attributes
    ----------
    install_location : str
        path to top level install location
    config_path : str
        path to configure folder of installSynApps
    modules : List of InsallModule
        list of EpicsModule objects representing the modules that will be installed
    base_path : str
        abs path to install location of EPICS base
    support_path : str
        abs path to install location of EPICS support modules
    ad_path : str
        abs path to install location of EPICS area detector
    motor_path : str
        abs path to install location of EPICS motor
    module_map : dict of str -> int
        Dictionary storing relation of module names to build index
    injector_files : list of InjectorFile
        list of injector files loaded by install configuration
    build_flags : list of list of str
        list of macro-value pairs enforced at build time
    """


    def __init__(self, config_file_path: Path | None = None):
        """Constructor for the InstallConfiguration object
        """

        # Paths to configure and output locations
        self.config_file_path = config_file_path

        self.install_location = None
        self.build_location = None
        self.cloned = False
        self.modules: dict[str, EpicsModule] = {}
        self.build_options: dict[str, str] = {}

        if config_file_path is not None:
            with open(config_file_path, "r") as fp:
                configuration = json.loads(fp.read())
                self.install_location = configuration["INSTALL_LOC"]
                self.build_location = configuration["BUILD_LOC"]

                modules_as_json = configuration["MODULES"]
                for module_name in modules_as_json:
                    self.modules[module_name] = EpicsModule(module_name, modules_as_json[module_name])

                self.build_options = configuration["CONFIG_MACROS"]


    def save(self, save_path: Path | None = None, overwrite_existing=True):
        """Function that saves loaded install configuration

        Main saving function for writing install config. Can create a save directory, then saves 
        main install configuration, build flags, and injector files.

        Parameters
        ----------
        filepath : str
            defaults to addtlConfDirs/config$DATE. The filepath into which to save the install configuration

        Returns
        -------
        bool
            True if successful, False otherwise
        str
            None if successfull, otherwise error message
        """

        if save_path is None:
            save_path = self.config_file_path

        if overwrite_existing and os.path.exists(save_path):
            os.remove(save_path)
        elif not overwrite_existing and os.path.exists(save_path):
            raise FileExistsError(f"Configuration already written to {save_path}!")

        with open(save_path, "w") as fp:
            configuration = {}

            configuration["BUILD_LOC"] = self.build_location
            configuration["INSTALL_LOC"] = self.install_location
            configuration["CONFIG_MACROS"] = self.build_options
            configuration["MODULES"] = {}
            for module_name in self.modules:
                configuration["MODULES"][module_name] = self.modules[module_name].as_dict()

            fp.write(json.dumps(configuration, indent=4))


    def freeze(self):
        logger.write("Freezing versions of modules in configuration...")
        for module in self.modules.values():
            logger.write(f"Freezing version of {module.name}...")
            module.version = get_commit_hash_given_version(module.name, module.url, module.version)
            logger.write(f"Froze module to hash {module.version}")
        logger.write("Done.")


    


    def auto_update_modules(self, save_path=None, overwrite_existing=True):
        """Function that syncs module version tags with those found in git repositories.

        Parameters
        ----------
        install_config : InstallConfiguration
            instance of install configuration for which to update tags
        save_path : str
            None by default. If set, will save the install configuration to the given location after updating.
        overwrite_existing : bool
            Flag that tells installSynApps to overwrite or not the existing module tags. Default: True
        """

        logger.write('Syncing...')
        logger.write('Please wait while tags are synced - this may take a while...')
        for module in self.modules.values():
            self.auto_update_module_tag(module)


    def clone_and_checkout(self) -> list[str]:
        """Top level function that clones and checks out all modules in the current install configuration.

        Returns
        -------
        list[str]
            List of all modules that failed to be correctly cloned and checked out
        """

        failed_modules = []
        for module in self.modules.values():
            successfully_cloned = module.clone_and_checkout(self.build_location)
            self.save()
            if not successfully_cloned:
                failed_modules.append(module.name)

        return failed_modules
    
    def build_module(self, module: EpicsModule, num_threads: int | None = None):
        """Function that executes build of single module

        First, checks if all dependencies built, if not, does that first.
        Then checks for custom build script. If one is found, runs that from
        module root directory.
        Otherwise, runs make followed by specified make flag in module root
        directory.

        Parameters
        ----------
        module_name : str
            The name of the module being built

        Returns
        -------
        int
            The return code of the build process, 0 if module is not buildable (ex. UTILS)
        """

        if module.built:
            logger.write(f"Module {module.name} already built.")
            return True

        if not module.cloned and not module.clone_and_checkout():
            return False

        for dep in module.dependencies:
            deps_built = self.build_module(self.modules[dep], num_threads=num_threads)
            if not deps_built:
                return False

        if module.name != "EPICS_BASE":
            logger.write(f"Adding CONFIG_SITE.local and RELEASE.local files for {module.name}")
            for configure_dir in module.get_module_configure_dirs():
                with open(os.path.join(configure_dir, "CONFIG_SITE.local"), "w") as fp:
                    for macro in self.build_options:
                        fp.write(f"{macro}={self.build_options[macro]}\n")
                with open(os.path.join(configure_dir, "RELEASE.local"), "w") as fp:
                    for mod in self.modules.values():
                        fp.write(f"{mod.name}={os.path.join(self.build_location, mod.url.split('/')[-1].split('.')[0])}\n")

        logger.write(f"Building module {module.name}...")
        if module.build_cmd is not None:
            cmd = module.build_cmd.split(" ")
        else:
            cmd = ["make", "-C", module.abs_path, f"-sj{'' if not num_threads else num_threads}"]

        logger.print_command(cmd)
        proc = Popen(cmd)
        proc.wait()

        if proc.returncode == 0:
            logger.write(f"Built module {module.name}.")
            module.built = True
            return True
        return False


    def build_all(self, num_threads: int = 0):
        """Main function that runs full build sequentially

        Returns
        -------
        int
            0 if success, number failed modules otherwise
        list of str
            List of module names that failed to compile
        """

        success = True
        for module in self.modules.values():
            success = self.build_module(module, num_threads=num_threads)
            if not success:
                logger.write(f"Failed to build module {module.name}! Aborting...")
                break
        self.save()
        return success



    def __str__(self) -> str:

        out = "--------------------------------\n"
        out = out + f"Config Location {self.config_file_path}\n"
        out = out + f"Build Location = {self.build_location}\n"
        out = out + f"Install Location = {self.install_location}\n\nModules:\n\n"
        out = out + f"+------------------------------------------------------------------+\n"
        out = out + f"|     Module Name    | Module Version | Cloned | Built | Installed |\n"
        out = out + f"+------------------------------------------------------------------+\n"
        for module in self.modules.values():
            out += f"|   {module.name:16} |   {module.version:12} | {'X' if module.cloned else ' '}      | {'X' if module.built else ' '}        | {'X' if module.installed else ' '}      |\n"
        out = out + f"+------------------------------------------------------------------+\n"
        return out