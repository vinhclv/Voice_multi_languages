import os
import time
import re
import shutil
import pyperclip
import queue
import threading
import traceback
import json
import pandas as pd
import sys

# Import thư viện giao diện mới
import customtkinter as ctk
from tkinter import filedialog, messagebox

# Import các module bên ngoài của bạn
import audio_post_processor
import auto_video_pipeline

# ==========================================
# BIẾN TOÀN CỤC & TRẠNG THÁI HỆ THỐNG
# ==========================================
INPUT_DIR = r"\\Synology-new\data share\Dat\TheNews_Raw\DowloadsTelegram"
OUTPUT_DIR = r"\\Synology-new\data share\Dat\TheNews_Raw\Output"
APP_TITLE = r"Dgt Auto TTS Subtitles Clone Voice.*"
LANG_MAP_FILE = "lang_map.json"

file_queue = queue.Queue()
pending_files = set()
IS_RUNNING = False
GENERATE_SUB = True  

# Đảm bảo file lang_map tồn tại
if not os.path.exists(LANG_MAP_FILE):
    with open(LANG_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump({"vi": "default_voice"}, f)

# ==========================================
# CORE LOGIC (GIỮ NGUYÊN 100%)
# ==========================================
def load_lang_map():
    with open(LANG_MAP_FILE, "r", encoding="utf-8") as f:
        return json.load(f)
        
def cleanup_junk_files(base_name, current_project_dir):
    junk_extensions = [".txt", ".dgt", "-log.dgt"]
    files_to_remove = [os.path.join(current_project_dir, f"{base_name}{ext}") for ext in junk_extensions]

    for file_path in files_to_remove:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                print(f"🧹 Đã dọn dẹp: {os.path.basename(file_path)}")
            except Exception as e:
                pass

def move_with_retry(src, dst, is_dir=False, retries=5, delay=2):
    for i in range(retries):
        try:
            if not os.path.exists(src): return True 
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
    try:
        time.sleep(3) 
        project_name = base_name.split('_')[0] 
        project_out_dir = os.path.join(output_dir, project_name)

        if not os.path.exists(project_out_dir):
            os.makedirs(project_out_dir)

        srt_file = os.path.join(current_project_dir, f"{base_name}.srt")
        if move_with_retry(srt_file, os.path.join(project_out_dir, f"{base_name}.srt")):
            print(f"🚚 Đã dời file SRT dịch: {base_name}.srt")

        result_folder = os.path.join(current_project_dir, base_name)
        if move_with_retry(result_folder, os.path.join(project_out_dir, base_name), is_dir=True):
            print(f"📂 Đã dời thư mục Audio: {base_name}")
        
        cleanup_junk_files(base_name, current_project_dir)
        
        remaining_files = os.listdir(current_project_dir)
        remaining_subtitles = [f for f in remaining_files if f.endswith(".srt") and f != f"{project_name}.srt"]
        
        if len(remaining_subtitles) == 0:
            print(f"\n🎉 Dự án {project_name} đã đọc xong TẤT CẢ ngôn ngữ! Tiến hành chốt hạ...")
            
            orig_mp4 = os.path.join(current_project_dir, f"{project_name}.mp4")
            orig_srt = os.path.join(current_project_dir, f"{project_name}.srt")
            orig_xlsx = os.path.join(current_project_dir, f"{project_name}.xlsx")
            
            if os.path.exists(orig_mp4): move_with_retry(orig_mp4, os.path.join(project_out_dir, f"{project_name}.mp4"))
            if os.path.exists(orig_srt): move_with_retry(orig_srt, os.path.join(project_out_dir, f"{project_name}.srt"))
            if os.path.exists(orig_xlsx): move_with_retry(orig_xlsx, os.path.join(project_out_dir, f"{project_name}.xlsx"))
            
            for file_in_dir in os.listdir(current_project_dir):
                if file_in_dir.lower().endswith(".png"):
                    src_png = os.path.join(current_project_dir, file_in_dir)
                    dst_png = os.path.join(project_out_dir, file_in_dir)
                    move_with_retry(src_png, dst_png)
            
            trigger_trans = os.path.join(current_project_dir, "done_translation.txt")
            trigger_meta = os.path.join(current_project_dir, "done_metadata.txt")
            if os.path.exists(trigger_trans): os.remove(trigger_trans)
            if os.path.exists(trigger_meta): os.remove(trigger_meta)
            
            for _ in range(3):
                try:
                    shutil.rmtree(current_project_dir)
                    print(f"🗑️ Đã xóa sạch sẽ thư mục Input: {project_name}")
                    break
                except:
                    time.sleep(1)
            
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
    from pywinauto.application import Application
    from pywinauto import Desktop
    
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
        
        app = Application(backend="win32").connect(title_re=APP_TITLE)
        main_window = app.window(title_re=APP_TITLE)
        main_window.set_focus()

        main_window.child_window(auto_id="btnImportSubtitles").click_input()
        time.sleep(2)
        
        file_dialog = Desktop(backend="win32").window(class_name="#32770")
        file_dialog.wait("ready", timeout=5)
        file_dialog.set_focus()
        
        edit_box = file_dialog.child_window(class_name="Edit")
        edit_box.click_input()
        edit_box.type_keys("^a{BACKSPACE}")
        time.sleep(0.5)
        edit_box.set_edit_text(os.path.abspath(file_path))
        time.sleep(1) 
        file_dialog.type_keys("{ENTER}")

        if lang_code in CURRENT_LANG_MAP:
            time.sleep(1)
            main_window.child_window(auto_id="btnVoiceClone").click_input()
            time.sleep(2) 
            popup = app.window(title="Voice Clone")
            popup.set_focus()
            
            popup.type_keys("{TAB}")
            time.sleep(0.5)

            found = False
            for i in range(50):
                pyperclip.copy("") 
                popup.type_keys("^c") 
                time.sleep(0.3)
                current_val = pyperclip.paste().strip()
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
    while IS_RUNNING:
        try:
            file_path = file_queue.get(timeout=2)
            if file_path is None: break
            process_tts_tool(file_path)
            file_queue.task_done()
        except queue.Empty:
            continue

def continuous_scanner():
    print(f"🔍 Hệ thống quét liên tục đã kích hoạt trên: {INPUT_DIR}")
    while IS_RUNNING:
        try:
            if not os.path.exists(INPUT_DIR):
                time.sleep(2)
                continue
                
            project_folders = [f for f in os.listdir(INPUT_DIR) if os.path.isdir(os.path.join(INPUT_DIR, f))]
            
            for folder_name in project_folders:
                folder_path = os.path.join(INPUT_DIR, folder_name)

                trigger_trans = os.path.join(folder_path, "done_translation.txt")
                trigger_meta = os.path.join(folder_path, "done_metadata.txt")
                
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
    excel_path = os.path.join(project_out_dir, f"{folder_name}.xlsx")
    if not os.path.exists(excel_path):
        print(f"   ⚠️ Không tìm thấy file {folder_name}.xlsx để cập nhật.")
        return False
    try:
        print("   📊 Đang cấu hình file Excel chuẩn form DHB...")
        df = pd.read_excel(excel_path)
        if "Ngôn ngữ" not in df.columns:
            print("   ❌ Lỗi: File Excel đầu vào không có cột 'Ngôn ngữ' để đối chiếu!")
            return False

        paths_video, paths_thumb, tai_khoan = [], [], []
        for index, row in df.iterrows():
            lang = str(row["Ngôn ngữ"]).strip() 
            video_name = f"{folder_name}_{lang}_DUBBED.mp4"
            thumb_name = f"{folder_name}_{lang}.png"
            
            video_full_path = os.path.abspath(os.path.join(project_out_dir, video_name))
            thumb_full_path = os.path.abspath(os.path.join(project_out_dir, thumb_name))
            
            if not os.path.exists(video_full_path):
                print(f"   ⚠️ Cảnh báo: Không tìm thấy video {video_name} trên ổ cứng!")
            
            paths_video.append(video_full_path)
            paths_thumb.append(thumb_full_path)
            tai_khoan.append(lang)
            
        df["Ảnh thu nhỏ"] = paths_thumb
        df["Trẻ em"] = "Không"
        df["Riêng tư"] = "Công khai"
        df["Đặt lịch"] = "None"
        df["Tài khoản"] = tai_khoan 
        df["Video"] = paths_video
        
        df.to_excel(excel_path, index=False)
        print(f"   ✅ Đã chốt form Excel thành công, khớp 100% dữ liệu, sẵn sàng lên mâm!")
        return True
    except Exception as e:
        print(f"   ❌ Lỗi khi cập nhật Excel DHB: {e}")
        return False

def output_scanner():
    print(f"👁️ Hệ thống giám sát Output đã kích hoạt trên: {OUTPUT_DIR}")
    while IS_RUNNING:
        try:
            if os.path.exists(OUTPUT_DIR):
                project_folders = [f for f in os.listdir(OUTPUT_DIR) if os.path.isdir(os.path.join(OUTPUT_DIR, f))]
                
                for folder_name in project_folders:
                    project_out_dir = os.path.join(OUTPUT_DIR, folder_name)
                    marker_100_percent = os.path.join(project_out_dir, "_HOAN_THANH_100.txt")
                    marker_done_post = os.path.join(project_out_dir, "_DA_XU_LY_OUTPUT_XONG.txt")
                    
                    if os.path.exists(marker_100_percent) and not os.path.exists(marker_done_post):
                        print(f"\n🎯 PHÁT HIỆN DỰ ÁN SẴN SÀNG HẬU KỲ: {folder_name}")
                        success = audio_post_processor.run_post_processing_for_project(project_out_dir)

                        if success:
                            print("🎬 Bắt đầu quá trình ghép Audio vào Video...")
                            video_success = auto_video_pipeline.run_video_sync_pipeline(project_out_dir, folder_name, generate_sub=GENERATE_SUB)
                            
                            if not video_success:
                                print(f"🛑 Hậu kỳ Video gặp lỗi cho dự án {folder_name}. Dừng việc dọn dẹp và cắm cờ!")
                                continue 
                            
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
                            
                            excel_success = update_excel(project_out_dir, folder_name)
                            if not excel_success:
                                print(f"🛑 Cập nhật Excel thất bại cho {folder_name}. Bỏ qua việc cắm cờ!")
                                continue 
                                    
                            with open(marker_done_post, "w", encoding="utf-8") as f:
                                f.write("Trạng thái Hậu kỳ: ok")
                                
                            print(f"🏁 ĐÃ ĐÓNG DẤU HẬU KỲ XONG CHO: {folder_name}")
                        else:
                            print(f"⚠️ Quá trình tạo Audio thất bại cho {folder_name}. Chờ vòng sau xử lý lại.")
        except Exception as e:
            print(f"⚠️ Lỗi khi quét Output: {e}")
            traceback.print_exc()
        time.sleep(2)


# ==========================================
# GIAO DIỆN HIỆN ĐẠI BẰNG CUSTOMTKINTER
# ==========================================
ctk.set_appearance_mode("dark")  # Giao diện Tối
ctk.set_default_color_theme("blue")  # Tone màu chủ đạo Xanh dương

class PrintRedirector:
    def __init__(self, text_widget):
        self.text_widget = text_widget
    def write(self, string):
        self.text_widget.insert("end", string)
        self.text_widget.see("end")
    def flush(self): pass

def browse_input():
    path = filedialog.askdirectory(title="Chọn thư mục Input", initialdir="C:\\")
    if path:
        entry_in.delete(0, 'end')
        entry_in.insert(0, path)

def browse_output():
    path = filedialog.askdirectory(title="Chọn thư mục Output", initialdir="C:\\")
    if path:
        entry_out.delete(0, 'end')
        entry_out.insert(0, path)

def load_scrollable_langs():
    # Xóa sạch các frame cũ bên trong Scrollable Frame
    for widget in scroll_lang.winfo_children():
        widget.destroy()
        
    data = load_lang_map()
    for code, voice in data.items():
        # Render lại từng dòng cực kỳ sang trọng
        row = ctk.CTkFrame(scroll_lang, fg_color="transparent")
        row.pack(fill="x", pady=2)
        
        lbl = ctk.CTkLabel(row, text=f"🌐  {code.upper()}   ➝   {voice}", font=ctk.CTkFont(size=13, weight="bold"))
        lbl.pack(side="left", padx=10)
        
        btn_del = ctk.CTkButton(row, text="❌ Xóa", width=60, height=24, fg_color="#D16969", hover_color="#A34747",
                                command=lambda k=code: del_lang(k))
        btn_del.pack(side="right", padx=10)

def add_lang():
    code = entry_lang_code.get().strip()
    voice = entry_lang_voice.get().strip()
    if code and voice:
        data = load_lang_map()
        data[code] = voice
        with open(LANG_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        load_scrollable_langs()
        entry_lang_code.delete(0, 'end')
        entry_lang_voice.delete(0, 'end')
    else:
        messagebox.showwarning("Thiếu dữ liệu", "Vui lòng nhập đủ Mã Ngôn Ngữ và Voice!")

def del_lang(code):
    data = load_lang_map()
    if code in data:
        del data[code]
        with open(LANG_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        load_scrollable_langs()

def start_system():
    global INPUT_DIR, OUTPUT_DIR, IS_RUNNING, GENERATE_SUB
    INPUT_DIR = entry_in.get().strip()
    OUTPUT_DIR = entry_out.get().strip()
    GENERATE_SUB = sub_var.get() == 1
    
    if not INPUT_DIR or not OUTPUT_DIR:
        messagebox.showerror("Lỗi", "Đường dẫn IN / OUT không được bỏ trống!")
        return
        
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    IS_RUNNING = True
    btn_start.configure(state="disabled", fg_color="#444444")
    btn_stop.configure(state="normal", fg_color="#DA3633")
    
    print("\n🚀 KÍCH HOẠT HỆ THỐNG AUTO TTS 3 LUỒNG...")
    print(f"📌 Chế độ tạo Subtitle: {'BẬT (Có)' if GENERATE_SUB else 'TẮT (Không)'}")
    
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=continuous_scanner, daemon=True).start()
    threading.Thread(target=output_scanner, daemon=True).start()

def stop_system():
    global IS_RUNNING
    IS_RUNNING = False
    btn_start.configure(state="normal", fg_color="#238636")
    btn_stop.configure(state="disabled", fg_color="#444444")
    print("\n🛑 Đang ra lệnh dừng khẩn cấp... Các tiến trình sẽ dừng lại an toàn sau vài giây.")


# KHỞI TẠO CỬA SỔ CHÍNH
root = ctk.CTk()
root.title("Auto TTS Post-Production Pipeline v3.0")
root.geometry("850x780")

# 1. KHUNG PATHS
frame_paths = ctk.CTkFrame(root, corner_radius=10)
frame_paths.pack(fill="x", padx=20, pady=15)

lbl_title_path = ctk.CTkLabel(frame_paths, text="THIẾT LẬP ĐƯỜNG DẪN", font=ctk.CTkFont(size=14, weight="bold"))
lbl_title_path.grid(row=0, column=0, columnspan=3, pady=(10, 5), sticky="w", padx=15)

ctk.CTkLabel(frame_paths, text="INPUT FOLDER:").grid(row=1, column=0, sticky="w", padx=15, pady=5)
entry_in = ctk.CTkEntry(frame_paths, width=500, corner_radius=5)
entry_in.insert(0, INPUT_DIR)
entry_in.grid(row=1, column=1, padx=10, pady=5)
ctk.CTkButton(frame_paths, text="📁 Chọn", width=80, command=browse_input).grid(row=1, column=2, padx=10)

ctk.CTkLabel(frame_paths, text="OUTPUT FOLDER:").grid(row=2, column=0, sticky="w", padx=15, pady=15)
entry_out = ctk.CTkEntry(frame_paths, width=500, corner_radius=5)
entry_out.insert(0, OUTPUT_DIR)
entry_out.grid(row=2, column=1, padx=10, pady=(5, 15))
ctk.CTkButton(frame_paths, text="📁 Chọn", width=80, command=browse_output).grid(row=2, column=2, padx=10)

# 2. KHUNG SETTING (RATIO SUB)
frame_settings = ctk.CTkFrame(root, fg_color="transparent")
frame_settings.pack(fill="x", padx=20, pady=0)

ctk.CTkLabel(frame_settings, text="Tạo Subtitle (Hardcode):", font=ctk.CTkFont(weight="bold")).pack(side="left")
sub_var = ctk.IntVar(value=1)
ctk.CTkRadioButton(frame_settings, text="Có Sub", variable=sub_var, value=1).pack(side="left", padx=20)
ctk.CTkRadioButton(frame_settings, text="Không Sub", variable=sub_var, value=0).pack(side="left")

# 3. KHUNG QUẢN LÝ NGÔN NGỮ (Tân tiến)
frame_lang = ctk.CTkFrame(root, corner_radius=10)
frame_lang.pack(fill="x", padx=20, pady=15)

lbl_title_lang = ctk.CTkLabel(frame_lang, text="QUẢN LÝ NGÔN NGỮ (LANGUAGE MAP)", font=ctk.CTkFont(size=14, weight="bold"))
lbl_title_lang.pack(anchor="w", padx=15, pady=(10, 5))

frame_lang_inputs = ctk.CTkFrame(frame_lang, fg_color="transparent")
frame_lang_inputs.pack(fill="x", padx=15, pady=5)

ctk.CTkLabel(frame_lang_inputs, text="Mã (vd: es):").pack(side="left")
entry_lang_code = ctk.CTkEntry(frame_lang_inputs, width=80)
entry_lang_code.pack(side="left", padx=(5, 15))

ctk.CTkLabel(frame_lang_inputs, text="Voice (vd: Explaned TBN):").pack(side="left")
entry_lang_voice = ctk.CTkEntry(frame_lang_inputs, width=250)
entry_lang_voice.pack(side="left", padx=(5, 15))

ctk.CTkButton(frame_lang_inputs, text="➕ Lưu Voice", width=100, command=add_lang).pack(side="left")

# Box xịn xò để thay thế Listbox
scroll_lang = ctk.CTkScrollableFrame(frame_lang, height=120, fg_color="#1E1E1E")
scroll_lang.pack(fill="x", padx=15, pady=(5, 15))
load_scrollable_langs()

# 4. KHUNG ĐIỀU KHIỂN CHÍNH
frame_controls = ctk.CTkFrame(root, fg_color="transparent")
frame_controls.pack(fill="x", padx=20, pady=10)

btn_start = ctk.CTkButton(frame_controls, text="▶ KHỞI ĐỘNG HỆ THỐNG", font=ctk.CTkFont(size=15, weight="bold"), height=45, fg_color="#238636", hover_color="#2EA043", command=start_system)
btn_start.pack(side="left", expand=True, fill="x", padx=(0, 10))

btn_stop = ctk.CTkButton(frame_controls, text="⏹ DỪNG LẠI", font=ctk.CTkFont(size=15, weight="bold"), height=45, fg_color="#444444", state="disabled", command=stop_system)
btn_stop.pack(side="right", expand=True, fill="x", padx=(10, 0))

# 5. KHUNG CONSOLE LOG
frame_log = ctk.CTkFrame(root, corner_radius=10)
frame_log.pack(fill="both", expand=True, padx=20, pady=(5, 20))

lbl_title_log = ctk.CTkLabel(frame_log, text="NHẬT KÝ HỆ THỐNG (CONSOLE)", font=ctk.CTkFont(size=14, weight="bold"))
lbl_title_log.pack(anchor="w", padx=15, pady=(10, 5))

console_text = ctk.CTkTextbox(frame_log, bg_color="transparent", fg_color="#111111", text_color="#4AF626", font=("Consolas", 12))
console_text.pack(fill="both", expand=True, padx=15, pady=(0, 15))

# Gắn stdout vào Console UI
sys.stdout = PrintRedirector(console_text)

if __name__ == "__main__":
    print("UI Ready. Configure your paths and click 'KHỞI ĐỘNG HỆ THỐNG'...")
    root.mainloop()