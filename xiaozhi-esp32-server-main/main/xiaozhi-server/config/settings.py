import os
from config.config_loader import read_config, get_project_dir, load_config


default_config_file = "config.yaml"
config_file_valid = False


def check_config_file():
    global config_file_valid
    if config_file_valid:
        return
    """
    Simplified configuration check to notify users about the status of the configuration file.
    """
    custom_config_file = get_project_dir() + "data/." + default_config_file
    if not os.path.exists(custom_config_file):
        raise FileNotFoundError(
            "The file 'data/.config.yaml' could not be found. Please follow the tutorial to ensure the configuration file exists."
        )

    # Check if configuration is read from API
    config = load_config()
    if config.get("read_config_from_api", False):
        print("Reading configuration from API")
        old_config_origin = read_config(custom_config_file)
        if old_config_origin.get("selected_module") is not None:
            error_msg = "It appears your configuration file contains both remote (Control Panel) and local settings:\n"
            error_msg += "\nRecommendations:\n"
            error_msg += "1. Copy the 'config_from_api.yaml' file from the root directory to the 'data' folder and rename it to '.config.yaml'\n"
            error_msg += "2. Follow the tutorial to configure the API endpoint and secret key correctly.\n"
            raise ValueError(error_msg)
    config_file_valid = True