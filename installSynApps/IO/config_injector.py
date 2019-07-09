"""
Class responsible for injecting settings into configuration files

@author: Jakub Wlodek
"""

import os
import re
import installSynApps.DataModel.install_config as IC

class ConfigInjector:
    """
    Class that is responsible for injecting configuration information and replaces macros.

    Attributes
    ----------
    install_config : InstallConfiguration
        the currently loaded install configuration
    ad_modules : List of str
        Used to decide which modules to include when with_ad = False in update_macros_file()

    Methods
    -------
    inject_into_file(injector_file_path : str)
        injects a given injector file into its target
    update_macros(macro_val_list : List, target : str)
        updates the macros in a target directory files given a list of macro-value pairs
    update_macros_file(macro_replace_list : List, target_dir : 
        str, target_filename : str, comment_unsupported : bool, with_ad : bool)
            Function that updates the macros for a single file, with settings for commenting unupported macros
            and for including the ad blacklist
    """


    def __init__(self, install_config):
        """Constructor for ConfigInjector"""

        self.install_config = install_config
        self.ad_modules = ["ADCORE", "AREA_DETECTOR", "ADSUPPORT"]




    def inject_to_file(self, injector_file):
        """
        Function that injects contents of specified file into target

        First, convert to absolute path given the install config. Then open it in append mode, then
        write all uncommented lines in the injector file into the target, and then close both

        Parameters
        ----------
        injector_file_path : InjectorFile
            object representing injector file
        """

        target_path = injector_file.target
        if target_path is None or len(target_path) == 0:
            return
        target_path = self.install_config.convert_path_abs(target_path)
        print(target_path)
        target_file = target_path.rsplit('/', 1)[-1]
        target_path_no_example = target_path.rsplit('/', 1)[0] + "/" + target_file[8:]
        if (not os.path.exists(target_path) and not os.path.exists(target_path_no_example)):
            return
        if target_file.startswith("EXAMPLE_"):
            if os.path.exists(target_path):
                os.rename(target_path, target_path_no_example)
            target_path = target_path_no_example
        print(target_path)
        target_fp = open(target_path, "a")
        target_fp.write("\n# ------------The following was auto-generated by installSynApps-------\n\n")
        if injector_file.contents is not None:
            target_fp.write(injector_file.contents)
        target_fp.write("\n# --------------------------Auto-generated end----------------------\n")
        target_fp.close()



    def update_macros_dir(self, macro_replace_list, target_dir):
        """
        Function that updates the macros for all files in a target location, given a list of macro-value pairs

        Parameters
        ----------
        macro_replace_list : List
            list containting macro-value pairs
        target_dir : str
            path of target dir for which all macros will be edited.
        """

        if os.path.exists(target_dir) and os.path.isdir(target_dir):
            for file in os.listdir(target_dir):
                if os.path.isfile(target_dir + "/" + file) and not file.endswith(".pl") and file != "Makefile" and not file.endswith(".ioc"):
                    self.update_macros_file(macro_replace_list, target_dir, file)


    def update_macros_file(self, macro_replace_list, target_dir, target_filename, comment_unsupported = False, with_ad = True):
        """
        Function that updates the macro values in a single configure file

        Parameters
        ----------
        macro_replace_list : List of [str, str]
            list of macro-value pairs to replace
        target_dir : str
            location of target file
        target_filename : str
            name of the file
        comment_unsupported : bool
            if true, will comment out any macros that are in the file that are not in input list. Important for updating RELEASE in support/
        with_ad : bool
            if false, will comment out macros for area detector modules. used for RELEASE in support - AD is built separately
        """

        if not os.path.exists(target_dir + "/OLD_FILES"):
            os.mkdir(target_dir + "/OLD_FILES")
        os.rename(target_dir + "/" + target_filename, target_dir + "/OLD_FILES/" + target_filename)
        old_fp = open(target_dir + "/OLD_FILES/" + target_filename, "r")

        if target_filename.startswith("EXAMPLE_"):
            new_fp = open(target_dir + "/" + target_filename[8:], "w")
        else:
            new_fp = open(target_dir + "/" + target_filename, "w")
        line = old_fp.readline()
        while line:
            line = line.strip()
            if not line.startswith('#') and '=' in line:
                line = line = re.sub(' +', '', line)
            if line.startswith('#') and '=' not in line:
                new_fp.write(line + "\n")
            else:
                wrote_line = False
                for macro in macro_replace_list:
                    if line.startswith(macro[0] + "=") and (with_ad or (macro[0] not in self.ad_modules)):
                        new_fp.write("{}={}\n".format(macro[0], macro[1]))
                        wrote_line = True
                    elif line.startswith("#" + macro[0] + "="):
                        new_fp.write("#{}={}\n".format(macro[0], macro[1]))
                        wrote_line = True
                if not wrote_line:
                    if comment_unsupported and not line.startswith('#') and len(line) > 1:
                        new_fp.write("#" + line + "\n")
                    else:
                        new_fp.write(line + "\n")
            line = old_fp.readline()
        new_fp.close()
        old_fp.close()


