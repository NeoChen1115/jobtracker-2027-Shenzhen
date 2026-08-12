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
LOCATION_KEYWORDS = ['深圳', '全国', '不限', '远程', '广东', '华南']
JOB_KEYWORDS = ['数据分析', '数据科学', '商业分析', '数据', 'DA', 'DS', 'BA', 'Data', 'Analyst', 'Scientist']
CSV_FILE = 'shenzhen_2027_data_jobs.csv'

# GitHub 真实活跃的秋招/校招数据源列表
SOURCES = [
    {
        "name": "xixicc2027 (2027届秋招信息)",
        "url": "https://raw.githubusercontent.com/xixicc186/xixicc2027/main/README.md"
    },
    {
        "name": "Campus2026 (校招&实习信息)",
        "url": "https://raw.githubusercontent.com/namewyf/Campus2026/main/README.md"
    }
]

def clean_markdown_text(text):
    """把 Markdown 里的超链接 [文本](url)、加粗 **文本**、HTML 标签如 <br> 彻底清洗为纯文本"""
    if not text:
        return ""
    # 去除 <br>、<b> 等 HTML 标签
    text = re.sub(r'<[^>]+>', ' ', text)
    # 把 [文本](链接) 替换为纯文本
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
    # 去除加粗/斜体 **text** / *text*
    text = re.sub(r'\*+', '', text)
    # 去除多余空格与换行
    return text.strip()

def extract_url_from_line(line):
    """从整行提取一个最精准的 HTTP 投递链接"""
    urls = re.findall(r'https?://[^\s\)"\'>]+', line)
    if urls:
        return urls[0]
    return ""

def extract_date_from_line(line):
    """提取形如 2026-08-10 或 08/11 的发布日期"""
    date_match = re.search(r'(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2})', line)
    if date_match:
        return date_match.group(1)
    return datetime.now().strftime('%Y-%m-%d')

def fetch_markdown(url):
    """抓取 Markdown 文本并处理 URL 编码"""
    try:
        safe_url = urllib.parse.quote(url, safe=':/%?&=#')
        req = urllib.request.Request(safe_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"抓取失败 {url}: {e}")
        return ""

def parse_markdown_tables(content):
    """精细化解析 Markdown 表格，防止列混杂"""
    jobs = []
    lines = content.split('\n')
    for line in lines:
        if '|' in line:
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 4:
                raw_company = parts
                raw_job = parts
                raw_location = parts if len(parts) > 3 else ""
                
                # 过滤表格头部和格式线
                if any(x in raw_company for x in ['---', '公司', '名称', ':---']):
                    continue
                
                company = clean_markdown_text(raw_company)
                job_title = clean_markdown_text(raw_job)
                location = clean_markdown_text(raw_location)
                
                link = extract_url_from_line(line)
                pub_date = extract_date_from_line(line)

                if company and job_title and len(company) < 50:
                    jobs.append({
                        'company': company,
                        'job_title': job_title,
                        'location': location if location else '不限/全国',
                        'pub_date': pub_date,
                        'link': link
                    })
    return jobs

def filter_jobs(jobs):
    """过滤深圳地区 + DA/DS/BA 相关岗位"""
    filtered = []
    for job in jobs:
        job_title = job['job_title']
        location = job['location']
        
        title_match = any(k.lower() in job_title.lower() for k in JOB_KEYWORDS)
        loc_match = any(k in location for k in LOCATION_KEYWORDS) or not location or location == '不限/全国'
        
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
                existing.add((row.get('公司名称', ''), row.get('岗位名称', '')))
    return existing

def save_jobs(new_jobs):
    """保存新岗位至 CSV 表格，加入【发布/更新日期】列"""
    file_exists = os.path.exists(CSV_FILE)
    with open(CSV_FILE, mode='a', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['公司名称', '岗位名称', '工作地点', '发布/更新日期', '投递链接', '投递状态'])
        for job in new_jobs:
            writer.writerow([job['company'], job['job_title'], job['location'], job['pub_date'], job['link'], '未投递'])

def send_email_with_attachment(subject, content):
    """发送带 CSV 表格附件的邮件"""
    sender = os.environ.get('EMAIL_SENDER', '').strip()
    password = os.environ.get('EMAIL_PASSWORD', '').strip()
    receiver = os.environ.get('EMAIL_RECEIVER', '').strip()
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

    if not sender or not password or not receiver:
        print("⚠️ 未配置完整的 EMAIL_SENDER、EMAIL_PASSWORD 或 EMAIL_RECEIVER 环境变量，跳过发送邮件。")
        return

    # 创建带附件的邮件
    msg = MIMEMultipart()
    msg['From'] = formataddr(('秋招助手', sender))
    msg['To'] = formataddr(('订阅用户', receiver))
    msg['Subject'] = Header(subject, 'utf-8')

    # 添加正文
    msg.attach(MIMEText(content, 'plain', 'utf-8'))

    # 添加 CSV 文件附件
    if os.path.exists(CSV_FILE):
        try:
            with open(CSV_FILE, 'rb') as f:
                part = MIMEApplication(f.read(), Name='shenzhen_2027_data_jobs.csv')
                part.add_header('Content-Disposition', 'attachment', filename=('utf-8', '', '深圳2027数据岗位汇总表.csv'))
                msg.attach(part)
        except Exception as e:
            print(f"附件添加失败: {e}")

    try:
        server = smtplib.SMTP_SSL(smtp_server, 465, timeout=10)
        server.login(sender, password)
        server.sendmail(sender, [receiver], msg.as_string())
        server.quit()
        print("📧 带附件的邮件发送成功！")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")

def main():
    print("开始抓取与清理解析秋招信息...")
    all_raw_jobs = []
    for src in SOURCES:
        print(f"正在抓取数据源: {src['name']}")
        content = fetch_markdown(src['url'])
        parsed = parse_markdown_tables(content)
        print(f"数据源 {src['name']} 解析到 {len(parsed)} 条规范信息")
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
        content = f"🎉 发现新增深圳 2027 届 DA/DS/BA 岗位共 {len(new_jobs)} 个（最新 Excel 表格已发送至邮件附件）：\n\n"
        for job in new_jobs:
            content += f"🏢 公司：{job['company']}\n📌 岗位：{job['job_title']}\n📍 地点：{job['location']}\n📅 发布日期：{job['pub_date']}\n🔗 链接：{job['link']}\n"
            content += "-" * 30 + "\n"
        send_email_with_attachment(f"【秋招提醒】新增 {len(new_jobs)} 个深圳数据岗位！（含最新 Excel 附件）", content)
    else:
        print("当前无新增匹配岗位，发送带有最新表格附件的巡检邮件...")
        content = f"✅ 秋招监控系统正常运行中！\n\n当前累计为你追踪到 {len(existing_jobs)} 个符合条件的深圳 DA/DS/BA 岗位。\n本次巡检暂无新开放岗位，已将最新的完整岗位汇总表作为附件发送给你，方便随时查阅与投递！"
        send_email_with_attachment("【秋招助手】最新深圳数据岗位汇总表（含附件）", content)

if __name__ == '__main__':
    main()
