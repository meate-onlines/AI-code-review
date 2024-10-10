import re
from datetime import datetime, timedelta
from config_loader import config
import gitlab

gitlab_config = config['gitlab']

gl = gitlab.Gitlab(gitlab_config['url'], gitlab_config['token'])

gl.auth()

# 获取当天的时间范围
today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
today_end = today_start + timedelta(days=1)

# 格式化时间字符串，GitLab API 需要 ISO 8601 格式的时间
start_date = today_start.isoformat()
end_date = today_end.isoformat()


# 查询当天创建的合并请求
def get_mrs_created_today():
    all_mrs = []
    # 遍历所有项目
    for project in gl.projects.list(all=True):
        # 获取项目中的所有合并请求
        mrs = project.mergerequests.list(state='opened', created_after=start_date, created_before=end_date)
        all_mrs.extend(mrs)
    return all_mrs


def parse_diffs(all_mrs, callback=None):
    for item in all_mrs:
        project = gl.projects.get(item.project_id)
        mr = project.mergerequests.get(item.iid)
        # 获取合并请求的更改详情
        changes = mr.changes()
        # 获取合并请求的更改详情
        for file_change in changes['changes']:
            file_path = file_change['new_path'] if 'new_path' in file_change else file_change['old_path']
            if file_change['deleted_file']:
                continue
            diff = file_change['diff']
            pattern = re.compile(r'@@ -\d+,\d+ \+(\d+),(\d+) @@')
            matches = pattern.findall(diff)
            diff_list = list(filter(None, diff.split('@@ -')))
            for index, item_diff in enumerate(diff_list):
                body = callback(item_diff)
                if not body:
                    continue
                print(item_diff)
                print(file_path)
                line = matches[index]
                start_line = int(line[0])
                end_line = int(line[1]) + start_line - 1
                body = f"### **文件：{file_path}" + f"第{start_line}到{end_line}行**\n" + f"\nAI review:{body}"
                discussion = mr.notes.create({
                    'body': body,
                    'position': {
                        'base_sha': mr.diff_refs.get('base_sha', ""),
                        'head_sha': mr.diff_refs.get('head_sha', ''),
                        'start_sha': mr.diff_refs.get('start_sha', ""),
                        'position_type': 'text',
                        'new_line': True,
                        # 'new_start_line': start_line,
                        # 'new_end_line': end_line,
                        "file_path": file_path,
                        'line': start_line,
                        'line_type': 'new'
                    },
                    'resolve': False
                })
                discussion.save()
            break


# 打印当天创建的合并请求
if __name__ == "__main__":
    mrs_today = get_mrs_created_today()
    parse_diffs(mrs_today)