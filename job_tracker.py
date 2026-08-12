import os
import re
import csv
import smtplib
import urllib.request
import urllib.parse
from email.mime.text import MIMEText
from email.header import Header

# ================= 筛选条件配置 =================
LOCATION_KEYWORDS = ['深圳', '全国', '不限', '远程', '广东']
JOB_KEYWORDS = ['数据分析', '数据科学', '商业分析', '数据', 'DA', 'DS', 'BA', 'Data Analyst', 'Data Scientist', 'Business Analyst']
CSV_FILE = 'shenzhen_2027_data_jobs.csv'

# GitHub 开源秋招/校招数据源列表
SOURCES = [
    {
        "name": "2027校招汇总源1",
        "url": "https://raw.githubusercontent.com/CodersGo/2027校招信息汇总/main/README.md"
    },
    {
        "name": "2026-2027校招汇总源2",
        "url": "https://raw.githubusercontent.com/hky2019/2025-2026-Job-Opportunities/main/README.md"
    }
]

def fetch_markdown(url):
    """抓取 Markdown 文本并对中文 URL 进行自动安全转义"""
    try:
        # 对包含中文的 URL 进行 safe 转义编码
        safe_url = urllib.parse.quote(url, safe=':/%?&=#')
        req = urllib.request.Request(safe_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"抓取失败 {url}: {e}")
        return ""

def parse_markdown_tables(content):
    """解析 Markdown 表格数据"""
    jobs = []
    lines = content.split('\n')
    for line in lines:
        if '|' in line:
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 4:
                company = parts
                job_title = parts
                location = parts if len(parts) > 3 else ""
                link = ""
                
                # 提取 Markdown 超链接 [名称](http...)
                link_match = re.search(r'\[.*?\]\((.*?)\)', line)
                if link_match:
                    link = link_match.group(1)

                if company and job_title and company not in ['公司名称', '公司', '---', ':---']:
                    jobs.append({
                        'company': company,
                        'job_title': job_title,
                        'location': location,
                        'link': link
                    })
    return jobs

def filter_jobs(jobs):
    """过滤深圳地区 + DA/DS/BA 相关岗位"""
    filtered = []
    for job in jobs:
        title_match = any(k.lower() in job['job_title'].lower() for k in JOB_KEYWORDS)
        loc_match = any(k in job['location'] for k in LOCATION_KEYWORDS) or not job['location']
        
        if title_match and loc_match:
            filtered.append(job)
    return filtered

def load_existing_jobs():
    """读取已有历史岗位（去重）"""
    existing = set()
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing.add((row['公司名称'], row['岗位名称']))
    return existing

def save_jobs(new_jobs):
    """保存新岗位至 CSV 表格"""
    file_exists = os.path.exists(CSV_FILE)
    with open(CSV_FILE, mode='a', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['公司名称', '岗位名称', '工作地点', '投递链接', '投递状态'])
        for job in new_jobs:
            writer.writerow([job['company'], job['job_title'], job['location'], job['link'], '未投递'])

def send_email_notification(new_jobs):
    """当有新岗位时发送邮件提醒"""
    sender = os.environ.get('EMAIL_SENDER')
    password = os.environ.get('EMAIL_PASSWORD')
    receiver = os.environ.get('EMAIL_RECEIVER')
    smtp_server = os.environ.get('SMTP_SERVER', 'smtp.qq.com')

    if not sender or not password or not receiver:
        print("未配置邮件环境变量，跳过邮件通知。")
        return

    content = f"🎉 发现新增深圳 2027 届 DA/DS/BA 岗位共 {len(new_jobs)} 个：\n\n"
    for job in new_jobs:
        content += f"🏢 公司：{job['company']}\n📌 岗位：{job['job_title']}\n📍 地点：{job['location']}\n🔗 链接：{job['link']}\n"
        content += "-" * 30 + "\n"

    message = MIMEText(content, 'plain', 'utf-8')
    message['From'] = Header(f"秋招助手 <{sender}>")
    message['To'] = Header(receiver)
    message['Subject'] = Header(f"【秋招提醒】新增 {len(new_jobs)} 个深圳数据岗位！", 'utf-8')

    try:
        server = smtplib.SMTP_SSL(smtp_server, 465)
        server.login(sender, password)
        server.sendmail(sender, [receiver], message.as_string())
        server.quit()
        print("邮件提醒发送成功！")
    except Exception as e:
        print(f"邮件发送失败: {e}")

def main():
    print("开始抓取秋招信息...")
    all_raw_jobs = []
    for src in SOURCES:
        print(f"正在抓取数据源: {src['name']}")
        content = fetch_markdown(src['url'])
        parsed = parse_markdown_tables(content)
        print(f"数据源 {src['name']} 解析到 {len(parsed)} 条原始信息")
        all_raw_jobs.extend(parsed)
    
    # 筛选
    target_jobs = filter_jobs(all_raw_jobs)
    existing_jobs = load_existing_jobs()
    
    # 去重提取新岗位
    new_jobs = []
    for job in target_jobs:
        key = (job['company'], job['job_title'])
        if key not in existing_jobs:
            new_jobs.append(job)
            existing_jobs.add(key)
            
    print(f"筛选匹配完成！本次新增 {len(new_jobs)} 个相关岗位。")
    if new_jobs:
        save_jobs(new_jobs)
        send_email_notification(new_jobs)
    else:
        print("当前暂无新增匹配岗位。")

if __name__ == '__main__':
    main()
    
