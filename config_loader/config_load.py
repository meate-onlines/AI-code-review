from pathlib import Path

import yaml

import logging


def load_config():
    config_file_path = 'config.yml'

    # 获取配置文件的绝对路径
    config_path = Path(config_file_path).resolve()

    # 检查文件是否存在
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file {config_path} does not exist.")

    # 使用PyYAML加载配置文件
    with open(config_path, 'r') as stream:
        try:
            return yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            logging.error(exc)


if __name__ == '__main__':
    config = load_config()
    print(config)
