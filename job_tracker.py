import os
import re
import csv
import smtplib
import urllib.request
import urllib.parse
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.header import Header
from email.utils import formataddr

# ================= 筛选条件配置 =================
STRICT_SHENZHEN_KEYWORDS = ['深圳', 'Shenzhen', '深']
EXCLUDE_CITIES = ['广州', '郑州', '北京', '上海', '杭州', '成都', '武汉', '南京', '苏州', '合肥', '长沙', '重庆', '天津', '厦门', '东莞', '佛山']
DATA_JOB_KEYWORDS = ['数据分析', '数据科学', '商业分析', '数据', 'DA', 'DS', 'BA', 'Data', 'Analyst', 'Scientist']

CSV_ALL_JOBS = 'shenzhen_all_jobs.csv'       # 全量深圳岗位表格（两人共享）
CSV_DATA_JOBS = 'shenzhen_data_jobs.csv'     # 个人数据专岗表格（个人专属）

# 专注于 2027 届最新秋招/校招的数据源列表
SOURCES = [
    {
        "name": "xixicc2027 (2027届专属秋招信息每日聚合)",
        "url": "https://raw.githubusercontent.com/xixicc186/xixicc2027/main/README.md"
    }
]

def clean_markdown_text(text):
    """清洗 Markdown 文本"""
    if not text:
        return ""
    if isinstance(text, list):
        text = " ".join([str(i) for i in text])
    text = str(text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
    text = re.sub(r'\*+', '', text)
    return text.strip()

def extract_url_from_line(line):
    """提取 HTTP 链接"""
    urls = re.findall(r'https?://[^\s\)"\'>]+', str(line))
    if urls:
        return urls[0]
    return ""

def extract_date_from_line(line):
    """提取发布日期"""
    date_match = re.search(r'(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2})', str(line))
    if date_match:
        return date_match.group(1)
    return datetime.now().strftime('%Y-%m-%d')

def fetch_markdown(url):
    """抓取 Markdown 文本"""
    try:
        safe_url = urllib.parse.quote(url, safe=':/%?&=#')
        req = urllib.request.Request(safe_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"抓取失败 {url}: {e}")
        return ""

def parse_markdown_tables(content):
    """解析 Markdown 表格"""
    jobs = []
    lines = content.split('\n')
    for line in lines:
        if '|' in line:
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 3:
                raw_company = parts if len(parts) > 1 else ""
                raw_job = parts if len(parts) > 2 else ""
                raw_location = parts if len(parts) > 3 else ""
                
                company = clean_markdown_text(raw_company)
                job_title = clean_markdown_text(raw_job)
                location = clean_markdown_text(raw_location)

                if any(x in company for x in ['---', '公司', '名称', ':---', '公司名称']):
                    continue
                
                link = extract_url_from_line(line)
                pub_date = extract_date_from_line(line)

                if company and job_title and len(company) < 50:
                    jobs.append({
                        'company': company,
                        'job_title': job_title,
                        'location': location if location else '深圳',
                        'pub_date': pub_date,
                        'link': link
                    })
    return jobs

def filter_all_shenzhen_jobs(jobs):
    """筛选所有深圳地区的岗位（不限专业类型，适合共享）"""
    filtered = []
    for job in jobs:
        location = job['location']
        has_exclude_city = any(city in location for city in EXCLUDE_CITIES)
        has_shenzhen = any(sz in location for sz in STRICT_SHENZHEN_KEYWORDS)
        
        if has_shenzhen or (not has_exclude_city and (not location or location in ['不限', '全国', '远程'])):
            filtered.append(job)
    return filtered

def filter_data_jobs(jobs):
    """个人精选：深圳 + DA/DS/BA 数据相关岗位"""
    filtered = []
    for job in jobs:
        job_title = job['job_title']
        title_match = any(k.lower() in job_title.lower() for k in DATA_JOB_KEYWORDS)
        if title_match:
            filtered.append(job)
    return filtered

def load_existing_jobs(file_path):
    """读取已存历史岗位"""
    existing = set()
    if os.path.exists(file_path):
        with open(file_path, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing.add((row.get('公司名称', ''), row.get('岗位名称', '')))
    return existing

def save_jobs(file_path, new_jobs):
    """保存新岗位至指定 CSV 文件"""
    file_exists = os.path.exists(file_path)
    with open(file_path, mode='a', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['公司名称', '岗位名称', '工作地点', '发布/更新日期', '投递链接', '投递状态'])
        for job in new_jobs:
            writer.writerow([job['company'], job['job_title'], job['location'], job['pub_date'], job['link'], '未投递'])

def send_email_with_attachment(to_receivers, subject, content, attachment_file, attachment_name):
    """支持多收件人和自定附件的通用发信函数"""
    sender = os.environ.get('EMAIL_SENDER', '').strip()
    password = os.environ.get('EMAIL_PASSWORD', '').strip()
    smtp_server = os.environ.get('SMTP_SERVER', '').strip()

    if smtp_server:
        smtp_server = re.sub(r'^https?://', '', smtp_server).split('/')[0].split(':')[0]
    
    if not smtp_server:
        if '@qq.com' in sender.lower():
            smtp_server = 'smtp.qq.com'
        elif '@163.com' in sender.lower():
            smtp_server = 'smtp.163.com'
        elif '@gmail.com' in sender.lower():
            smtp_server = 'smtp.gmail.com'
        else:
            smtp_server = 'smtp.qq.com'

    if not sender or not password or not to_receivers:
        print("⚠️ 发件环境或收件人列表缺失，跳过发送。")
        return

    msg = MIMEMultipart()
    msg['From'] = formataddr(('秋招助手', sender))
    msg['To'] = ", ".join([formataddr(('求职伙伴', addr)) for addr in to_receivers])
    msg['Subject'] = Header(subject, 'utf-8')

    msg.attach(MIMEText(content, 'plain', 'utf-8'))

    # 添加指定表格附件
    if os.path.exists(attachment_file):
        try:
            with open(attachment_file, 'rb') as f:
                part = MIMEApplication(f.read(), Name=attachment_name)
                part.add_header('Content-Disposition', 'attachment', filename=('utf-8', '', attachment_name))
                msg.attach(part)
        except Exception as e:
            print(f"附件添加失败: {e}")

    try:
        server = smtplib.SMTP_SSL(smtp_server, 465, timeout=10)
        server.login(sender, password)
        server.sendmail(sender, to_receivers, msg.as_string())
        server.quit()
        print(f"📧 邮件成功发送给: {to_receivers}")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")

def main():
    print("开始抓取 2027 届最新秋招信息...")
    all_raw_jobs = []
    for src in SOURCES:
        print(f"正在抓取数据源: {src['name']}")
        content = fetch_markdown(src['url'])
        parsed = parse_markdown_tables(content)
        print(f"数据源 {src['name']} 解析到 {len(parsed)} 条 2027 届岗位信息")
        all_raw_jobs.extend(parsed)
    
    user_email = os.environ.get('EMAIL_RECEIVER', '').strip()
    gf_email = os.environ.get('EMAIL_GF_RECEIVER', '').strip()

    # 1. 筛选【深圳全量岗位】（供两人共享）
    all_shenzhen_jobs = filter_all_shenzhen_jobs(all_raw_jobs)
    existing_all_jobs = load_existing_jobs(CSV_ALL_JOBS)
    
    new_all_jobs = []
    for job in all_shenzhen_jobs:
        key = (job['company'], job['job_title'])
        if key not in existing_all_jobs:
            new_all_jobs.append(job)
            existing_all_jobs.add(key)

    # 构造两人接收列表
    shared_receivers = [user_email]
    if gf_email:
        shared_receivers.append(gf_email)

    print(f"📊 [全量深圳岗位] 累计匹配: {len(all_shenzhen_jobs)} 个, 本次新增: {len(new_all_jobs)} 个")

    # 发送【全量共享提醒】（发给两人）
    if new_all_jobs:
        save_jobs(CSV_ALL_JOBS, new_all_jobs)
        content = f"🎉 发现新增【深圳全量】2027 届校招岗位共 {len(new_all_jobs)} 个（含完整 Excel 表格附件）：\n\n"
        for job in new_all_jobs:
            content += f"🏢 公司：{job['company']}\n📌 岗位：{job['job_title']}\n📍 地点：{job['location']}\n📅 日期：{job['pub_date']}\n🔗 链接：{job['link']}\n"
            content += "-" * 30 + "\n"
        send_email_with_attachment(shared_receivers, f"【双人共享-秋招提醒】新增 {len(new_all_jobs)} 个深圳全量岗位！（含最新附件）", content, CSV_ALL_JOBS, "深圳2027全量校招岗位汇总表.csv")
    else:
        content = f"✅ 2027 届深圳全量秋招监控正常运行中！\n\n目前累计抓取到【深圳全量校招岗位】共 {len(all_shenzhen_jobs)} 个，已被全部为您归档存入附件表格中。"
        send_email_with_attachment(shared_receivers, "【双人共享-秋招助手】最新深圳全量校招岗位汇总表", content, CSV_ALL_JOBS, "深圳2027全量校招岗位汇总表.csv")

    # 2. 筛选【个人 DA/DS/BA 数据专岗】（仅发给自己）
    data_jobs = filter_data_jobs(all_shenzhen_jobs)
    existing_data_jobs = load_existing_jobs(CSV_DATA_JOBS)

    new_data_jobs = []
    for job in data_jobs:
        key = (job['company'], job['job_title'])
        if key not in existing_data_jobs:
            new_data_jobs.append(job)
            existing_data_jobs.add(key)

    print(f"📊 [个人数据专岗] 累计匹配: {len(data_jobs)} 个, 本次新增: {len(new_data_jobs)} 个")

    # 发送【个人专属提醒】（仅发给自己）
    if new_data_jobs:
        save_jobs(CSV_DATA_JOBS, new_data_jobs)
        content = f"🎯 [个人专属] 发现新增【深圳】2027 届 DA/DS/BA 数据岗位共 {len(new_data_jobs)} 个：\n\n"
        for job in new_data_jobs:
            content += f"🏢 公司：{job['company']}\n📌 岗位：{job['job_title']}\n📍 地点：{job['location']}\n📅 日期：{job['pub_date']}\n🔗 链接：{job['link']}\n"
            content += "-" * 30 + "\n"
        send_email_with_attachment([user_email], f"【个人专属-数据岗位】新增 {len(new_data_jobs)} 个深圳 DA/DS/BA 岗位！", content, CSV_DATA_JOBS, "深圳2027数据岗位精选表.csv")
    else:
        content = f"✅ [个人专属] 数据岗监控正常运行中！\n\n目前累计为你追踪到【深圳 DA/DS/BA 数据岗】共 {len(data_jobs)} 个，完整表格已随附件发送给您！"
        send_email_with_attachment([user_email], "【个人专属-数据岗位】最新深圳 DA/DS/BA 岗位精选表", content, CSV_DATA_JOBS, "深圳2027数据岗位精选表.csv")

if __name__ == '__main__':
    main()
