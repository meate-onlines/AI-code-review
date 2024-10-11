from config_loader import config
from openai import OpenAI

ai_config = config["ai"]

client = OpenAI(
    api_key=ai_config['api_key'],
    base_url=ai_config['base_url'],
)


def review_code(code_string):
    completion = client.chat.completions.create(
        model=ai_config['model'],
        messages=[
            {'role': 'system', 'content': ai_config['role_desc']},
            {'role': 'user', 'content': ai_config['prompt'] + "\n" + code_string}])

    return completion.choices[0].message.content


if __name__ == "__main__":
    code_str = """
    def test_function(a, b):
        return a + b
    """
    print(review_code(code_str))

