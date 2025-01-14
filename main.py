from repository import code
from ai import ali_ai
import datetime
import asyncio
mrs_today = code.get_mrs_created_today()
print(f"开始审核{datetime.datetime.now().date()}合并的代码,总数:{len(mrs_today)}")
code.parse_diffs(mrs_today, ali_ai.review_code)
# Wait for any pending async operations to complete

try:
    # Get the current event loop
    loop = asyncio.get_event_loop()
    # Run until all tasks are complete
    pending = asyncio.all_tasks(loop)
    loop.run_until_complete(asyncio.gather(*pending))
except RuntimeError:
    # Handle case where there is no event loop
    pass

print("今日合并提交的代码审核完毕！")

