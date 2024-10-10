# AI-code-review

[[License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Introduction

This is an AI code review tool designed to be used in conjunction with GitLab.

It leverages AI models to analyze code and provide feedback and modification suggestions, aiding developers in improving code quality and efficiency.

## Features

- Integrates with Alibaba Cloud's Qwen code model to perform code reviews and enhance code quality.
- Supports customizable rules for tailoring review criteria according to team needs.
- Provides customizable templates for adapting review processes to team requirements.

## Installation Guide

1. Clone the project repository:
   ```bash
   git clone https://github.com/meate-onlines/AI-code-review.git
   ```

2. Install dependencies

   ```bash
   pip install -r requirements.txt
   ```

## Documentation
### Main Modules

- `code.py`: The main program responsible for fetching the merged code of the day and sending requests to the AI model for review.
- `config_load.py`: Configuration file containing the AI model settings as well as the configuration information for review rules and templates.
- `ali_ai.py`: Module for invoking Alibaba Cloud's Qwen code model for reviews.

### Example Code

```python
from repository import code
from ai import ali_ai

mrs_today = code.get_mrs_created_today()
code.parse_diffs(mrs_today, ali_ai.review_code)
print("Today's merged code has been reviewed!")
```

## Configuration

First, copy the configuration file `config-demo_1728538661012.yml` and rename it to `config.yml`.

The configuration file `config.yml` includes the following parameters:
```yaml
gitlab:
    url: xxxxxxx # GitLab server address
    user: xxxxxxx # GitLab username (optional)
    token: xxxxxxx # User access token for authorization

# Configuration for Alibaba Cloud AI assistant
ai:
    base_url: xxxxxxx # Base URL for the AI service
    api_key: xxxxxxx # API key for authentication
    model: xxxxxxx # Name of the AI model to be used
    role_desc: you are a code reviewer # Description of the AI model's role to ensure it understands its position as a code reviewer
    prompt: You are a code reviewer. Please review the code, identify issues within the code, and provide concise descriptions of key issues within 300 characters. 
           For configuration-type code snippets, return an empty string. # Prompt provided to the AI model to guide it through the code review task
```
After configuring, run `python main.py`.
It is recommended to use tools like `cron` or `systemd` to schedule daily code review tasks.

## Contribution Guidelines

Contributions are welcome! Please follow these steps:

1. Fork the project.
2. Create a new branch.
3. Commit your changes.
4. Submit a Pull Request.

## License

This project is licensed under the [MIT License](LICENSE).

## Contact

For any questions or suggestions, please contact:

- Email: fmj_lg@163.com
- GitHub: [meate-onlines](https://github.com/meate-onlines)

## Acknowledgments

Thanks to the following projects and individuals for their support:

- [python-gitlab](https://python-gitlab.readthedocs.io/en/stable/index.html)
- [Alibaba Cloud Qwen](https://help.aliyun.com/zh/dashscope/developer-reference/use-qwen-coder-by-calling-api?source=5176.29345612&userCode=din8lh2o)
