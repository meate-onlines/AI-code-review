from config_loader import config
from openai import OpenAI

ai_config = config["ai"]

client = OpenAI(
    api_key=ai_config['api_key'],
    base_url=ai_config['base_url'],
)


def review_code(code_string)->dict:
    completion = client.chat.completions.create(
        model=ai_config['model'],
        messages=[
            {'role': 'system', 'content': ai_config['role_desc']},
            {'role': 'user', 'content': ai_config['prompt'] + "\n" + code_string}])
    print(completion)
    if not completion or not completion.choices or len(completion.choices) == 0:
        return {
            'success': False,
            'message': 'No response from AI service',
            'data': None
        }

    review_content = completion.choices[0].message.content
    if not review_content:
        return {
            'success': False, 
            'message': 'Empty review content',
            'data': None
        }

    return {
        'success': True,
        'message': 'Review completed successfully',
        'data': review_content
    }



if __name__ == "__main__":
    code_str = """
    def test_function(a, b):
        return a + b
    """
    print(review_code(code_str))

