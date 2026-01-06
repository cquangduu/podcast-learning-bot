"""
English Learning Automation - NEW GENAI VERSION (Fix 503 Error)
"""
import smtplib
import os
import time
import feedparser
import requests
from google import genai # Thư viện mới
from google.genai import types
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from docx import Document
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# --- CẤU HÌNH ---
RSS_FEED_URL = "http://feeds.bbci.co.uk/learningenglish/english/features/6-minute-english/rss"
TEMP_AUDIO_FILE = "temp_podcast.mp3"
MODEL_NAME = "gemini-flash-latest"

class PodcastLearningAutomation:
    def __init__(self):
        print("--- KHỞI TẠO HỆ THỐNG ---")
        load_dotenv()
        
        # 1. Lấy biến môi trường
        self.email_sender = os.getenv("EMAIL_SENDER")
        self.email_password = os.getenv("EMAIL_PASSWORD")
        self.email_receiver = os.getenv("EMAIL_RECEIVER")
        self.api_key = os.getenv('GOOGLE_API_KEY')

        # 2. Kiểm tra
        print(f"API Key: {'✅ OK' if self.api_key else '❌ MISSING'}")
        print(f"Email User: {'✅ OK' if self.email_sender else '❌ MISSING'}")
        
        if not all([self.email_sender, self.email_password, self.email_receiver, self.api_key]):
             raise ValueError("⛔ LỖI: Thiếu biến môi trường! Kiểm tra lại Secrets/YAML.")

        # 3. Cấu hình Client Gemini Mới
        try:
            self.client = genai.Client(api_key=self.api_key)
            print("✅ Đã kết nối Client Google GenAI mới")
        except Exception as e:
            print(f"❌ Lỗi khởi tạo Client: {e}")
            raise e

        self.rss_url = RSS_FEED_URL

    def get_audio_from_webpage(self, page_url):
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(page_url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                if href.strip().lower().endswith('.mp3'):
                    if href.startswith('/'): return "https://www.bbc.co.uk" + href
                    return href
            return None
        except: return None

    def fetch_latest_episode(self):
        print(f"\n📡 Đang tải RSS feed...")
        feed = feedparser.parse(self.rss_url)
        if not feed.entries: raise Exception("RSS Trống")
        latest = feed.entries[0]
        title = latest.title
        pub_date = latest.get('published', 'Unknown')
        
        audio_url = None
        if hasattr(latest, 'enclosures'):
            for enc in latest.enclosures:
                if enc.get('href', '').endswith('.mp3'): audio_url = enc.get('href'); break
        
        if not audio_url:
            audio_url = self.get_audio_from_webpage(latest.link)

        if not audio_url: raise Exception("Không tìm thấy Audio URL")
        print(f"✓ Tìm thấy: {title}")
        return {'title': title, 'pub_date': pub_date, 'audio_url': audio_url}

    def download_audio(self, audio_url):
        print(f"⬇️ Đang tải MP3...")
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(audio_url, headers=headers)
        with open(TEMP_AUDIO_FILE, 'wb') as f: f.write(r.content)
        return TEMP_AUDIO_FILE

    def process_with_gemini(self, file_path):
        print(f"☁️ Upload và Xử lý với Gemini (New SDK)...")
        
        # 1. Upload file (Cú pháp mới)
        try:
            # Upload file trực tiếp
            file_ref = self.client.files.upload(file=file_path, config={'mime_type': 'audio/mp3'})
            print(f"   -> Upload xong: {file_ref.name}")
            
            # Chờ file xử lý xong (Polling state)
            while True:
                file_info = self.client.files.get(name=file_ref.name)
                if file_info.state == "ACTIVE":
                    break
                if file_info.state == "FAILED":
                    raise Exception("File upload failed processing")
                print("   ...đang xử lý file...")
                time.sleep(2)

            # 2. Tạo nội dung
            prompt = """
            Analyze this English podcast audio.
            OUTPUT FORMAT (Plain text only):
            1. VOCABULARY (5 Advanced words): Word - Definition (Vietnamese) - Example.
            2. TRANSCRIPT: Full verbatim transcript.
            """
            
            response = self.model_response = self.client.models.generate_content(
                model=MODEL_NAME,
                contents=[file_ref, prompt]
            )
            
            # 3. Dọn dẹp file trên Cloud (Quan trọng)
            self.client.files.delete(name=file_ref.name)
            
            return response.text

        except Exception as e:
            raise Exception(f"Lỗi Gemini SDK: {e}")

    def create_word_doc(self, info, content):
        print(f"📄 Tạo file Word...")
        doc = Document()
        doc.add_heading(info['title'], 0)
        doc.add_paragraph(f"Date: {info['pub_date']}")
        doc.add_paragraph(content)
        filename = f"Lesson_{int(time.time())}.docx"
        doc.save(filename)
        return filename

    def send_email(self, attachment_path, subject):
        print(f"\n📧 Đang gửi email...")
        msg = MIMEMultipart()
        msg['From'] = self.email_sender
        msg['To'] = self.email_receiver
        msg['Subject'] = f"[English Daily] {subject}"
        msg.attach(MIMEText("Tài liệu học tiếng Anh của bạn đính kèm bên dưới.", 'plain'))

        with open(attachment_path, "rb") as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f"attachment; filename= {os.path.basename(attachment_path)}")
            msg.attach(part)

        try:
            # Sử dụng cổng 587 (TLS) chuẩn
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(self.email_sender, self.email_password)
            server.send_message(msg)
            server.quit()
            print("✅ EMAIL GỬI THÀNH CÔNG!")
        except Exception as e:
            print(f"❌ LỖI GỬI MAIL: {e}")
            raise e

    def cleanup(self):
        if os.path.exists(TEMP_AUDIO_FILE): os.remove(TEMP_AUDIO_FILE)

    def run(self):
        try:
            ep = self.fetch_latest_episode()
            local = self.download_audio(ep['audio_url'])
            ai_content = self.process_with_gemini(local)
            doc = self.create_word_doc(ep, ai_content)
            self.send_email(doc, ep['title'])
            self.cleanup()
            print("--- DONE ---")
        except Exception as e:
            print(f"🔥 LỖI CHƯƠNG TRÌNH: {e}")
            self.cleanup()
            exit(1)

if __name__ == "__main__":
    PodcastLearningAutomation().run()
