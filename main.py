from repository import code
from ai import ali_ai

mrs_today = code.get_mrs_created_today()
code.parse_diffs(mrs_today, ali_ai.review_code)
print("今日合并提交的代码审核完毕！")
