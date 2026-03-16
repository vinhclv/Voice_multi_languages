import os
import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    # Khi chạy file .exe, ta muốn BASE_DIR là thư mục chứa file .exe đó
    BASE_DIR = Path(sys.executable).parent
else:
    # Nếu config.py nằm trong folder Code/, parent.parent sẽ lùi ra ngoài thư mục gốc (nơi chứa main.py)
    BASE_DIR = Path(__file__).resolve().parent.parent

# Chỉ định ĐÍCH DANH thư mục ffmpeg_bin nằm cùng cấp với main.py
FFMPEG_BIN = BASE_DIR / "ffmpeg_bin"

# Cấu hình đường dẫn và kiểm tra an toàn
if (FFMPEG_BIN / "ffmpeg.exe").exists():
    ffmpeg_exe = str(FFMPEG_BIN / "ffmpeg.exe")
    ffprobe_exe = str(FFMPEG_BIN / "ffprobe.exe")
    
    # Cập nhật PATH hệ thống để subprocess (và Pydub nếu có) gọi được lệnh trực tiếp
    os.environ["PATH"] = str(FFMPEG_BIN) + os.pathsep + os.environ["PATH"]
else:
    # Trường hợp xấu nhất: Không tìm thấy gì cả -> Để chuỗi rỗng để check_tools() bắt lỗi sau
    print("⚠️ CẢNH BÁO: Không tìm thấy thư mục ffmpeg_bin hoặc file ffmpeg.exe!")
    ffmpeg_exe = ""
    ffprobe_exe = ""

PATHS = {
    "ffmpeg": ffmpeg_exe,
    "ffprobe": ffprobe_exe,
    "temp_dir": BASE_DIR / "temp_sync",
    "output_default": "Video_Final_Theo_SRT.mp4"
}

def check_tools():
    """Kiểm tra xem file exe có tồn tại thực sự không"""
    valid_ffmpeg = os.path.isfile(PATHS["ffmpeg"])
    valid_ffprobe = os.path.isfile(PATHS["ffprobe"])
    return valid_ffmpeg and valid_ffprobe