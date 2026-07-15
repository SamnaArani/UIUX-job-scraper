"""
SEO & Design Job Scraper Bot v5.0 - Customized for PIXEELLstudio
================================================================
منابع رایگان:
  • Remotive.com
  • Jobicy.com
  • Arbeitnow
  • Adzuna (با API key)
  • FindWork.dev
  • Cloudflare Worker

منابع پولی (اختیاری):
  • JSearch via RapidAPI  — پلن رایگان 200 req/ماه

Cover Letter:
  • هر آگهی یک دکمه "ChatGPT Cover Letter" داره
  • کلیک → باز شدن ChatGPT با پرامپت آماده (به طور پویا از prompt.txt یا کد)

ذخیره‌سازی اختیاری:
  • Google Sheets (Batch append)

متغیرهای محیطی (GitHub Secrets):
  TELEGRAM_BOT_TOKEN   — اجباری
  TELEGRAM_CHAT_ID     — اجباری (آیدی گروه با 100-)
  JOB_TOPIC_ID         — اختیاری (آیدی عددی تاپیک مورد نظر)
  RAPIDAPI_KEY         — اختیاری
  GSHEET_CREDENTIALS   — اختیاری (JSON)
  GSHEET_ID            — اختیاری
  CF_WORKER_URL        — اختیاری
  ADZUNA_APP_ID        — اختیاری
  ADZUNA_API_KEY       — اختیاری
"""

import html
import json
import logging
import os
import re
import time
import traceback
import urllib.parse
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

try:
    import gspread
    from google.oauth2.service_account import Credentials
    SHEETS_AVAILABLE = True
except ImportError:
    SHEETS_AVAILABLE = False

SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR / ".env")

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
RAPIDAPI_KEY       = os.environ.get("RAPIDAPI_KEY")
TELEGRAM_TOKEN     = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")
TELEGRAM_TOPIC_ID  = os.environ.get("JOB_TOPIC_ID") # هماهنگ با اکشن سکرت شما
GSHEET_CREDENTIALS = os.environ.get("GSHEET_CREDENTIALS", "")
GSHEET_ID          = os.environ.get("GSHEET_ID", "")
CF_WORKER_URL      = os.environ.get("CF_WORKER_URL")
ADZUNA_APP_ID      = os.environ.get("ADZUNA_APP_ID")
ADZUNA_API_KEY     = os.environ.get("ADZUNA_API_KEY")
FINDWORK_TOKEN     = os.environ.get("FINDWORK_TOKEN")

SEEN_JOBS_FILE     = Path("seen_jobs.txt")
MAX_SEEN_JOBS      = 2000
MAX_JOBS_PER_RUN   = 40

TEST_MODE          = False   # False = واقعی | True = تست
CHANNEL_USERNAME   = "@PIXEELLstudio"

# ─── کلمات کلیدی و امتیازدهی اختصاصی حوزه طراحی و توسعه ─────────────────────
SEARCH_QUERIES = [
    "UI UX Designer remote",
    "UX Designer remote",
    "Product Designer remote",
    "WordPress Developer remote",
    "WordPress Designer remote",
]

# کلمات کلیدی مثبت برای امتیازدهی (افزایش شانس ارسال)
BOOST_WORDS = [
    "ui", "ux", "user experience", "user interface", "product designer",
    "wordpress", "figma", "web design", "elementor", "front-end", "landing page"
]

# کلمات کلیدی منفی (کاهش امتیاز یا فیلتر نهایی)
BLACKLIST_WORDS = [
    "senior", "lead", "principal", "manager", "director", "head of",
    "us-only", "us only", "usa only", "citizens only", "visa sponsorship req",
    "seo", "sem", "link building" # فیلتر سئو برای همخوانی با فعالیت جدید شما
]

# ─── Helper Functions ─────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())

def extract_salary(job: dict) -> str:
    """استخراج حقوق از فیلدهای مختلف آگهی"""
    if job.get("salary"):
        return str(job["salary"])
    
    # JSearch fields
    min_sal = job.get("job_min_salary")
    max_sal = job.get("job_max_salary")
    currency = job.get("job_salary_currency") or "$"
    period = job.get("job_salary_period") or ""
    if min_sal and max_sal:
        p_str = f"/{period}" if period else ""
        return f"{currency}{min_sal:,} - {max_sal:,}{p_str}"
    
    # جستجو در توضیحات
    desc = (job.get("description") or job.get("job_description") or "").lower()
    match = re.search(r"(\$\d+[\d,]*\s*-\s*\$\d+[\d,]*|\$\d+[\d,]*\s*(?:per hour|/hr|a year|annually))", desc)
    if match:
        return match.group(1).strip()
    
    return ""

def get_job_type(job: dict) -> str:
    """تشخیص نوع همکاری بر اساس عنوان و توضیحات آگهی"""
    title = (job.get("title") or job.get("job_title") or "").lower()
    desc = (job.get("description") or job.get("job_description") or "").lower()
    combined = f"{title} {desc}"
    
    if any(k in combined for k in ["freelance", "contract", "hourly", "project", "فریلنس", "پروژه"]):
        return "🛠 پروژه‌ای / فریلنس"
    if any(k in combined for k in ["part-time", "parttime", "پاره وقت"]):
        return "⏱ پاره وقت"
    return "🏢 استخدامی / رسمی"

def generate_hashtags(job_title: str) -> str:
    """تولید هشتگ‌های اختصاصی مورد نیاز PIXEELLstudio"""
    t = (job_title or "").lower()
    tags = ["#استخدام"]
    if "ui" in t or "ux" in t or "interface" in t:
        tags.append("#UI_UX")
    if "wordpress" in t or "وردپرس" in t:
        tags.append("#WordPress")
    if "product" in t:
        tags.append("#Product_Design")
    if "developer" in t or "web" in t:
        tags.append("#Web_Development")
    if "remote" in t or "دورکاری" in t:
        tags.append("#Remote")
    return " ".join(tags)

def load_seen_jobs() -> set:
    if not SEEN_JOBS_FILE.exists():
        return set()
    try:
        with open(SEEN_JOBS_FILE, "r", encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    except Exception as e:
        log.warning(f"خطا در بارگذاری لیست مشاغل دیده‌شده: {e}")
        return set()

def save_seen_jobs(seen_set: set):
    jobs_list = list(seen_set)[-MAX_SEEN_JOBS:]
    try:
        with open(SEEN_JOBS_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(jobs_list) + "\n")
    except Exception as e:
        log.error(f"خطا در ذخیره لیست مشاغل دیده‌شده: {e}")

# ─── Core Logic: Evaluation ──────────────────────────────────────────────────

def evaluate_job(job: dict) -> tuple[int, list[str]]:
    """
    سیستم امتیازدهی پیشرفته نسخه ۵.۰ توسعه‌دهنده با تنظیمات شخصی طراحی و وردپرس.
    """
    title = (job.get("title") or job.get("job_title") or "").lower()
    desc = (job.get("description") or job.get("job_description") or "").lower()
    
    score = 15  # امتیاز پایه
    matched_skills = []

    # فیلتر بلک‌لیست سخت‌گیرانه (حذف کارهای غیرمرتبط)
    for bad in BLACKLIST_WORDS:
        if re.search(r"\b" + re.escape(bad) + r"\b", title):
            return -999, []
        if re.search(r"\b" + re.escape(bad) + r"\b", desc):
            score -= 15

    # فیلتر موقعیت‌های جغرافیایی نامناسب (آمریکا فقط)
    geo_blacklist = ["us only", "usa only", "united states only", "us residents only"]
    if any(g in desc for g in geo_blacklist) or any(g in title for g in geo_blacklist):
        return -999, []

    # امتیازدهی مثبت برای کلمات کلیدی هدف دیزاین و وردپرس
    for good in BOOST_WORDS:
        if re.search(r"\b" + re.escape(good) + r"\b", title):
            score += 15
            matched_skills.append(good.upper())
        elif re.search(r"\b" + re.escape(good) + r"\b", desc):
            score += 5
            if good.upper() not in matched_skills:
                matched_skills.append(good.upper())

    # امتیازدهی بر اساس زمان انتشار آگهی
    posted_at = job.get("posted_at", "")
    if "hour" in posted_at or "minute" in posted_at or "today" in posted_at.lower():
        score += 10

    return score, matched_skills

def is_old_job(job: dict) -> bool:
    """شناسایی آگهی‌های قدیمی برای جلوگیری از ارسال منقضی شده‌ها"""
    posted_at = str(job.get("posted_at", "")).lower()
    if any(k in posted_at for k in ["30+ days", "month", "year"]):
        return True
    return False

# ─── Scraper Engines ─────────────────────────────────────────────────────────

def fetch_remotive() -> list[dict]:
    log.info("درحال دریافت داده از Remotive...")
    url = "https://remotive.com/api/remote-jobs?category=design"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            jobs = []
            for j in data.get("jobs", []):
                jobs.append({
                    "id": f"remotive-{j.get('id')}",
                    "title": j.get("title"),
                    "company": j.get("company_name"),
                    "url": j.get("url"),
                    "source": "Remotive",
                    "posted_at": j.get("publication_date", "")[:10],
                    "salary": j.get("salary", ""),
                    "description": j.get("description", ""),
                    "location": j.get("candidate_required_location", "Remote")
                })
            return jobs
    except Exception as e:
        log.error(f"خطا در متد Remotive: {e}")
    return []

def fetch_jobicy() -> list[dict]:
    log.info("درحال دریافت داده از Jobicy...")
    url = "https://jobicy.com/api/v2/remote-jobs?count=50&industry=design"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            jobs = []
            for j in data.get("jobs", []):
                jobs.append({
                    "id": f"jobicy-{j.get('id')}",
                    "title": j.get("jobTitle"),
                    "company": j.get("companyName"),
                    "url": j.get("url"),
                    "source": "Jobicy",
                    "posted_at": j.get("pubDate", "")[:10],
                    "salary": j.get("annualSalaryMin") or j.get("jobSalary") or "",
                    "description": j.get("jobDescription", ""),
                    "location": j.get("jobGeo", "Remote")
                })
            return jobs
    except Exception as e:
        log.error(f"خطا در متد Jobicy: {e}")
    return []

def fetch_arbeitnow() -> list[dict]:
    log.info("درحال دریافت داده از Arbeitnow...")
    url = "https://www.arbeitnow.com/api/job-board-api"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            jobs = []
            for j in data.get("data", []):
                title = j.get("title", "").lower()
                # غربالگری اولیه متنی برای عدم هدررفت منابع
                if not any(w in title for w in ["design", "ux", "ui", "wordpress"]):
                    continue
                jobs.append({
                    "id": f"arbeitnow-{j.get('slug')}",
                    "title": j.get("title"),
                    "company": j.get("company_name"),
                    "url": j.get("url"),
                    "source": "Arbeitnow",
                    "posted_at": "اخیراً",
                    "salary": "",
                    "description": j.get("description", ""),
                    "location": "Germany / Remote" if j.get("remote") else "Germany"
                })
            return jobs
    except Exception as e:
        log.error(f"خطا در متد Arbeitnow: {e}")
    return []

def fetch_adzuna() -> list[dict]:
    if not ADZUNA_APP_ID or not ADZUNA_API_KEY:
        return []
    log.info("درحال دریافت داده از Adzuna...")
    url = "https://api.adzuna.com/v1/api/jobs/us/search/1"
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_API_KEY,
        "results_per_page": 30,
        "what": "UI UX Designer remote",
        "content-type": "application/json"
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()
            jobs = []
            for j in data.get("results", []):
                jobs.append({
                    "id": f"adzuna-{j.get('id')}",
                    "title": j.get("title"),
                    "company": j.get("company", {}).get("display_name"),
                    "url": j.get("redirect_url"),
                    "source": "Adzuna",
                    "posted_at": j.get("created", "")[:10],
                    "salary": j.get("salary_max") or "",
                    "description": j.get("description", ""),
                    "location": "Remote"
                })
            return jobs
    except Exception as e:
        log.error(f"خطا در متد Adzuna: {e}")
    return []

def fetch_findwork() -> list[dict]:
    if not FINDWORK_TOKEN:
        return []
    log.info("درحال دریافت داده از FindWork...")
    url = "https://findwork.dev/api/jobs/"
    headers = {"Authorization": f"Token {FINDWORK_TOKEN}"}
    params = {"search": "UI UX", "remote": "true"}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()
            jobs = []
            for j in data.get("results", []):
                jobs.append({
                    "id": f"findwork-{j.get('id')}",
                    "title": j.get("role"),
                    "company": j.get("company_name"),
                    "url": j.get("url"),
                    "source": "FindWork",
                    "posted_at": j.get("date_posted", "")[:10],
                    "salary": "",
                    "description": j.get("text", ""),
                    "location": "Remote"
                })
            return jobs
    except Exception as e:
        log.error(f"خطا در متد FindWork: {e}")
    return []

def fetch_cf_worker() -> list[dict]:
    if not CF_WORKER_URL:
        return []
    log.info("درحال دریافت داده از Cloudflare Worker...")
    try:
        r = requests.get(f"{CF_WORKER_URL.rstrip('/')}/jobs", timeout=15)
        if r.status_code == 200:
            data = r.json()
            jobs = []
            for j in data.get("jobs", []):
                title = j.get("title", "").lower()
                if not any(w in title for w in ["design", "ux", "ui", "wordpress"]):
                    continue
                jobs.append({
                    "id": j.get("id"),
                    "title": j.get("title"),
                    "company": j.get("company"),
                    "url": j.get("url"),
                    "source": j.get("source", "CF Worker"),
                    "posted_at": j.get("posted_at", "اخیراً"),
                    "salary": j.get("salary", ""),
                    "description": j.get("description", ""),
                    "location": j.get("location", "Remote")
                })
            return jobs
    except Exception as e:
        log.error(f"خطا در متد Cloudflare Worker: {e}")
    return []

def fetch_jsearch() -> list[dict]:
    if not RAPIDAPI_KEY:
        log.info("کلید JSearch یافت نشد. این بخش نادیده گرفته می‌شود.")
        return []
    log.info("درحال دریافت داده از JSearch via RapidAPI...")
    
    url = "https://jsearch.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
    }
    
    all_jobs = []
    for q in SEARCH_QUERIES[:3]:  # بهینه‌سازی شده برای کنترل دقیق مصرف اعتبار API
        log.info(f"درحال جستجوی کوئری JSearch برای: {q}")
        params = {
            "query": q,
            "page": "1",
            "num_pages": "1",
            "date_posted": "week"
        }
        try:
            r = requests.get(url, headers=headers, params=params, timeout=15)
            if r.status_code == 200:
                results = r.json().get("data", [])
                for j in results:
                    all_jobs.append({
                        "id": f"jsearch-{j.get('job_id')}",
                        "title": j.get("job_title"),
                        "company": j.get("employer_name"),
                        "url": j.get("job_apply_link"),
                        "source": "JSearch",
                        "posted_at": j.get("job_posted_at_datetime_utc", "")[:10],
                        "salary": extract_salary(j),
                        "description": j.get("job_description", ""),
                        "location": j.get("job_city") or "Remote"
                    })
            time.sleep(1) # تاخیر ایمن برای پیشگیری از Rate limit
        except Exception as e:
            log.error(f"خطا در دریافت داده JSearch برای کوئری '{q}': {e}")
            
    return all_jobs

# ─── Telegram API ─────────────────────────────────────────────────────────────

def send_telegram(text: str, reply_markup: str = None, thread_id: str = None) -> bool:
    if TEST_MODE:
        log.info(f"[TEST MODE] ارسال پیام شبیه‌سازی شد (تاپیک {thread_id}):\n{text}\n")
        return True

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("خطا: توکن ربات یا چت‌آیدی تلگرام تنظیم نشده است!")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if thread_id:
        payload["message_thread_id"] = thread_id

    # سیستم تلاش مجدد خودکار پیشرفته با تاخیر فزاینده (Exponential Backoff) برای مقابله با Flood Limit
    for attempt in range(3):
        try:
            r = requests.post(url, json=payload, timeout=15)
            res = r.json()
            if r.status_code == 200 and res.get("ok"):
                return True
            
            if r.status_code == 429:
                wait_sec = res.get("parameters", {}).get("retry_after", 5)
                log.warning(f"محدودیت سرعت تلگرام! تلاش مجدد پس از {wait_sec} ثانیه...")
                time.sleep(wait_sec + 1)
                continue
                
            log.error(f"خطا در ارسال پیام به تلگرام: {res}")
            return False
        except Exception as e:
            log.error(f"خطا در اتصال به سرور تلگرام (تلاش {attempt+1}): {e}")
            time.sleep(2)
            
    return False

# ─── Formatting / Buttons ────────────────────────────────────────────────────

def format_job(job: dict, score: int, skills: list) -> str:
    """قالب‌بندی فوق‌العاده شیک با استایل بومی و امضای PIXEELLstudio"""
    title = html.escape(job.get("title") or "بدون عنوان")
    company = html.escape(job.get("company") or "نامشخص")
    location = html.escape(job.get("location") or "Remote")
    source = html.escape(job.get("source") or "سایت کاریابی")
    salary = extract_salary(job)
    
    salary_line = f"💰 <b>حقوق: {html.escape(salary)}</b>" if salary else ""
    skills_line = f"⚡️ مهارت‌ها: <code>{', '.join(skills)}</code>" if skills else ""
    
    lines = [
        f"💼 <b>{title}</b>",
        f"🏢 {company}",
        f"📍 {location}",
    ]
    if salary_line:
        lines.append(salary_line)
    if skills_line:
        lines.append(skills_line)
        
    lines.append(f"🌐 منبع: {source}")
    return "\n".join(lines)

def build_job_buttons(job: dict) -> str:
    """
    ساخت دکمه‌های شیشه‌ای دو ردیفه شامل ثبت نام، کاورلتر هوشمند و جوین کانال.
    این تابع کاملاً مطابق با منطق نسخه ۵.۰ است و پرامپت را ابتدا از prompt.txt می‌خواند.
    """
    link = job.get("url") or ""
    title = job.get("title") or "Position"
    company = job.get("company") or "Company"
    
    if not link:
        return ""

    # منطق پویا برای بارگذاری قالب پرامپت از prompt.txt
    prompt_path = SCRIPT_DIR / "prompt.txt"
    if prompt_path.exists():
        try:
            prompt_tpl = prompt_path.read_text(encoding="utf-8").strip()
        except Exception:
            prompt_tpl = ""
    else:
        prompt_tpl = ""

    # در صورت عدم وجود فایل prompt.txt، از قالب پیش‌فرض بهینه‌شده برای طراحی و وردپرس استفاده می‌شود
    if not prompt_tpl:
        prompt_tpl = (
            "Write a professional, concise cover letter for the '{title}' position at '{company}'.\n"
            "Focus on my UI/UX Design and web development skills.\n\n"
            "Job link: {url}\n\n"
            "Keep it under 250 words, be targeted to the job requirements, and end with a call to action."
        )

    try:
        prompt_text = prompt_tpl.format(title=title, company=company, url=link)
    except Exception:
        # هندلر برای موارد خاص و ناسازگاری فرمت متن
        prompt_text = f"Write a cover letter for {title} at {company}. Link: {link}"

    encoded_prompt = urllib.parse.quote(prompt_text)
    chatgpt_url = f"https://chatgpt.com/?q={encoded_prompt}"
    
    keyboard = {"inline_keyboard": [
        [
            {"text": "🔗 Apply / مشاهده آگهی", "url": link},
            {"text": "🤖 ChatGPT Cover Letter", "url": chatgpt_url}
        ],
        [
            {"text": "📢 عضویت در کانال PIXEELLstudio", "url": f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}"}
        ]
    ]}
    return json.dumps(keyboard)

# ─── Google Sheets Integration ────────────────────────────────────────────────

def save_to_gsheet(rows: list):
    """ذخیره تمام آگهی‌های دور جاری در یک شیت گوگل به طور گروهی (کاهش نرخ مصرف API گوگل)"""
    if not SHEETS_AVAILABLE or not GSHEET_CREDENTIALS or not GSHEET_ID:
        return
    try:
        creds_dict = json.loads(GSHEET_CREDENTIALS)
        scope = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        
        sheet = client.open_by_key(GSHEET_ID).sheet1
        sheet.append_rows(rows, value_input_option="USER_ENTERED")
        log.info(f"تعداد {len(rows)} آگهی با موفقیت در Google Sheets ذخیره شد.")
    except Exception as e:
        log.error(f"خطا در ذخیره‌سازی داده‌ها در Google Sheets: {e}")

# ─── Main Executor ────────────────────────────────────────────────────────────

def main():
    log.info("شروع اسکرپ آگهی‌های شغلی طراحی و وردپرس...")
    
    seen_jobs = load_seen_jobs()
    raw_jobs = []

    # اجرای همزمان تمام متدهای اسکرپ موقعیت‌های شغلی طراحی
    raw_jobs.extend(fetch_remotive())
    raw_jobs.extend(fetch_jobicy())
    raw_jobs.extend(fetch_arbeitnow())
    raw_jobs.extend(fetch_adzuna())
    raw_jobs.extend(fetch_findwork())
    raw_jobs.extend(fetch_cf_worker())
    raw_jobs.extend(fetch_jsearch())

    qualified = []
    seen_in_current_run = set()
    
    stats = {"blacklisted": 0, "low_score": 0, "seen": 0, "old": 0}

    # ارزیابی، فیلترگذاری و فیلترینگ با دقت حداکثری بر اساس امتیازدهی هوشمند
    for job in raw_jobs:
        job_id = job.get("id")
        if not job_id:
            continue
            
        if job_id in seen_jobs or job_id in seen_in_current_run:
            stats["seen"] += 1
            continue
            
        if is_old_job(job):
            stats["old"] += 1
            continue

        score, skills = evaluate_job(job)
        if score == -999:
            stats["blacklisted"] += 1
            seen_jobs.add(job_id) # ذخیره تکراری بلک لیست ها برای راندمان اجرای بعدی
            continue
            
        if score < 10:  # حداقل حد آستانه امتیاز برای ورود به مرحله ارسال (MIN_SCORE_THRESHOLD)
            stats["low_score"] += 1
            continue

        seen_in_current_run.add(job_id)
        qualified.append((job, score, skills))

    # مرتب‌سازی موقعیت‌های شغلی تایید شده بر اساس بیشترین امتیاز تناسب تخصص
    qualified.sort(key=lambda x: x[1], reverse=True)

    active_sources = ["Remotive", "Jobicy", "Arbeitnow"]
    if RAPIDAPI_KEY: active_sources.append("JSearch")
    if CF_WORKER_URL: active_sources.append("CF Worker")
    if ADZUNA_API_KEY: active_sources.append("Adzuna")
    if FINDWORK_TOKEN: active_sources.append("FindWork")
    sources_line = ", ".join(active_sources)

    now = datetime.now().strftime("%Y-%m-%d")
    
    # استخراج درست تاپیک آیدی برای ساختارهای سوپرگروهی
    thread_id = str(TELEGRAM_TOPIC_ID) if TELEGRAM_TOPIC_ID and TELEGRAM_TOPIC_ID.isdigit() else None

    # اگر فرصت شغلی جدید با کیفیتی پیدا نشد
    if not qualified:
        log.info("آگهی واجد شرایط جدیدی در این دور یافت نشد.")
        send_telegram(
            f"🔍 <b>بررسی آگهی‌های روزانه PIXEELLstudio</b>\n"
            f"📅 {now}\n\n"
            f"❌ آگهی جدید و واجد شرایط پیدا نشد.\n"
            f"⛔️ {stats['blacklisted']} آگهی نامرتبط فیلتر شدند.\n"
            f"🔁 {stats['seen']} مورد تکراری نادیده گرفته شد.",
            thread_id=thread_id
        )
        save_seen_jobs(seen_jobs)
        return

    # ارسال پیام هدر زیبای روزانه کانال به همراه شمارش واقعی آمار فیلترها و آگهی‌های هدف
    send_telegram(
        f"🔍 <b>فرصت‌های شغلی بین‌المللی امروز</b>\n"
        f"📅 {now}\n"
        f"📊 <b>{len(qualified)}</b> آگهی جدید پیدا شد | ⛔️ {stats['blacklisted']} فیلتر شد\n"
        f"➖➖➖➖➖➖➖➖\n"
        f"📢 کانال رسمی: {CHANNEL_USERNAME}",
        thread_id=thread_id
    )
    time.sleep(1.5)

    sent = 0
    sheet_rows = []

    # ارسال جداگانه آگهی‌ها به تلگرام به همراه سیستم تاخیر ضد اسپم
    for job, score, skills in qualified[:MAX_JOBS_PER_RUN]:
        try:
            base_msg = format_job(job, score, skills)
            job_type = get_job_type(job)
            hashtags = generate_hashtags(job.get("title", ""))

            msg = (
                f"{base_msg}\n"
                f"⚙️ نوع همکاری: <b>{job_type}</b>\n\n"
                f"📌 {hashtags}\n"
                f"➖➖➖➖➖➖➖➖\n"
                f"📢 کانال رسمی: {CHANNEL_USERNAME}"
            )

            buttons = build_job_buttons(job)

            # اصلاح باگ حیاتی: متغیر thread_id اینجا به درستی برای تک تک آگهی ها پاس داده شد
            if send_telegram(msg, reply_markup=buttons if buttons else None, thread_id=thread_id):
                sent += 1
                seen_jobs.add(job.get("id"))
                
                # پرامپت انکود شده برای ذخیره در گوگل‌شیت
                prompt_text = "Generate cover letter prompt"
                sheet_rows.append([
                    job.get("title", ""), job.get("company", ""),
                    job.get("source", ""), job.get("url", ""),
                    job.get("posted_at", ""), job.get("salary", ""),
                    score, job.get("location", ""),
                    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                    "New", prompt_text
                ])

            time.sleep(2.0) # تاخیر ایمن ۲ ثانیه‌ای بین آگهی‌ها برای عدم دریافت Flood Limit از سرور تلگرام

        except Exception as e:
            log.error(f"خطا در پردازش آگهی {job.get('id')}: {e}")
            traceback.print_exc()

    # آپدیت نهایی دیتابیس لوکال و گوگل‌شیت آگهی‌های فرستاده شده
    save_seen_jobs(seen_jobs)
    
    if sheet_rows:
        save_to_gsheet(sheet_rows)

    log.info(f"پایان کار با موفقیت! تعداد ارسال‌های موفقیت‌آمیز امروز: {sent} آگهی.")

if __name__ == "__main__":
    main()
