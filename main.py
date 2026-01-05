"""
English Learning Automation from Podcast RSS Feed
Sử dụng Google Gemini API để xử lý âm thanh, tạo tài liệu và gửi Email
"""
import smtplib
import os
import time
import feedparser
import requests
import google.generativeai as genai
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from docx import Document
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from dotenv import load_dotenv
from bs4 import BeautifulSoup

# --- CẤU HÌNH ---
RSS_FEED_URL = "http://feeds.bbci.co.uk/learningenglish/english/features/6-minute-english/rss"
TEMP_AUDIO_FILE = "temp_podcast.mp3"
MODEL_NAME = "gemini-flash-latest" # Khuyên dùng bản 1.5 Flash vì xử lý audio tốt và rẻ/free

class PodcastLearningAutomation:
    def __init__(self):
        """Khởi tạo hệ thống tự động hóa"""
        self.rss_url = RSS_FEED_URL
        self.setup_env()
        self.setup_gemini()
        
    def setup_env(self):
        """Tải biến môi trường"""
        load_dotenv()
        self.email_sender = os.getenv("EMAIL_SENDER")
        self.email_password = os.getenv("EMAIL_PASSWORD")
        self.email_receiver = os.getenv("EMAIL_RECEIVER") # Thêm người nhận vào .env
        self.api_key = os.getenv('GOOGLE_API_KEY')

        if not all([self.email_sender, self.email_password, self.email_receiver, self.api_key]):
            raise ValueError("⚠️ Thiếu biến môi trường trong file .env hoặc Secrets")

    def setup_gemini(self):
        """Cấu hình Gemini"""
        try:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(MODEL_NAME)
            print("✓ Đã cấu hình Gemini API thành công")
        except Exception as e:
            raise Exception(f"Lỗi cấu hình Gemini API: {str(e)}")

    def get_audio_from_webpage(self, page_url):
        """Tìm link mp3 trực tiếp từ trang web (Web Scraping)"""
        try:
            print(f"  🔍 Đang quét trang web: {page_url}")
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(page_url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                if href.strip().lower().endswith('.mp3'):
                    if href.startswith('/'):
                        return "https://www.bbc.co.uk" + href
                    return href
            return None
        except Exception as e:
            print(f"  ⚠️ Lỗi khi quét web: {e}")
            return None
    
    def fetch_latest_episode(self):
        """Lấy thông tin tập mới nhất"""
        try:
            print(f"\n📡 Đang tải RSS feed...")
            feed = feedparser.parse(self.rss_url)
            if not feed.entries:
                raise Exception("RSS Feed trống")
            
            latest = feed.entries[0]
            title = latest.title
            pub_date = latest.get('published', 'Unknown date')
            audio_url = None

            # 1. Tìm trong enclosures
            if hasattr(latest, 'enclosures'):
                for enc in latest.enclosures:
                    if enc.get('href', '').endswith('.mp3'):
                        audio_url = enc.get('href')
                        break
            
            # 2. Nếu không thấy, quét web
            if not audio_url:
                print("  ⚠️ Không thấy MP3 trong RSS, thử quét trang web...")
                audio_url = self.get_audio_from_webpage(latest.link)
            
            if not audio_url:
                raise Exception("Không tìm thấy Audio URL")
            
            print(f"✓ Tìm thấy: {title} ({pub_date})")
            return {'title': title, 'pub_date': pub_date, 'audio_url': audio_url}
        except Exception as e:
            raise Exception(f"Lỗi lấy Podcast: {str(e)}")

    def download_audio(self, audio_url):
        """Tải file MP3"""
        try:
            print(f"⬇️  Đang tải audio...")
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(audio_url, headers=headers, stream=True, timeout=60)
            with open(TEMP_AUDIO_FILE, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"✓ Tải xong ({os.path.getsize(TEMP_AUDIO_FILE)/1024/1024:.2f} MB)")
            return TEMP_AUDIO_FILE
        except Exception as e:
            raise Exception(f"Lỗi tải file: {str(e)}")

    def process_with_gemini(self, file_path):
        """Upload và xử lý với Gemini"""
        print(f"☁️  Upload lên Gemini & Phân tích...")
        audio_file = genai.upload_file(file_path)
        
        # Chờ xử lý
        while audio_file.state.name == "PROCESSING":
            time.sleep(2)
            audio_file = genai.get_file(audio_file.name)
        
        if audio_file.state.name == "FAILED":
            raise Exception("Gemini xử lý file thất bại")

        # Prompt gộp (Transcript + Analysis) để tiết kiệm request
        prompt = """
        Analyze this English podcast audio.
        
        TASK 1: FULL TRANSCRIPT
        Provide a complete, verbatim transcript.
        
        TASK 2: VIETNAMESE LEARNING ANALYSIS
        Extract 5 Advanced Vocabulary words (B2-C1) and 2 Grammar Structures.
        For each, provide: Definition (Vietnamese), Example Sentence, and Example Translation.
        
        OUTPUT FORMAT:
        Start with "### ANALYSIS" for Task 2.
        Then "### TRANSCRIPT" for Task 1.
        """
        
        response = self.model.generate_content([audio_file, prompt])
        
        # Xóa file trên cloud sau khi xong
        audio_file.delete()
        
        return response.text

    def create_word_doc(self, info, content):
        """Tạo file Word"""
        print(f"📄 Đang tạo file Word...")
        doc = Document()
        doc.add_heading(info['title'], 0)
        doc.add_paragraph(f"Date: {info['pub_date']}")
        
        doc.add_heading("Nội Dung Bài Học", level=1)
        doc.add_paragraph(content) # Có thể xử lý string để chia tách đẹp hơn nếu muốn
        
        clean_title = "".join([c for c in info['title'] if c.isalnum() or c==' ']).strip().replace(' ', '_')
        filename = f"English_Lesson_{clean_title}.docx"
        doc.save(filename)
        print(f"✓ Đã lưu: {filename}")
        return filename

    def send_email(self, attachment_path, subject):
        """Gửi email đính kèm"""
        print(f"📧 Đang gửi email tới {self.email_receiver}...")
        msg = MIMEMultipart()
        msg['From'] = self.email_sender
        msg['To'] = self.email_receiver
        msg['Subject'] = subject
        
        body = "Chào bạn,\n\nĐây là bài học tiếng Anh tự động của ngày hôm nay.\nChúc bạn học tốt!"
        msg.attach(MIMEText(body, 'plain'))

        with open(attachment_path, "rb") as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f"attachment; filename= {os.path.basename(attachment_path)}")
            msg.attach(part)

        try:
            server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
            server.login(self.email_sender, self.email_password)
            server.send_message(msg)
            server.quit()
            print("✅ Email đã gửi thành công!")
        except Exception as e:
            print(f"❌ Lỗi gửi mail: {e}")

    def cleanup(self):
        if os.path.exists(TEMP_AUDIO_FILE):
            os.remove(TEMP_AUDIO_FILE)

    def run(self):
        try:
            print("--- BẮT ĐẦU ---")
            # 1. Lấy thông tin
            info = self.fetch_latest_episode()
            
            # 2. Tải & Xử lý AI
            local_file = self.download_audio(info['audio_url'])
            ai_content = self.process_with_gemini(local_file)
            
            # 3. Tạo Word
            doc_file = self.create_word_doc(info, ai_content)
            
            # 4. Gửi Mail
            self.send_email(doc_file, f"[Podcast Daily] {info['title']}")
            
            # 5. Dọn dẹp
            self.cleanup()
            print("--- HOÀN TẤT ---")
            
        except Exception as e:
            print(f"❌ LỖI NGHIÊM TRỌNG: {e}")
            self.cleanup()

if __name__ == "__main__":
    PodcastLearningAutomation().run()