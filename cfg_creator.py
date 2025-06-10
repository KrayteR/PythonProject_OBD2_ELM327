from configparser import ConfigParser

config = ConfigParser()

config["commands"] = {
    "rpm": "010C",
    "speed": "010D"
}

with open("cfg.ini", "w") as f:
    config.write(f)