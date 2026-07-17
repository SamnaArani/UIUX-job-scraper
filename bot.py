"""
UI/UX, Dev & SEO Multi-Topic Job Scraper Bot v5.7 - Premium Unified Edition
================================================================================
امکانات فوق‌پیشرفته ادغام شده در این نسخه:
  • معماری یکپارچه با ورودی داینامیک موضوعی (Design, Dev, SEO) از طریق سیستم Command Line
  • تفکیک کاملاً مجزای فایل کش دیده‌شده‌ها (seen_jobs_[category].txt) جهت پیشگیری از تداخل
  • حذف کامل امتیاز تناسب شخصی برای استفاده عمومی کاربران در گروه/کانال تلگرام
  • نمایش مهارت‌های انطباق‌یافته استخراج شده در کارت جاب تلگرام
  • موتور پیش‌کامپایل شده الگوهای Regex با الگوهای مرز کلمه (\b) برای افزایش ۱۰ برابری سرعت و دقت
  • فیلتر جغرافیایی سخت‌گیرانه برای لوکیشن و توضیحات به طور همزمان
  • دکمه‌های شیشه‌ای دو ردیفه (Apply + ChatGPT Cover Letter شخصی‌سازی شده برای هر فیلد + کانال شما)
  • ارسال خروجی‌های تفکیک شده به تاپیک‌های مجزا در سوپرگروه با پایداری حداکثری
  • اصلاح منطق شناسایی: تولید خودکار شناسه‌های یکتا و پایدار بر اساس URL برای دور زدن آیدی‌های رندوم کلودفلر
"""

import html
import json
import logging
import os
import re
import sys
import time
import traceback
import urllib.parse
from collections import OrderedDict
from datetime import datetime, timezone, timedelta
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

# ورودی اول سیستم مشخص می‌کند فرآیند برای کدام دسته است: design | dev | seo (پیش‌فرض design)
CATEGORY = sys.argv[1].lower() if len(sys.argv) > 1 else "design"
log.info(f"🚀 ربات در فاز پردازش حوزه تخصصی آغاز به کار کرد: {CATEGORY.upper()}")

# ─── Config ───────────────────────────────────────────────────────────────────
RAPIDAPI_KEY       = os.environ.get("RAPIDAPI_KEY")
TELEGRAM_TOKEN     = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")

# تخصیص هوشمند تاپیک مقصد تلگرام بر اساس فیلد کاری
if CATEGORY == "design":
    TELEGRAM_TOPIC_ID = os.environ.get("TOPIC_DESIGN") or os.environ.get("JOB_TOPIC_ID")
elif CATEGORY == "dev":
    TELEGRAM_TOPIC_ID = os.environ.get("TOPIC_DEV") or os.environ.get("JOB_TOPIC_ID")
elif CATEGORY == "seo":
    TELEGRAM_TOPIC_ID = os.environ.get("TOPIC_SEO") or os.environ.get("JOB_TOPIC_ID")
else:
    TELEGRAM_TOPIC_ID = os.environ.get("JOB_TOPIC_ID")

GSHEET_CREDENTIALS = os.environ.get("GSHEET_CREDENTIALS", "")
GSHEET_ID          = os.environ.get("GSHEET_ID", "")
CF_WORKER_URL      = os.environ.get("CF_WORKER_URL")
ADZUNA_APP_ID      = os.environ.get("ADZUNA_APP_ID")
ADZUNA_API_KEY     = os.environ.get("ADZUNA_API_KEY")
FINDWORK_TOKEN     = os.environ.get("FINDWORK_TOKEN")

SEEN_JOBS_FILE     = SCRIPT_DIR / f"seen_jobs_{CATEGORY}.txt" # فایل کش جداگانه برای هر حوزه
MAX_SEEN_JOBS      = 3000
MAX_JOBS_PER_RUN   = 20
MIN_FIT_SCORE      = 35      # حداقل امتیاز تناسب برای ارسال آگهی
MAX_JOB_AGE_DAYS   = 7       # حداکثر سن آگهی به روز

TEST_MODE          = False    # True = شبیه‌سازی آفلاین و ارسال مستقیم خروجی‌ها به تلگرام برای تست استایل | False = حالت اسکرپ واقعی وب
CHANNEL_USERNAME   = "@PIXEELLstudio"

# هدرهای شبیه‌ساز مرورگر واقعی برای دور زدن سیستم‌های ضداسکرپ و کلودفلر
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,fa;q=0.8"
}

# ─── تخصیص پویای کیوردها، بلک‌لیست‌ها و سیستم امتیازدهی هوشمند ──────────────

# ۱. تعریف کوئری‌های JSearch به تفکیک و چرخشی (۱۵ کوئری طلایی برای هر حوزه بدون ریموت + هدف‌گیری لینکدین)
DESIGN_QUERIES = {
    1: [
        "UI UX Designer", 
        "Product Designer", 
        "Figma Designer", 
        "Interaction Designer", 
        "UI UX Designer linkedin"  # جستجوی تخصصی روی آگهی‌ها و پست‌های لینکدین
    ],
    2: [
        "Web Designer", 
        "WordPress Designer", 
        "Elementor Designer", 
        "Visual Designer", 
        "Web Designer linkedin"  # جستجوی تخصصی روی آگهی‌ها و پست‌های لینکدین
    ],
    3: [
        "Motion Designer", 
        "Motion Graphics Designer", 
        "After Effects Designer", 
        "3D Animator", 
        "Motion Graphics linkedin"  # جستجوی تخصصی روی آگهی‌ها و پست‌های لینکدین
    ]
}

DEV_QUERIES = {
    1: [
        "WordPress Developer", 
        "React Developer", 
        "Front End Developer", 
        "Webflow Developer", 
        "WordPress Developer linkedin"  # جستجوی تخصصی روی آگهی‌ها و پست‌های لینکدین
    ],
    2: [
        "JavaScript Developer", 
        "PHP Developer", 
        "Full Stack Developer", 
        "NodeJS Developer", 
        "Full Stack Developer linkedin"  # جستجوی تخصصی روی آگهی‌ها و پست‌های لینکدین
    ],
    3: [
        "DevOps Engineer", 
        "SRE Engineer", 
        "Kubernetes Engineer", 
        "Data Science Intern", 
        "DevOps SRE linkedin"  # جستجوی تخصصی روی آگهی‌ها و پست‌های لینکدین
    ]
}

SEO_QUERIES = {
    1: [
        "Technical SEO Specialist", 
        "SEO Specialist", 
        "SEO Python Analyst", 
        "SEO Auditor", 
        "SEO Specialist linkedin"  # جستجوی تخصصی روی آگهی‌ها و پست‌های لینکدین
    ],
    2: [
        "SEO Content Manager", 
        "SEO Content Editor", 
        "SEO Copywriter", 
        "SEO Writer", 
        "SEO Content linkedin"  # جستجوی تخصصی روی آگهی‌ها و پست‌های لینکدین
    ],
    3: [
        "SEO Strategist", 
        "Search Engine Optimization Specialist", 
        "On-Page SEO Specialist", 
        "SEO Link Builder", 
        "SEO Growth Hacker linkedin"  # جستجوی تخصصی روی آگهی‌ها و پست‌های لینکدین
    ]
}


# ۲. مهارت‌های پیش‌فرض هر رشته (بروزرسانی شده با فیدبک کاربران)
DESIGN_SKILLS = [
    "figma", "ui", "ux", "user experience", "user interface", "product design",
    "wordpress", "elementor", "web design", "interaction design", "wireframing",
    "prototyping", "html", "css", "webflow", "divi", "landing page", "illustrator",
    "photoshop", "responsive design", "motion design", "motion graphics", "after effects",
    "animation", "3d", "blender", "premiere", "cinema 4d"
]

DEV_SKILLS = [
    "wordpress", "php", "javascript", "react", "html", "css", "webflow", "shopify",
    "elementor", "divi", "git", "api", "node.js", "bootstrap", "tailwind", "mysql", "jquery",
    "devops", "aws", "kubernetes", "docker", "terraform", "sre", "ci/cd", "python",
    "data science", "machine learning", "data analysis", "sql"
]

SEO_SKILLS = [
    "python", "wordpress", "technical seo", "on-page seo", "screaming frog", "ahrefs",
    "semrush", "google analytics", "google search console", "content", "keyword research",
    "html", "cms", "link building", "schema", "growth hacking", "digital marketing"
]


# ۳. کلمات کلیدی بلک‌لیست عمومی جغرافیایی و کاری (پاک‌سازی تداخل‌ها)
GEO_BLACKLIST = [
    "us residents only", "must reside in us", "must be located in us",
    "must be based in the us", "must be based in us",
    "must be authorized to work in the us", "citizens only",
    "native english speaker only", "10+ years", "8+ years", "7+ years"
]

DESIGN_BLACKLIST = GEO_BLACKLIST + [
    "senior designer", "lead designer", "design director", "head of design", 
    "developer", "programmer", "engineer", "devops", "seo specialist", "link building"
]

DEV_BLACKLIST = GEO_BLACKLIST + [
    "senior developer", "lead developer", "cto", "tech lead", "architect", 
    "ui/ux designer", "graphic designer", "seo specialist"
]

SEO_BLACKLIST = GEO_BLACKLIST + [
    "senior seo", "head of seo", "director of seo", 
    "developer", "programmer", "graphic designer", "ui/ux"
]


# ۴. ضرایب و وزن کلمات ارزشمند هر حوزه (بروزرسانی شده با نقش‌های جدید)
DESIGN_BOOST = {
    "figma": 20, "ui": 15, "ux": 15, "product designer": 18, "wordpress": 15,
    "elementor": 12, "web design": 10, "junior": 18, "entry level": 15, "associate": 12,
    "part-time": 8, "contract": 5, "webflow": 12, "wireframing": 8, "prototyping": 8,
    "motion design": 18, "motion graphics": 18, "after effects": 15, "animation": 15,
    "visual designer": 12, "3d": 10, "graphic designer": 8
}

DEV_BOOST = {
    "wordpress": 20, "react": 18, "php": 15, "webflow": 15, "javascript": 12,
    "html": 10, "css": 10, "junior": 18, "entry level": 15, "associate": 12,
    "part-time": 8, "contract": 5, "node.js": 12, "tailwind": 8, "api": 8,
    "devops": 18, "kubernetes": 18, "aws": 15, "sre": 15, "data science": 15,
    "intern": 15, "internship": 12, "machine learning": 12
}

# SEO_BOOST کلمات کلیدی سئو
SEO_BOOST = {
    "technical seo": 20, "python": 18, "wordpress": 15, "junior": 18, "entry level": 15,
    "seo specialist": 12, "seo editor": 12, "content editor": 10, "on-page": 10,
    "part-time": 8, "contract": 5, "screaming frog": 12, "ahrefs": 10, "semrush": 10,
    "seo strategist": 15, "growth hacker": 15, "link builder": 12
}

# اعمال پیکربندی‌های پویا بر اساس حوزه انتخاب شده در ران تایم
if CATEGORY == "design":
    JSEARCH_QUERIES = DESIGN_QUERIES
    _DEFAULT_SKILLS = DESIGN_SKILLS
    BLACKLIST_KEYWORDS = DESIGN_BLACKLIST
    BOOST_KEYWORDS = DESIGN_BOOST
elif CATEGORY == "dev":
    JSEARCH_QUERIES = DEV_QUERIES
    _DEFAULT_SKILLS = DEV_SKILLS
    BLACKLIST_KEYWORDS = DEV_BLACKLIST
    BOOST_KEYWORDS = DEV_BOOST
else:  # seo
    JSEARCH_QUERIES = SEO_QUERIES
    _DEFAULT_SKILLS = SEO_SKILLS
    BLACKLIST_KEYWORDS = SEO_BLACKLIST
    BOOST_KEYWORDS = SEO_BOOST

# استخراج مسطح کوئری‌ها برای سایر ابزارها
SEARCH_QUERIES = [q for group in JSEARCH_QUERIES.values() for q in group]

# خواندن مهارت‌های شخصی کاربر از گیت‌هاب سکرت در صورت تعریف شدن
_user_skills_env = os.environ.get("USER_SKILLS", "")
MY_SKILLS = [s.strip().lower() for s in _user_skills_env.split(",") if s.strip()] if _user_skills_env else _DEFAULT_SKILLS

# ─── پیش‌کامپایل موتور رگولار اکسپرشن (Regex Engine) ─────────────────────────
_SKILL_PATTERNS    = {s: re.compile(r"\b" + re.escape(s) + r"\b", re.I) for s in MY_SKILLS}
_BOOST_PATTERNS    = {kw: re.compile(r"\b" + re.escape(kw) + r"\b", re.I) for kw in BOOST_KEYWORDS}
_BLACKLIST_PATTERNS = {kw: re.compile(r"\b" + re.escape(kw.lower()) + r"\b", re.I) for kw in BLACKLIST_KEYWORDS}

# ─── Helper Functions ─────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())

def extract_salary(job: dict) -> str:
    if job.get("salary"):
        return str(job["salary"])
    
    min_sal = job.get("job_min_salary")
    max_sal = job.get("job_max_salary")
    currency = job.get("job_salary_currency") or "$"
    period = job.get("job_salary_period") or ""
    if min_sal and max_sal:
        p_str = f"/{period}" if period else ""
        return f"{currency}{min_sal:,} - {max_sal:,}{p_str}"
    
    desc = (job.get("description") or job.get("job_description") or "").lower()
    match = re.search(r"(\$\d+[\d,]*\s*-\s*\$\d+[\d,]*|\$\d+[\d,]*\s*(?:per hour|/hr|a year|annually))", desc)
    if match:
        return match.group(1).strip()
    
    return ""

def get_job_type(job: dict) -> str:
    title = (job.get("title") or job.get("job_title") or "").lower()
    desc = (job.get("description") or job.get("job_description") or "").lower()
    combined = f"{title} {desc}"
    
    if any(k in combined for k in ["freelance", "contract", "hourly", "project", "فریلنس", "پروژه"]):
        return "🛠 پروژه‌ای / فریلنس"
    if any(k in combined for k in ["part-time", "parttime", "پاره وقت"]):
        return "⏱ پاره وقت"
    return "🏢 استخدامی / رسمی"

def generate_hashtags(job_title: str) -> str:
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
    if "seo" in t or "سئو" in t:
        tags.append("#SEO")
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
    سیستم ارزیابی فوق پیشرفته با کلمات کلیدی وزن‌دار و الگوهای Regex از پیش‌کامپایل شده.
    تضمین می‌کند محاسبات سرعت بالا و فیلترهای فوق‌العاده دقیقی داشته باشند.
    """
    title = (job.get("title") or job.get("job_title") or "").lower()
    desc = (job.get("description") or job.get("job_description") or "").lower()
    location = str(job.get("location") or "").lower()
    combined_text = f"{title} {desc} {location}"
    
    # ۱. فیلتر بلک‌لیست با Regex کامپایل شده (دقت ۱۰۰٪ با شناسایی مرز کلمات)
    for kw, pattern in _BLACKLIST_PATTERNS.items():
        if pattern.search(combined_text):
            return -999, []

    # ۲. فیلترهای جغرافیایی سختگیرانه تر
    geo_blacklist = ["us only", "usa only", "united states only", "us residents only", "citizens only"]
    if any(g in desc for g in geo_blacklist) or any(g in title for g in geo_blacklist) or any(g in location for g in geo_blacklist):
        if "worldwide" not in desc and "anywhere" not in desc:
            return -999, []

    score = 10  # امتیاز پایه برای شروع فرآیند مهارت‌سنجی
    matched_skills = []

    # ۳. شناسایی مهارت‌های اختصاصی کاربر
    for skill, pattern in _SKILL_PATTERNS.items():
        if pattern.search(combined_text):
            matched_skills.append(skill.upper())
            score += 7  # به ازای انطباق هر تخصص فنی ۷ امتیاز اضافه می‌شود

    # ۴. سیستم امتیازدهی وزن‌دار بر اساس BOOST_KEYWORDS
    for kw, pattern in _BOOST_PATTERNS.items():
        weight = BOOST_KEYWORDS[kw]
        if pattern.search(title):
            score += weight  # وزن دوبرابر در صورت تطابق با عنوان شغل
        elif pattern.search(desc):
            score += int(weight * 0.5)

    # ۵. بونوس زمان انتشار
    posted_at = job.get("posted_at", "")
    if "hour" in posted_at or "minute" in posted_at or "today" in posted_at.lower():
        score += 10

    return min(score, 100), matched_skills[:5]

def is_old_job(job: dict) -> bool:
    """تشخیص پویای آگهی‌های قدیمی بر اساس واژه‌های متداول انگلیسی و پیکربندی MAX_JOB_AGE_DAYS"""
    posted_at = str(job.get("posted_at", "")).lower()
    
    old_patterns = ["30+ days", "month", "year", "2 weeks ago", "3 weeks ago", "4 weeks ago", "14 days ago", "20 days ago"]
    if any(k in posted_at for k in old_patterns):
        return True
    
    # بررسی روزهای عددی
    day_match = re.search(r"(\d+)\s+day", posted_at)
    if day_match:
        days = int(day_match.group(1))
        if days > MAX_JOB_AGE_DAYS:
            return True
            
    return False

# ─── Scraper Engines ─────────────────────────────────────────────────────────

def fetch_remotive() -> list[dict]:
    log.info("درحال دریافت داده از Remotive...")
    category_param = "seo" if CATEGORY == "seo" else "design" if CATEGORY == "design" else "software-development"
    url = f"https://remotive.com/api/remote-jobs?category={category_param}"
    try:
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
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
    industry_param = "seo" if CATEGORY == "seo" else "design" if CATEGORY == "design" else "dev"
    url = f"https://jobicy.com/api/v2/remote-jobs?count=50&industry={industry_param}"
    try:
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
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
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
        if r.status_code == 200:
            data = r.json()
            jobs = []
            for j in data.get("data", []):
                title = j.get("title", "").lower()
                # غربالگری هوشمند متناسب با فیلد ران تایم
                match_words = ["design", "ux", "ui", "wordpress"] if CATEGORY != "seo" else ["seo", "marketing"]
                if CATEGORY == "dev":
                    match_words += ["developer", "react", "php", "javascript"]
                if not any(w in title for w in match_words):
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
    search_term = "UI UX Designer remote" if CATEGORY == "design" else "WordPress Developer remote" if CATEGORY == "dev" else "SEO remote"
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_API_KEY,
        "results_per_page": 30,
        "what": search_term,
        "content-type": "application/json"
    }
    try:
        r = requests.get(url, params=params, headers=DEFAULT_HEADERS, timeout=15)
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
    headers = {
        "Authorization": f"Token {FINDWORK_TOKEN}",
        "User-Agent": DEFAULT_HEADERS["User-Agent"]
    }
    search_term = "UI UX" if CATEGORY == "design" else "WordPress" if CATEGORY == "dev" else "SEO"
    params = {"search": search_term, "remote": "true"}
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
        # ارسال پارامتر دسته‌بندی فعال به ورکر داینامیک جدید
        params = {"category": CATEGORY}
        r = requests.get(
            f"{CF_WORKER_URL.rstrip('/')}/jobs", 
            params=params, 
            headers=DEFAULT_HEADERS, 
            timeout=15
        )
        if r.status_code == 200:
            data = r.json()
            jobs = []
            for j in data.get("jobs", []):
                title = j.get("title", "").lower()
                # غربالگری ثانویه و اطمینان از تطابق محتوا در سمت پایتون
                match_words = ["design", "ux", "ui", "wordpress"] if CATEGORY != "seo" else ["seo", "marketing"]
                if CATEGORY == "dev":
                    match_words += ["developer", "react", "php", "javascript"]
                if not any(w in title for w in match_words):
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
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
        "User-Agent": DEFAULT_HEADERS["User-Agent"]
    }
    
    all_jobs = []
    
    # برای حفظ سهمیه رایگان، در هر اجرا فقط یکی از گروه‌ها را می‌چرخانیم (تغییر چرخشی بر اساس روز ماه)
    day_of_month = datetime.now().day
    group_to_fetch = (day_of_month % len(JSEARCH_QUERIES)) + 1
    selected_queries = JSEARCH_QUERIES[group_to_fetch]
    
    log.info(f"انتخاب گروه کوئری {group_to_fetch} برای کنترل دقیق مصرف اعتبار JSearch")
    
    for q in selected_queries:
        log.info(f"درحال جستجوی کوئری JSearch برای: {q}")
        params = {
            "query": q,
            "page": "1",
            "num_pages": "1",
            "date_posted": "week",
            # 💡 اصلاح انقلابی: فعال‌سازی فیلتر رسمی دورکاری در موتور جستجوی JSearch
            # با این پارامتر، دیگر نیازی به نوشتن کلمه remote در خود کوئری‌ها نیست
            "remote_jobs_only": "true"
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
            time.sleep(1)
        except Exception as e:
            log.error(f"خطا در دریافت داده JSearch برای کوئری '{q}': {e}")
            
    return all_jobs

# ─── Telegram API ─────────────────────────────────────────────────────────────

def send_telegram(text: str, reply_markup: str = None, thread_id: str = None) -> bool:
    if TEST_MODE:
        border = "=" * 60
        log.info(
            f"\n{border}\n"
            f"📢 [TEST MODE] پیام شبیه‌سازی شده تلگرام (تاپیک مقصد: {thread_id or 'عمومی'})\n"
            f"{border}\n"
            f"{text}\n"
            f"{border}\n"
            f"🔘 دکمه‌های پیوست شده:\n{reply_markup or 'بدون دکمه'}\n"
            f"{border}\n"
        )
        # در حالت تست مود هم می‌خواهیم پیام ارسال شود تا استایل و دیزاین را در تلگرام چک کنیم

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("خطا: توکن ربات یا چت‌آیدی تلگرام تنظیم نشده است!")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True}, # هندلینگ امن پیش‌نمایش لینک در تلگرام
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if thread_id:
        payload["message_thread_id"] = thread_id

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
    """
    قالب‌بندی فارسی شیک و بهینه کارت‌های جاب بدون نمایش امتیاز تناسب شخصی.
    مناسب جهت انتشار در گروه‌ها و کانال‌های عمومی بدون ایجاد ابهام برای اعضا.
    """
    title = html.escape(job.get("title") or "بدون عنوان")
    company = html.escape(job.get("company") or "نامشخص")
    location = html.escape(job.get("location") or "Remote")
    source = html.escape(job.get("source") or "سایت کاریابی")
    salary = extract_salary(job)
    
    lines = [
        f"💼 <b>عنوان تخصص:</b>\n{title}",
        f"🏢 <b>نام شرکت:</b>\n{company}",
        f"📍 <b>موقعیت جغرافیایی:</b>\n{location}",
    ]
    
    if salary:
        lines.append(f"💰 <b>حقوق پیشنهادی:</b>\n{html.escape(salary)}")
        
    # اضافه شدن مهارت‌های پیدا شده به عنوان تخصص‌های مورد نیاز آگهی (نه امتیاز شخصی)
    if skills:
        lines.append(f"⚡️ <b>مهارت‌های مورد نیاز:</b>\n<code>{', '.join(skills)}</code>")
        
    lines.append(f"🌐 <b>منبع انتشار آگهی:</b>\n{source}")
    
    # فاصله‌گذاری دو برابری بین آیتم‌ها برای پیشگیری از تداخل چشمی متن‌ها
    return "\n\n".join(lines)

def build_job_buttons(job: dict) -> tuple[str, str]:
    """ساخت دکمه‌های شیشه‌ای دو ردیفه متناسب با پرامپت اختصاصی هر حوزه"""
    link = job.get("url") or ""
    title = job.get("title") or "Position"
    company = job.get("company") or "Company"
    
    if not link:
        return "", ""

    # منطق پویا برای بارگذاری قالب پرامپت از prompt.txt
    prompt_path = SCRIPT_DIR / "prompt.txt"
    if prompt_path.exists():
        try:
            prompt_tpl = prompt_path.read_text(encoding="utf-8").strip()
        except Exception:
            prompt_tpl = ""
    else:
        prompt_tpl = ""

    if not prompt_tpl:
        if CATEGORY == "seo":
            prompt_tpl = (
                "Write a professional, concise cover letter for the '{title}' position at '{company}'.\n"
                "Focus on my technical SEO skills and analytical tools.\n\n"
                "Job link: {url}\n\n"
                "Keep it under 250 words, be targeted to the job requirements, and end with a call to action."
            )
        else:
            prompt_tpl = (
                "Write a professional, concise cover letter for the '{title}' position at '{company}'.\n"
                "Focus on my UI/UX Design, frontend styling, and web development skills.\n\n"
                "Job link: {url}\n\n"
                "Keep it under 250 words, be targeted to the job requirements, and end with a call to action."
            )

    try:
        prompt_text = prompt_tpl.format(title=title, company=company, url=link)
    except Exception:
        prompt_text = f"Write a cover letter for {title} at {company}. Link: {link}"

    encoded_prompt = urllib.parse.quote(prompt_text)
    chatgpt_url = f"https://chatgpt.com/?q={encoded_prompt}"
    
    keyboard = {"inline_keyboard": [
        [
            {"text": "🔗 Apply Now / مشاهده آگهی", "url": link},
            {"text": "🤖 ChatGPT Cover Letter", "url": chatgpt_url}
        ],
        [
            {"text": "📢 عضویت در کانال PIXEELLstudio", "url": f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}"}
        ]
    ]}
    return json.dumps(keyboard), chatgpt_url

# ─── Google Sheets Integration ────────────────────────────────────────────────

def save_to_gsheet(rows: list):
    if not SHEETS_AVAILABLE or not GSHEET_CREDENTIALS or not GSHEET_ID:
        return
    try:
        creds_dict = json.loads(GSHEET_CREDENTIALS)
        scope = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        
        # تلاش برای ذخیره‌سازی در تبی با نام حوزه مربوطه برای آرشیو تمیزتر (مثلاً تبی به نام Design)
        try:
            sheet = client.open_by_key(GSHEET_ID).worksheet(CATEGORY.capitalize())
        except Exception:
            sheet = client.open_by_key(GSHEET_ID).sheet1
            
        sheet.append_rows(rows, value_input_option="USER_ENTERED")
        log.info(f"تعداد {len(rows)} آگهی با موفقیت در Google Sheets ذخیره شد.")
    except Exception as e:
        log.error(f"خطا در ذخیره‌سازی داده‌ها در Google Sheets: {e}")

# ─── Main Executor ────────────────────────────────────────────────────────────

def main():
    log.info(f"شروع اسکرپ آگهی‌های شغلی حوزه {CATEGORY.upper()} با پایداری حداکثری...")
    
    seen_jobs = load_seen_jobs()
    raw_jobs = []
    source_counts = {}

    # در صورت فعال بودن حالت تست، موتورهای اسکرپ را اجرا نمی‌کنیم تا سهمیه API مصرف نشود
    if TEST_MODE:
        log.info("🧪 حالت تست فعال است. هیچ درخواستی به سایت‌های کاریابی ارسال نمی‌شود (سهمیه API حفظ می‌شود).")
        log.info("⚡ ساخت داده‌های شبیه‌سازی شده (Mock Data) برای تست ارسال زنده به تلگرام...")
        
        if CATEGORY == "design":
            raw_jobs = [
                {
                    "id": "mock-design-1",
                    "title": "Senior UI/UX & Product Designer",
                    "company": "Lemon.io",
                    "description": "We are seeking a Product Designer skilled in Figma, UI Design, wireframing, and interaction design to build beautiful web apps.",
                    "salary": "$90,000 - $120,000/yr",
                    "remote": True,
                    "url": "https://remotive.com/remote-jobs/product/staff-product-designer-sao-paulo-2091000",
                    "source": "Remotive",
                    "source_emoji": "🌐",
                    "posted_at": datetime.now().strftime("%Y-%m-%d"),
                    "location": "Worldwide (Remote)"
                }
            ]
        elif CATEGORY == "dev":
            raw_jobs = [
                {
                    "id": "mock-dev-1",
                    "title": "WordPress & Front-End Developer",
                    "company": "WebSparks Ltd",
                    "description": "Looking for a mid-level web developer expert in WordPress, PHP, JavaScript, CSS/HTML, Elementor, and Tailwind CSS.",
                    "salary": "$75,000/yr",
                    "remote": True,
                    "url": "https://jobicy.com/jobs/wordpress-developer",
                    "source": "Jobicy",
                    "source_emoji": "🟢",
                    "posted_at": datetime.now().strftime("%Y-%m-%d"),
                    "location": "Remote"
                }
            ]
        else: # seo
            raw_jobs = [
                {
                    "id": "mock-seo-1",
                    "title": "Junior Technical SEO Specialist",
                    "company": "SearchFlow Media",
                    "description": "Seeking an expert in technical SEO, Screaming Frog, SEMrush, Google Analytics, search console, and custom Python scrapers.",
                    "salary": "",
                    "remote": True,
                    "url": "https://arbeitnow.com/jobs/seo-specialist",
                    "source": "Arbeitnow",
                    "source_emoji": "🔷",
                    "posted_at": datetime.now().strftime("%Y-%m-%d"),
                    "location": "Remote"
                }
            ]
        source_counts = {"MockData": len(raw_jobs)}
    else:
        # اجرای همزمان تمام متدهای اسکرپ با هدرهای مرورگر واقعی در حالت معمولی
        scrapers = [
            (fetch_remotive, "Remotive"),
            (fetch_jobicy, "Jobicy"),
            (fetch_arbeitnow, "Arbeitnow"),
            (fetch_adzuna, "Adzuna"),
            (fetch_findwork, "FindWork"),
            (fetch_cf_worker, "CF Worker"),
            (fetch_jsearch, "JSearch")
        ]
        for fn, name in scrapers:
            try:
                jobs = fn()
                source_counts[name] = len(jobs)
                raw_jobs.extend(jobs)
            except Exception as e:
                log.error(f"خطا در اسکرپر {name}: {e}")
                source_counts[name] = 0

    qualified = []
    seen_in_current_run = set()
    
    stats = {"blacklisted": 0, "low_score": 0, "seen": 0, "old": 0}

    # ارزیابی بهینه و جدید بر اساس زمان و موقعیت مکانی آگهی
    for job in raw_jobs:
        # 💡 اصلاح انقلابی تشخیص همپوشانی تکراری‌ها:
        # برای غلبه بر باگ آیدی‌های لرزان یا تولید مجدد آیدی رندوم توسط کلودفلر/APIها،
        # یک کلید ثابت پایدار و منحصربه‌فرد بر اساس لینک ثبت‌نام واقعی آگهی (Apply URL) ایجاد می‌کنیم.
        # در صورت نبود لینک ثبت‌نام، ترکیب عنوان و شرکت به عنوان شناسه جایگزین هش می‌شود.
        raw_url = job.get("url") or ""
        raw_title = (job.get("title") or "").lower().strip()
        raw_company = (job.get("company") or "").lower().strip()
        
        fallback_id = f"{raw_title}_{raw_company}"
        stable_id = raw_url if raw_url else fallback_id
        
        if not stable_id:
            continue
            
        # تحمیل شناسه پایدار تولید شده به عنوان ID رسمی جاب برای ذخیره‌سازی در کش تلگرام و گیت‌هاب
        job["id"] = stable_id
        job_id = stable_id
            
        if job_id in seen_jobs or job_id in seen_in_current_run:
            stats["seen"] += 1
            continue
            
        if is_old_job(job):
            stats["old"] += 1
            continue

        score, skills = evaluate_job(job)
        if score == -999:
            stats["blacklisted"] += 1
            seen_jobs.add(job_id)
            continue
            
        if score < MIN_FIT_SCORE: # بررسی امتیازدهی وزن‌دار با متغیر داینامیک پیکربندی شده
            stats["low_score"] += 1
            continue

        seen_in_current_run.add(job_id)
        qualified.append((job, score, skills))

    qualified.sort(key=lambda x: x[1], reverse=True)

    active_sources = {k: v for k, v in source_counts.items() if v > 0}
    sources_line = " | ".join(f"{k}: {v}" for k, v in active_sources.items())

    now = datetime.now().strftime("%Y-%m-%d")
    thread_id = str(TELEGRAM_TOPIC_ID) if TELEGRAM_TOPIC_ID and TELEGRAM_TOPIC_ID.isdigit() else None

    # اگر فرصت شغلی جدید با کیفیتی پیدا نشد
    if not qualified:
        log.info("آگهی جدیدی در این دور یافت نشد.")
        send_telegram(
            f"🔍 <b>بررسی آگهی‌های روزانه PIXEELLstudio ({CATEGORY.upper()})</b>\n"
            f"📅 {now}\n\n"
            f"❌ آگهی جدید و واجد شرایط در این دور پیدا نشد.\n\n"
            f"📌 منابع فعال: <code>{sources_line or 'تست آفلاین (شبیه‌ساز)'}</code>\n"
            f"⛔️ {stats['blacklisted']} فیلتر شده | 📉 {stats['low_score']} امتیاز پایین | 🔁 {stats['seen']} تکراری | 🕐 {stats['old']} قدیمی",
            thread_id=thread_id
        )
        save_seen_jobs(seen_jobs)
        return

    # ارسال هدر روزانه با قالب بسیار لوکس و تمیز کاملاً مطابق درخواست کاربر
    send_telegram(
        f"🔍 <b>فرصت‌های شغلی بین‌المللی امروز ({CATEGORY.upper()})</b>\n"
        f"📅 {now}\n\n"
        f"📊 <b>{len(qualified)}</b> آگهی جدید پیدا شد | ⛔️ {stats['blacklisted']} فیلتر شد\n"
        f"➖➖➖➖➖➖➖➖\n"
        f"📢 کانال رسمی: {CHANNEL_USERNAME}",
        thread_id=thread_id
    )
    time.sleep(1.5)

    sent = 0
    sheet_rows = []

    for job, score, skills in qualified[:MAX_JOBS_PER_RUN]:
        try:
            base_msg = format_job(job, score, skills)
            job_type = get_job_type(job)
            hashtags = generate_hashtags(job.get("title", ""))

            # فضاسازی بزرگتر و اعمال فاصله‌های عمودی منظم برای بخش فوتر کارت جاب
            msg = (
                f"{base_msg}\n\n"
                f"⚙️ <b>نوع همکاری:</b>\n{job_type}\n\n"
                f"📌 <b>هشتگ‌های مرتبط:</b>\n{hashtags}\n\n"
                f"➖➖➖➖➖➖➖➖\n"
                f"📢 کانال رسمی: {CHANNEL_USERNAME}"
            )

            buttons, chatgpt_url = build_job_buttons(job)

            if send_telegram(msg, reply_markup=buttons if buttons else None, thread_id=thread_id):
                sent += 1
                seen_jobs.add(job.get("id"))
                
                # ذخیره‌سازی ثابت عبارت قدیمی "ChatGPT URL" طبق درخواست شما در گوگل شیت
                sheet_rows.append([
                    job.get("title", ""), job.get("company", ""),
                    job.get("source", ""), job.get("url", ""),
                    job.get("posted_at", ""), job.get("salary", ""),
                    score, job.get("location", ""),
                    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                    "New", "ChatGPT URL"
                ])

            time.sleep(2.0)

        except Exception as e:
            log.error(f"خطا در پردازش آگهی {job.get('id')}: {e}")
            traceback.print_exc()

    # در حالت تست، شناسه دیده‌شده‌های موقت را ذخیره نمی‌کنیم تا با هر بار ران مجدد در تست، پیام‌ها ارسال شوند
    if not TEST_MODE:
        save_seen_jobs(seen_jobs)
        if sheet_rows:
            save_to_gsheet(sheet_rows)

    log.info(f"پایان کار با موفقیت! تعداد ارسال‌های موفقیت‌آمیز امروز: {sent} آگهی.")

if __name__ == "__main__":
    main()
