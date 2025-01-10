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
today = datetime.now().date()
# 格式化时间字符串，GitLab API 需要 ISO 8601 格式的时间
start_date = today_start.isoformat()
end_date = today_end.isoformat()


# 查询当天创建的合并请求
def get_mrs_created_today() -> list:
    all_mrs = []
    # 遍历所有项目
    for project in gl.projects.list(all=True):
        # 获取项目中的所有合并请求
        mrs = project.mergerequests.list(state='opened', updated_after=start_date, updated_before=end_date)
        # mrs = project.mergerequests.list(state='opened')
        all_mrs.extend(mrs)
    return all_mrs


def parse_diffs(all_mrs, callback=None) -> None:
    for item in all_mrs:
        project = gl.projects.get(item.project_id)
        mr = project.mergerequests.get(item.iid)
        # 获取合并请求的提交记录
        commits = mr.commits()
        for commit in commits:
            commit_date = datetime.strptime(commit.committed_date, "%Y-%m-%dT%H:%M:%S.%fZ").date()
            if commit_date == today:
                diffs = commit.diff(get_all=True, deleted_file=False, diff=True)
                for file_change in diffs:
                    file_path = file_change['new_path'] if 'new_path' in file_change else file_change['old_path']
                    if file_path.find('pom.xml') >= 0 :
                        continue
                    # Skip already processed files
                    if hasattr(mr, 'processed_files') and file_path in mr.processed_files:
                        print(f"Skipping already processed file: {file_path}")
                        continue
                    
                    # Initialize processed_files set if not exists
                    if not hasattr(mr, 'processed_files'):
                        mr.processed_files = set()
                    mr.processed_files.add(file_path)
                    # Skip image, video and other media files
                    if re.search(r'\.(jpg|jpeg|png|gif|bmp|svg|mp4|avi|mov|wmv|flv|mp3|wav|ogg|pdf|ico)$', file_path, re.IGNORECASE):
                        print(f"Skipping media file: {file_path}")
                        continue
                    print(f"file_path: {file_path}")
                    # 获取文件内容
                    try:
                        file_content = project.files.get(file_path, ref=mr.source_branch).decode().decode('utf-8')
                        body = callback(file_content)
                        if body['success'] == True:
                            create_merge_request_note(mr, body['data'], file_path, 1, False)
                        else:
                            process_diff_section(file_path, mr, file_change['diff'], callback)

                    except gitlab.exceptions.GitlabGetError:
                        print(f"Unable to read file: {file_path}")
                        continue

def clear_diff(diff) -> str:  # 清除diff中的无用信息
    diff_list = diff.split('\n')
    diff_list = [line for line in diff_list
                 if not (line.strip().startswith('-') or line.strip() == '')]
    if len(diff_list) > 0:
        diff = '\n'.join(diff_list)
        if contains_letters(diff):
            return diff
    return ""


def contains_letters(input_string) -> bool:
    # 正则表达式模式，用于匹配任何字母字符
    pattern = r'[a-zA-Z]'

    # 搜索字符串中的字母字符
    if re.search(pattern, input_string):
        return True

    return False

def create_merge_request_note(mr, body: str, file_path: str, start_line: int, end_line: any):
    """
    在合并请求中创建一个新的评论
    
    Args:
        mr: 合并请求对象
        body: 评论内容
        file_path: 文件路径
        start_line: 评论所在行号
    
    Returns:
        discussion: 创建的评论对象
    """
    if end_line == False:
        end_line = "全部代码"
    else:
        end_line = f"第{start_line}到{end_line}行"  
    comment_str = (
                f"### **文件：{file_path} {end_line}**\n"
                f"\nAI review:{body}"
    )
    print("----------------"+comment_str+"--------------------")
    discussion = mr.notes.create({
        'body': comment_str,
        'position': {
            'base_sha': mr.diff_refs.get('base_sha', ""),
            'head_sha': mr.diff_refs.get('head_sha', ''),
            'start_sha': mr.diff_refs.get('start_sha', ""),
            'position_type': 'text',
            'new_line': True,
            "file_path": file_path,
            'line': start_line,
            'line_type': 'new'
        },
        'resolve': False
    })
    
    return discussion

# ... existing code ...

def process_diff_section(file_path: str, mr, diff: str, callback) -> None:
    """
    处理单个文件的diff部分创建相应的合并请求评论
    
    Args:
        file_path: 文件路径
        mr: 合并请求对象
        diff: diff内容
        callback: 回调函数用于处理diff内容
    """
    pattern = re.compile(r'@@ -\d+,\d+ \+(\d+),(\d+) @@')
    matches = pattern.findall(diff)
    diff_list = list(filter(None, diff.split('@@ -')))
    
    for index, item_diff in enumerate(diff_list):
        try:
            clear_diff_line = clear_diff(item_diff)
            if not clear_diff_line:
                continue
            
            body = callback(item_diff)
            if body['success'] == False:
                continue
            
            line = matches[index]
            if len(line) == 0:
                continue
            
            start_line = int(line[0])
            end_line = int(line[1]) + start_line - 1
            
            discussion = create_merge_request_note(mr, body['data'], file_path, start_line, end_line)
            discussion.save()
            
        except Exception as e:
            print(f"An error occurred: {e}")

# 打印当天创建的合并请求
if __name__ == "__main__":
    mrs_today = get_mrs_created_today()
    parse_diffs(mrs_today)
    
