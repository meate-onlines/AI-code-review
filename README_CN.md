# AI-code-review

[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 简介

这是一个结合 GitLab 使用的 AI 代码审查工具。

它使用 AI 模型来分析代码，并提供反馈和修改建议，以帮助开发人员提高代码质量和效率。

## 功能特点

- 集成阿里云的通义千问代码模型，实现代码审查，提升代码质量。
- 支持自定义规则，根据团队需求定制化审查规则。
- 支持自定义模板，根据团队需求定制化审查模板。

## 安装指南

1. 克隆项目仓库：
   ```bash
   git clone https://github.com/meate-onlines/AI-code-review.git
   ```

2. 安装依赖

   ```bash
   pip install -r requirements.txt
   ```

## 使用文档
### 主要模块

- `code.py`：主程序，负责获取当天合并的代码，并发送请求到 AI 模型进行审查。
- `config_load.py`：配置文件，包含 AI 模型的配置信息，以及审查规则和模板的配置信息。
- `ali_ai.py`：ai 模型调用模块，负责调用阿里云的通义千问代码模型进行审查。
### 示例代码

```python
from repository import code
from ai import ali_ai

mrs_today = code.get_mrs_created_today()
code.parse_diffs(mrs_today, ali_ai.review_code)
print("今日合并提交的代码审核完毕！")
```
## 配置
首先把配置文件`config-demo_1728538661012.yml`复制一份，并命名为`config.yml`。

配置文件`config.yml`包含以下参数：
```yaml
gitlab:
    url: xxxxxxx # GitLab服务器地址
    user: xxxxxxx # GitLab用户名（可删除）
    token: xxxxxxx # 用户访问令牌，用于授权

#aliyun AI助手相关配置
ai:
    base_url: xxxxxxx # AI服务的基础URL
    api_key: xxxxxxx # AI服务的API密钥，用于身份验证
    model: xxxxxxx # 使用的AI模型名称
    role_desc: you are a code reviewer # AI模型的角色描述，使其明确自己的定位是代码审核者
    prompt: 你是一个代码审核者，请 review 代码，找出代码中的问题，给出关键问题的描述，字数在 300 字以内，
           如果是配置类代码片段，请返回空字符串。 # 提供给AI模型的提示信息，引导其进行代码审核任务
```
配置完成后，运行`python main.py`即可。
建议使用`cron`或`systemd`等定时任务工具，设置每天定时运行代码审查任务。

## 贡献指南

欢迎贡献！请遵循以下步骤：

1. 叉克（Fork）项目。
2. 创建一个新的分支。
3. 提交你的更改。
4. 提交 Pull Request。

## 许可证

本项目采用 [MIT License](LICENSE) 许可。

## 联系方式

如有任何问题或建议，请联系：

- 邮箱: fmj_lg@163.com
- GitHub: [meate-onlines](https://github.com/meate-onlines)

## 致谢

感谢以下项目和人员的支持：

- [python-gitlab](https://python-gitlab.readthedocs.io/en/stable/index.html)
- [openai](https://help.aliyun.com/zh/dashscope/developer-reference/use-qwen-coder-by-calling-api?source=5176.29345612&userCode=din8lh2o)