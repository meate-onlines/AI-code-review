from repository import code
from ai import ali_ai
import datetime
mrs_today = code.get_mrs_created_today()
print(f"开始审核{datetime.datetime.now().date()}合并的代码,总数:{len(mrs_today)}")
code.parse_diffs(mrs_today, ali_ai.review_code)
print("今日合并提交的代码审核完毕！")

