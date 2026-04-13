import os
import sys
import re
from datetime import timedelta
from mutagen.mp3 import MP3
from pydub import AudioSegment

# --- CẤU HÌNH ĐƯỜNG DẪN FFMPEG (Cho Pydub) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FFMPEG_DIR = os.path.join(BASE_DIR, "ffmpeg_bin")

# DÒNG QUAN TRỌNG NHẤT: Thêm thư mục chứa ffmpeg vào biến môi trường hệ thống
os.environ["PATH"] += os.pathsep + os.path.abspath(FFMPEG_DIR)

ext = ".exe" if sys.platform.startswith("win") else ""
AudioSegment.converter = os.path.join(FFMPEG_DIR, f"ffmpeg{ext}")
AudioSegment.ffprobe = os.path.join(FFMPEG_DIR, f"ffprobe{ext}")

# --- 1. CÁC HÀM TRỢ GIÚP THỜI GIAN & SRT ---

def time_to_td(t_str):
    """Chuyển đổi chuỗi thời gian SRT thành timedelta cực kỳ trâu bò, chống lỗi Format"""
    # Xóa khoảng trắng thừa và đồng nhất các dấu phân cách (dấu phẩy, dấu chấm đều biến thành dấu hai chấm)
    t_str = t_str.strip().replace(',', ':').replace('.', ':')
    parts = t_str.split(':')
    
    # Ép kiểu an toàn: Có phần nào thì lấy phần đó, thiếu thì mặc định là 0
    h = int(parts[0]) if len(parts) > 0 else 0
    m = int(parts[1]) if len(parts) > 1 else 0
    s = int(parts[2]) if len(parts) > 2 else 0
    ms = int(parts[3]) if len(parts) > 3 else 0
    
    return timedelta(hours=h, minutes=m, seconds=s, milliseconds=ms)

def td_to_time(td):
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    milliseconds = int(td.microseconds / 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

def srt_time_to_ms(time_str):
    """Chuyển đổi SRT (00:00:00,000) sang milliseconds."""
    hours, minutes, seconds = time_str.split(':')
    seconds, milliseconds = seconds.split(',')
    return int(hours) * 3600000 + int(minutes) * 60000 + int(seconds) * 1000 + int(milliseconds)

def parse_srt(file_path):
    if not os.path.exists(file_path):
        return []
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read().strip()
    blocks = re.split(r'\n\n+', content)
    parsed_blocks = []
    for block in blocks:
        lines = block.split('\n')
        if len(lines) >= 3:
            times = lines[1].split(' --> ')
            parsed_blocks.append({
                'id': lines[0],
                'start': time_to_td(times[0]),
                'end': time_to_td(times[1]),
                'text': '\n'.join(lines[2:])
            })
    return parsed_blocks

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]

# --- 2. BƯỚC 1: FIX SRT TIMINGS ---

def sync_srt_timings(orig_srt_path, target_srt_path, audio_folder, output_srt_path):
    print(">>> Bước 1: Đang chuẩn hóa file SRT (SRT theo Audio)...")
    orig_blocks = parse_srt(orig_srt_path)
    target_blocks = parse_srt(target_srt_path)
    
    if not orig_blocks or not target_blocks:
        print("❌ Lỗi: Không thể đọc file SRT gốc hoặc file cần fix.")
        return False

    gaps = [orig_blocks[i+1]['start'] - orig_blocks[i]['end'] for i in range(len(orig_blocks) - 1)]
    
    files = [f for f in os.listdir(audio_folder) if f.lower().endswith('.mp3')]
    files.sort(key=natural_sort_key)
    
    if len(files) != len(target_blocks):
        print(f"⚠️ Cảnh báo: Số lượng file audio ({len(files)}) khác với SRT ({len(target_blocks)}).")

    current_start = orig_blocks[0]['start']
    with open(output_srt_path, 'w', encoding='utf-8') as out_f:
        for i, block in enumerate(target_blocks):
            if i < len(files):
                audio = MP3(os.path.join(audio_folder, files[i]))
                dur_td = timedelta(seconds=audio.info.length)
            else:
                dur_td = block['end'] - block['start']
                
            new_end = current_start + dur_td
            out_f.write(f"{block['id']}\n{td_to_time(current_start)} --> {td_to_time(new_end)}\n{block['text']}\n\n")
            
            if i < len(gaps):
                current_start = new_end + gaps[i]
    
    print(f"✅ Đã tạo file SRT cố định: {output_srt_path}")
    return True

# --- 3. BƯỚC 2: ADD SILENCE & MERGE AUDIO ---
def process_and_merge(input_folder, srt_fixed_path, output_folder, final_filename):
    print("\n>>> Bước 2: Đang xử lý thêm im lặng và ghép file...")
    try:
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)
        
        with open(srt_fixed_path, 'r', encoding='utf-8') as f:
            content = f.read()
        pattern = re.compile(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})')
        matches = pattern.findall(content)
        timings = [(srt_time_to_ms(start), srt_time_to_ms(end)) for start, end in matches]

        files = [f for f in os.listdir(input_folder) if f.endswith('.mp3')]
        files.sort(key=natural_sort_key)

        combined_audio = AudioSegment.empty()
        
        # Biến kiểm soát lỗi trong vòng lặp lẻ
        loop_error = False

        for i in range(len(files)):
            input_path = os.path.join(input_folder, files[i])
            output_individual_path = os.path.join(output_folder, files[i])
            
            try:
                current_audio = AudioSegment.from_mp3(input_path)
                silence_duration = 0
                if i < len(files) - 1 and i < len(timings) - 1:
                    current_end = timings[i][1]
                    next_start = timings[i+1][0]
                    silence_duration = max(0, next_start - current_end)

                processed_segment = current_audio + AudioSegment.silent(duration=silence_duration) if silence_duration > 0 else current_audio
                processed_segment.export(output_individual_path, format="mp3")
                combined_audio += processed_segment
            except Exception as e:
                print(f"   ❌ Lỗi tại file {files[i]}: {e}")
                loop_error = True

        # Export file tổng hợp
        combined_audio.export(final_filename, format="mp3")
        
        print("-" * 30)
        print(f"✨ HOÀN THÀNH TẤT CẢ!")
        print(f"📁 Thư mục file đã fix: {output_folder}")
        print(f"🎵 File tổng hợp: {final_filename}")
        
        # Trả về False nếu có bất kỳ lỗi nào trong vòng lặp
        return not loop_error

    except Exception as e:
        print(f"❌ Lỗi nghiêm trọng trong process_and_merge: {e}")
        return False

# --- HÀM CHÍNH (Cập nhật cơ chế Kiểm soát) ---

def run_post_processing_for_project(project_dir):
    print(f"\n🎧 ĐANG BẮT ĐẦU HẬU KỲ TẠI: {project_dir}")
    project_name = os.path.basename(project_dir)
    srt_goc_chuan = os.path.join(project_dir, f"{project_name}.srt")
    
    if not os.path.exists(srt_goc_chuan):
        print(f"⚠️ Không tìm thấy file gốc chuẩn nhịp ({project_name}.srt). Bỏ qua hậu kỳ.")
        return False

    all_success = True

    # ==========================================
    # --- XỬ LÝ FILE GỐC ---
    # ==========================================
    folder_audio_goc = os.path.join(project_dir, project_name)
    if os.path.exists(folder_audio_goc):
        goc_srt_da_fix = os.path.join(project_dir, f"{project_name}_fixed.srt")
        goc_output_fixed = os.path.join(project_dir, f"{project_name}_audio_fixed")
        goc_final_mp3 = os.path.join(project_dir, f"{project_name}_final.mp3")
        
        # KIỂM TRA: Nếu cả file Audio và Sub đã làm xong từ trước -> Bỏ qua
        if os.path.exists(goc_final_mp3) and os.path.exists(goc_srt_da_fix):
            print(f"\n--- ⏩ Đã có sẵn Audio GỐC ({project_name}), bỏ qua bước xử lý ---")
        else:
            print(f"\n--- ⏳ Đang xử lý ngôn ngữ GỐC: {project_name} ---")
            success_goc = sync_srt_timings(srt_goc_chuan, srt_goc_chuan, folder_audio_goc, goc_srt_da_fix)
            if success_goc:
                if not process_and_merge(folder_audio_goc, goc_srt_da_fix, goc_output_fixed, goc_final_mp3):
                    all_success = False
            else:
                all_success = False
    else:
        print(f"⚠️ Không tìm thấy thư mục audio gốc '{project_name}'.")
        all_success = False

    # ==========================================
    # --- XỬ LÝ FILE DỊCH ---
    # ==========================================
    target_srts = [f for f in os.listdir(project_dir) 
                   if f.endswith(".srt") 
                   and f != f"{project_name}.srt" 
                   and not f.endswith("_fixed.srt")]

    for srt_file in target_srts:
        base_name = os.path.splitext(srt_file)[0]
        srt_can_fix = os.path.join(project_dir, srt_file)
        folder_audio_dich = os.path.join(project_dir, base_name)
        srt_da_fix = os.path.join(project_dir, f"{base_name}_fixed.srt")
        folder_audio_fixed = os.path.join(project_dir, f"{base_name}_audio_fixed")
        file_audio_tong = os.path.join(project_dir, f"{base_name}_final.mp3")

        if not os.path.exists(folder_audio_dich):
            print(f"⚠️ Bỏ qua {base_name}: Không tìm thấy thư mục audio thô.")
            all_success = False 
            continue
            
        # KIỂM TRA: Nếu file dịch này đã làm xong từ lần trước -> Bỏ qua
        if os.path.exists(file_audio_tong) and os.path.exists(srt_da_fix):
            print(f"\n--- ⏩ Đã có sẵn Audio dịch: {base_name}, bỏ qua bước xử lý ---")
        else:
            print(f"\n--- ⏳ Đang xử lý ngôn ngữ dịch: {base_name} ---")
            if sync_srt_timings(srt_goc_chuan, srt_can_fix, folder_audio_dich, srt_da_fix):
                if not process_and_merge(folder_audio_dich, srt_da_fix, folder_audio_fixed, file_audio_tong):
                    all_success = False
            else:
                all_success = False

    return all_success
    