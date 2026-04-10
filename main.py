import os
import time
import re
import shutil
import pyperclip
import queue
import threading
from pywinauto.application import Application
import audio_post_processor
import auto_video_pipeline
import traceback
import json
import pandas as pd
INPUT_DIR = r"\\Synology-new\data share\Dat\TheNews_Raw\DowloadsTelegram"
OUTPUT_DIR = r"\\Synology-new\data share\Dat\TheNews_Raw\Output"

APP_TITLE = "Dgt Auto TTS Subtitles Clone Voice 5.11"

LANG_MAP_FILE = "lang_map.json"

file_queue = queue.Queue()
pending_files = set()

def load_lang_map():
    with open(LANG_MAP_FILE, "r", encoding="utf-8") as f:
        return json.load(f)
        
def cleanup_junk_files(base_name, current_project_dir):
    """Chỉ xóa các file tạm/rác của NGÔN NGỮ ĐANG CHẠY (.txt, .dgt)"""
    junk_extensions = [".txt", ".dgt", "-log.dgt"]
    files_to_remove = [os.path.join(current_project_dir, f"{base_name}{ext}") for ext in junk_extensions]


    for file_path in files_to_remove:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                print(f"🧹 Đã dọn dẹp: {os.path.basename(file_path)}")
            except Exception as e:
                pass # Bỏ qua nếu bị khóa
def move_with_retry(src, dst, is_dir=False, retries=5, delay=2):
    """Cơ chế cực lỳ: Cố gắng di chuyển file/thư mục, nếu bị khóa thì chờ rồi thử lại"""
    for i in range(retries):
        try:
            if not os.path.exists(src): return True # Không có thì thôi
            shutil.move(src, dst)
            return True
        except PermissionError:
            print(f"⏳ Hệ thống đang khóa file, chờ {delay}s để thử dời lại ({i+1}/{retries})...")
            time.sleep(delay)
        except Exception as e:
            print(f"❌ Lỗi dời tài nguyên: {e}")
            break
    return False

def move_resources_to_output(base_name, current_project_dir, output_dir):
    """Di chuyển file .srt và thư mục kết quả vào Output. Giữ file gốc đến phút chót."""
    try:
        time.sleep(3) 

        # base_name là tên file ngôn ngữ (VD: 2026-03-11-11-40-06_ko)
        # project_name là tên dự án gốc (VD: 2026-03-11-11-40-06)
        project_name = base_name.split('_')[0] 
        project_out_dir = os.path.join(output_dir, project_name)

        if not os.path.exists(project_out_dir):
            os.makedirs(project_out_dir)

        # 1. CHỈ dời file .srt dịch và folder MP3 của ngôn ngữ đang chạy
        srt_file = os.path.join(current_project_dir, f"{base_name}.srt")
        if move_with_retry(srt_file, os.path.join(project_out_dir, f"{base_name}.srt")):
            print(f"🚚 Đã dời file SRT dịch: {base_name}.srt")

        result_folder = os.path.join(current_project_dir, base_name)
        if move_with_retry(result_folder, os.path.join(project_out_dir, base_name), is_dir=True):
            print(f"📂 Đã dời thư mục Audio: {base_name}")
        
        # 2. Dọn rác (.txt, .dgt) của riêng ngôn ngữ này
        cleanup_junk_files(base_name, current_project_dir)
        
        # Đếm xem trong thư mục Input còn file .srt nào KHÔNG PHẢI file gốc không?
        remaining_files = os.listdir(current_project_dir)
        remaining_subtitles = [f for f in remaining_files 
                               if f.endswith(".srt") and f != f"{project_name}.srt"]
        
        if len(remaining_subtitles) == 0:
            print(f"\n🎉 Dự án {project_name} đã đọc xong TẤT CẢ ngôn ngữ! Tiến hành chốt hạ...")
            
            # 1. DỜI CÁC FILE GỐC (MP4, SRT, XLSX)
            orig_mp4 = os.path.join(current_project_dir, f"{project_name}.mp4")
            orig_srt = os.path.join(current_project_dir, f"{project_name}.srt")
            orig_xlsx = os.path.join(current_project_dir, f"{project_name}.xlsx")
            
            if os.path.exists(orig_mp4): move_with_retry(orig_mp4, os.path.join(project_out_dir, f"{project_name}.mp4"))
            if os.path.exists(orig_srt): move_with_retry(orig_srt, os.path.join(project_out_dir, f"{project_name}.srt"))
            if os.path.exists(orig_xlsx): move_with_retry(orig_xlsx, os.path.join(project_out_dir, f"{project_name}.xlsx"))
            
            # 2. QUÉT VÀ DỜI TOÀN BỘ FILE ẢNH PNG
            for file_in_dir in os.listdir(current_project_dir):
                if file_in_dir.lower().endswith(".png"):
                    src_png = os.path.join(current_project_dir, file_in_dir)
                    dst_png = os.path.join(project_out_dir, file_in_dir)
                    move_with_retry(src_png, dst_png)
            
            # 3. XÓA CÁC FILE CỜ BÁO HIỆU (Để rmdir không bị lỗi thư mục không trống)
            trigger_trans = os.path.join(current_project_dir, "done_translation.txt")
            trigger_meta = os.path.join(current_project_dir, "done_metadata.txt")
            if os.path.exists(trigger_trans): os.remove(trigger_trans)
            if os.path.exists(trigger_meta): os.remove(trigger_meta)
            
            # 4. Xóa thư mục Input (lúc này chắc chắn đã trống rỗng)
            for _ in range(3):
                try:
                    shutil.rmtree(current_project_dir)
                    print(f"🗑️ Đã xóa sạch sẽ thư mục Input: {project_name}")
                    break
                except:
                    time.sleep(1)
            
            # Cắm cờ 100% bên Output để báo cho luồng Hậu kỳ Video bắt đầu làm việc
            marker_file_path = os.path.join(project_out_dir, "_HOAN_THANH_100.txt")
            with open(marker_file_path, "w", encoding="utf-8") as f:
                f.write("OK")
            print(f"🌟 ĐÃ CẮM CỜ HOÀN THÀNH 100% CHO: {project_name}\n")
            
        else:
            print(f"⏳ Thư mục {project_name} vẫn còn {len(remaining_subtitles)} ngôn ngữ chờ đọc. Giữ lại file gốc và cờ!")

        print(f"✅ HOÀN TẤT XỬ LÝ CHO: {base_name}\n" + "-"*40)
    except Exception as e:
        print(f"❌ Lỗi quy trình di dời: {e}")

def convert_srt_to_txt(srt_filepath, txt_filepath):
    try:
        with open(srt_filepath, 'r', encoding='utf-8') as file:
            content = file.read()

        blocks = re.split(r'\n\s*\n', content.strip())
        clean_texts = []
        for block in blocks:
            lines = block.split('\n')
            text_start_idx = -1
            for i, line in enumerate(lines):
                if '-->' in line:
                    text_start_idx = i + 1
                    break
            
            if text_start_idx != -1 and text_start_idx < len(lines):
                text_content = '\n'.join(lines[text_start_idx:]).strip()
                if text_content:
                    clean_texts.append(text_content)
        
        with open(txt_filepath, 'w', encoding='utf-8') as file:
            file.write('\n\n'.join(clean_texts))
            
        print(f"✅ Đã chuyển đổi SRT -> TXT: {os.path.basename(txt_filepath)}")
    except Exception as e:
        print(f"❌ Lỗi chuyển đổi SRT: {e}")


def process_tts_tool(file_path):
    filename = os.path.basename(file_path)
    base_name = os.path.splitext(filename)[0] 
    current_project_dir = os.path.dirname(file_path)
    srt_path = os.path.join(current_project_dir, f"{base_name}.srt") 
    
    try:
        parts = base_name.split('_')
        lang_code = parts[-1].lower() if len(parts) > 1 else "vi"

        CURRENT_LANG_MAP = load_lang_map()
        target_voice = CURRENT_LANG_MAP.get(lang_code, "vi") 
        
        print(f"\n==> Xử lý TTS: {filename} | Ngôn ngữ: {lang_code}")
        
        app = Application(backend="win32").connect(title=APP_TITLE)
        main_window = app.window(title=APP_TITLE)
        main_window.set_focus()

        # Import File
        main_window.child_window(auto_id="btnImportSubtitles").click_input()
        time.sleep(2)
        file_dialog = app.window(class_name="#32770")
        file_dialog.set_focus()
        edit_box = file_dialog.child_window(class_name="Edit")
        edit_box.click_input()
        edit_box.type_keys("^a{BACKSPACE}")
        time.sleep(0.5)
        edit_box.set_edit_text(os.path.abspath(file_path))
        time.sleep(1) 
        file_dialog.type_keys("{ENTER}")

        # Chọn Voice Clone
        if lang_code in CURRENT_LANG_MAP:
            time.sleep(1)
            main_window.child_window(auto_id="btnVoiceClone").click_input()
            time.sleep(2) 
            popup = app.window(title="Voice Clone")
            popup.set_focus()
            
            # CHỈ TAB 1 LẦN ĐỂ ĐẾN CỘT VOICE NAME (Như bạn yêu cầu)
            popup.type_keys("{TAB}")
            time.sleep(0.5)

            found = False
            for i in range(50):
                pyperclip.copy("") 
                popup.type_keys("^c") 
                time.sleep(0.3)
                current_val = pyperclip.paste().strip() # VD: "duong_dt69mOZv"
                
                current_name = current_val.split('_')[0].lower() if '_' in current_val else current_val.lower()
                
                if target_voice.lower() == current_name:
                    found = True
                    break
                    
                popup.type_keys("{DOWN}")
                time.sleep(0.2)

            if found:
                popup.type_keys("{TAB 5}{SPACE}")
                time.sleep(1)
            else:
                popup.type_keys("{ESC}")

        # Bấm Start và đợi
        time.sleep(1.5)
        btn_start = main_window.child_window(auto_id="btnStart")
        btn_start.set_focus()
        btn_start.type_keys("{SPACE}")
        print(f"⏳ Tool đang xử lý TTS cho voice: {target_voice}... Vui lòng đợi.")

        time.sleep(5) 
        btn_start.wait('enabled', timeout=1200) 
        print(f"✨ Tool đã chạy xong file: {filename}")

        print(f"📦 Đang đóng gói tài nguyên vào Output...")
        move_resources_to_output(base_name, current_project_dir, OUTPUT_DIR)

    except Exception as e:
        print(f"❌ Lỗi quy trình (File sẽ được quét lại): {e}")
        
    finally:
        if srt_path in pending_files:
            pending_files.remove(srt_path)

def worker():
    print("🤖 Worker Online - Sẵn sàng bốc việc từ hàng đợi.")
    while True:
        file_path = file_queue.get()
        if file_path is None: break
        process_tts_tool(file_path)
        file_queue.task_done()

def continuous_scanner():
    print(f"🔍 Hệ thống quét liên tục đã kích hoạt trên: {INPUT_DIR}")
    while True:
        try:
            if not os.path.exists(INPUT_DIR):
                time.sleep(2)
                continue
                
            project_folders = [f for f in os.listdir(INPUT_DIR) if os.path.isdir(os.path.join(INPUT_DIR, f))]
            
            for folder_name in project_folders:
                folder_path = os.path.join(INPUT_DIR, folder_name)

                # --- LOGIC MỚI: KIỂM TRA ĐỦ 2 FILE TRIGGER ---
                trigger_trans = os.path.join(folder_path, "done_translation.txt")
                trigger_meta = os.path.join(folder_path, "done_metadata.txt")
                
                # Nếu thiếu 1 trong 2 file, sẽ bỏ qua và chờ vòng quét sau
                if not (os.path.exists(trigger_trans) and os.path.exists(trigger_meta)):
                    continue
                
                srt_files = [f for f in os.listdir(folder_path) if f.lower().endswith(".srt")]
                
                for filename in srt_files:
                    srt_path = os.path.join(folder_path, filename)
                    txt_path = os.path.splitext(srt_path)[0] + ".txt"
                    
                    if srt_path not in pending_files:
                        print(f"✨ Phát hiện mục tiêu mới: {filename} (Dự án: {folder_name})")
                        pending_files.add(srt_path)
                        convert_srt_to_txt(srt_path, txt_path)
                        file_queue.put(txt_path)
                        print(f"📥 Đã nạp {filename} vào dây chuyền.")
        except Exception as e:
            print(f"⚠️ Lỗi khi quét thư mục Input: {e}")
        
        time.sleep(2)

def update_excel(project_out_dir, folder_name):
    """Đọc file Excel cũ, đắp thêm cột và đường dẫn tuyệt đối chuẩn xác theo từng dòng"""
    excel_path = os.path.join(project_out_dir, f"{folder_name}.xlsx")
    
    if not os.path.exists(excel_path):
        print(f"   ⚠️ Không tìm thấy file {folder_name}.xlsx để cập nhật.")
        return False

    try:
        print("   📊 Đang cấu hình file Excel chuẩn form DHB...")
        df = pd.read_excel(excel_path)
        
        # Bắt buộc file Excel phải có cột "Ngôn ngữ" từ trước
        if "Ngôn ngữ" not in df.columns:
            print("   ❌ Lỗi: File Excel đầu vào không có cột 'Ngôn ngữ' để đối chiếu!")
            return False

        paths_video = []
        paths_thumb = []
        tai_khoan = []
        
        # Quét TỪNG DÒNG trong Excel để lấy đúng file Video khớp với dòng đó
        for index, row in df.iterrows():
            lang = str(row["Ngôn ngữ"]).strip() # Lấy ngôn ngữ của dòng hiện tại (vd: 'vi')
            
            # Tự động suy ra tên file Video và Thumbnail dựa trên ngôn ngữ đó
            video_name = f"{folder_name}_{lang}_DUBBED.mp4"
            thumb_name = f"{folder_name}_{lang}.png"
            
            video_full_path = os.path.abspath(os.path.join(project_out_dir, video_name))
            thumb_full_path = os.path.abspath(os.path.join(project_out_dir, thumb_name))
            
            # Kiểm tra xem video đó có thực sự tồn tại trên ổ cứng không
            if not os.path.exists(video_full_path):
                print(f"   ⚠️ Cảnh báo: Không tìm thấy video {video_name} trên ổ cứng!")
            
            # Nạp vào mảng (Đảm bảo thứ tự mảng này khớp 100% với thứ tự dòng trong Excel)
            paths_video.append(video_full_path)
            paths_thumb.append(thumb_full_path)
            tai_khoan.append(lang)
            
        # Đắp dữ liệu mới vào Excel
        df["Ảnh thu nhỏ"] = paths_thumb
        df["Trẻ em"] = "Không"
        df["Riêng tư"] = "Công khai"
        df["Đặt lịch"] = "None"
        df["Tài khoản"] = tai_khoan  # Tài khoản khớp tuyệt đối với ngôn ngữ của dòng
        df["Video"] = paths_video
        # TUYỆT ĐỐI KHÔNG ghi đè cột "Ngôn ngữ" nữa vì nó đã chuẩn rồi
        
        # Lưu đè lại file
        df.to_excel(excel_path, index=False)
        print(f"   ✅ Đã chốt form Excel thành công, khớp 100% dữ liệu, sẵn sàng lên mâm!")
        return True
            
    except Exception as e:
        print(f"   ❌ Lỗi khi cập nhật Excel DHB: {e}")
        return False

def output_scanner():
    print(f"👁️ Hệ thống giám sát Output đã kích hoạt trên: {OUTPUT_DIR}")
    while True:
        try:
            if os.path.exists(OUTPUT_DIR):
                project_folders = [f for f in os.listdir(OUTPUT_DIR) if os.path.isdir(os.path.join(OUTPUT_DIR, f))]
                
                for folder_name in project_folders:
                    project_out_dir = os.path.join(OUTPUT_DIR, folder_name)
                    marker_100_percent = os.path.join(project_out_dir, "_HOAN_THANH_100.txt")
                    marker_done_post = os.path.join(project_out_dir, "_DA_XU_LY_OUTPUT_XONG.txt")
                    
                    # ĐIỀU KIỆN TIÊN QUYẾT: Đã đủ nguyên liệu (Cờ 100) VÀ chưa làm Hậu kỳ
                    if os.path.exists(marker_100_percent) and not os.path.exists(marker_done_post):
                        
                        print(f"\n🎯 PHÁT HIỆN DỰ ÁN SẴN SÀNG HẬU KỲ: {folder_name}")
                        success = audio_post_processor.run_post_processing_for_project(project_out_dir)

                        if success:
                            # 1. NẤU ĂN (GHÉP VIDEO)
                            print("🎬 Bắt đầu quá trình ghép Audio vào Video...")
                            video_success = auto_video_pipeline.run_video_sync_pipeline(project_out_dir, folder_name)
                            
                            # NẾU THẤT BẠI: Dừng lại, không dọn rác, không cắm cờ!
                            if not video_success:
                                print(f"🛑 Hậu kỳ Video gặp lỗi cho dự án {folder_name}. Dừng việc dọn dẹp và cắm cờ!")
                                continue 
                            
                            # 2. RỬA BÁT VÀ QUÉT NHÀ (Chỉ chạy khi có Video)
                            print("🧹 Đang tiến hành dọn dẹp nguyên liệu thô...")
                            
                            for item in os.listdir(project_out_dir):
                                item_path = os.path.join(project_out_dir, item)
                                
                                if os.path.isfile(item_path):
                                    if item.lower().endswith((".txt", ".png", ".xlsx")) or item == f"{folder_name}.srt" or item.endswith("_DUBBED.mp4"):
                                        continue
                                    else:
                                        try:
                                            os.remove(item_path)
                                            print(f"   🗑️ Đã xóa file: {item}")
                                        except Exception: pass
                            
                                elif os.path.isdir(item_path):
                                    try:
                                        shutil.rmtree(item_path) 
                                        print(f"   🗑️ Đã xóa thư mục: {item}")
                                    except Exception: pass
                            
                            # 3. CẬP NHẬT EXCEL
                            excel_success = update_excel(project_out_dir, folder_name)
                            if not excel_success:
                                print(f"🛑 Cập nhật Excel thất bại cho {folder_name}. Bỏ qua việc cắm cờ!")
                                continue 
                                    
                            # 4. ĐÓNG DẤU HOÀN THÀNH 
                            with open(marker_done_post, "w", encoding="utf-8") as f:
                                f.write("Trạng thái Hậu kỳ: ok")
                                
                            print(f"🏁 ĐÃ ĐÓNG DẤU HẬU KỲ XONG CHO: {folder_name}")

                        else:
                            print(f"⚠️ Quá trình tạo Audio thất bại cho {folder_name}. Chờ vòng sau xử lý lại.")
                        
        except Exception as e:
            print(f"⚠️ Lỗi khi quét Output: {e}")
            traceback.print_exc()
        time.sleep(2)
if __name__ == "__main__":
    if not os.path.exists(OUTPUT_DIR): 
        os.makedirs(OUTPUT_DIR)
    
    t_worker = threading.Thread(target=worker, daemon=True)
    t_worker.start()

    t_scanner = threading.Thread(target=continuous_scanner, daemon=True)
    t_scanner.start()

    t_output_scanner = threading.Thread(target=output_scanner, daemon=True)
    t_output_scanner.start()

    print("🚀 Hệ thống Tự động hóa 3 Luồng đang chạy...")
    print("   1. Đang trực chờ Tool TTS")
    print("   2. Đang quét Input")
    print("   3. Đang giám sát Output chờ ghép Audio")
    print("-" * 40)
    
    try:
        while True: 
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping...")