import os
import subprocess
import shutil
import time 
from concurrent.futures import ThreadPoolExecutor
# Import từ source code của bạn
from Code.video_engine import VideoEngine
from Code.srt_utils import SRTProcessor
from Code.config import PATHS
import traceback 
# =========================================================
# HÀM MỚI: CHỜ FILE ĐƯỢC GHI XONG (CHỐNG LỖI MOOV ATOM)
# =========================================================
def wait_for_file_ready(file_path, wait_time=3, timeout=300):
    print(f"⏳ Đang kiểm tra tính toàn vẹn của file: {os.path.basename(file_path)}...")
    start_time = time.time()
    last_size = -1
    
    while True:
        if time.time() - start_time > timeout:
            print(f"❌ Lỗi: File không sẵn sàng sau {timeout} giây.")
            return False
            
        try:
            current_size = os.path.getsize(file_path)
            
            if current_size == 0:
                time.sleep(1)
                continue
                
            if current_size == last_size:
                print(f"✅ File đã sẵn sàng (Kích thước: {current_size / (1024*1024):.2f} MB)")
                return True
                
            last_size = current_size
            time.sleep(wait_time)
            
        except OSError:
            time.sleep(1)

# =========================================================
# QUY TRÌNH CHÍNH
# =========================================================
def run_video_sync_pipeline(project_out_dir, base_name, max_workers=6, generate_sub=True):
    try:
        orig_vid = os.path.join(project_out_dir, f"{base_name}.mp4")
        orig_srt = os.path.join(project_out_dir, f"{base_name}.srt")

        if not os.path.exists(orig_vid) or not os.path.exists(orig_srt):
            print(f"⚠️ Thiếu Video/SRT gốc. Bỏ qua Hậu kỳ Video cho: {base_name}")
            return False

        if not wait_for_file_ready(orig_vid):
            print(f"⚠️ Bỏ qua dự án {base_name} vì file video gốc bị lỗi hoặc đang bị khóa.")
            return False

        print(f"\n🎬 BẮT ĐẦU QUY TRÌNH AUTO VIDEO CHO DỰ ÁN: {base_name}")

        # =========================================================
        # BƯỚC 1: CẮT VIDEO GỐC THEO NHỊP SRT GỐC
        # =========================================================
        try:
            clips_dir_goc = os.path.join(project_out_dir, f"{base_name}_Splitted_Goc")
            os.makedirs(clips_dir_goc, exist_ok=True)
            orig_srt_data = SRTProcessor.parse_timestamps(orig_srt)

            split_tasks = []
            last_end = orig_srt_data[0]['start'] if orig_srt_data else 0
            
            for i, sub in enumerate(orig_srt_data):
                vid_id = i + 1
                start_time = last_end if i > 0 else sub['start']
                last_end = sub['end']
                dur = max(sub['end'] - start_time, 0.1)
                
                out_clip = os.path.join(clips_dir_goc, f"clip_{vid_id:03d}.mp4")
                if not os.path.exists(out_clip):
                    split_tasks.append((orig_vid, out_clip, start_time, dur))

            if split_tasks:
                print(f"✂️ Đang cắt {len(split_tasks)} phân đoạn từ Video gốc...")
                with ThreadPoolExecutor(max_workers=max_workers) as exe:
                    futures = [exe.submit(VideoEngine.split_video, t[0], t[1], t[2], t[3]) for t in split_tasks]
                    [f.result() for f in futures]
                    
        except Exception as e:
            print(f"\n❌ LỖI Ở BƯỚC 1 (Cắt video gốc): {e}")
            traceback.print_exc() 
            return False

        # =========================================================
        # BƯỚC 2 & 3: XỬ LÝ TỪNG NGÔN NGỮ (CO KÉO -> NỐI -> GHÉP)
        # =========================================================
        
        # [ĐÃ SỬA] Lọc file chuẩn xác: Bỏ qua file rác và file gốc
        fixed_srts = [
            f for f in os.listdir(project_out_dir) 
            if f.startswith(base_name) 
            and f.endswith("_fixed.srt") 
            and not "_Stretched_" in f
            and f != f"{base_name}_fixed.srt"  
        ]
        
        for f_srt in fixed_srts:
            try:
                lang_code = f_srt.replace(f"{base_name}_", "").replace("_fixed.srt", "")
                is_goc = False
                if lang_code == f"{base_name}": 
                    lang_code = "Goc_Fixed"
                    is_goc = True
                    
                print(f"\n🎞️ Đang xử lý Video cho ngôn ngữ: {lang_code.upper()}...")
                fixed_srt_path = os.path.join(project_out_dir, f_srt)
                fixed_srt_data = SRTProcessor.parse_timestamps(fixed_srt_path)

                stretch_dir = os.path.join(project_out_dir, f"{base_name}_Stretched_{lang_code}")
                os.makedirs(stretch_dir, exist_ok=True)

                # --- 2.1 CO KÉO (STRETCH) ---
                stretch_tasks = []
                for i, sub in enumerate(fixed_srt_data):
                    vid_id = i + 1
                    source_clip = os.path.join(clips_dir_goc, f"clip_{vid_id:03d}.mp4")
                    if not os.path.exists(source_clip): continue

                    start_ref = sub['start'] if i == 0 else fixed_srt_data[i-1]['end']
                    target_dur = max(sub['end'] - start_ref, 0.1)
                    out_stretch = os.path.join(stretch_dir, f"clip_{vid_id:03d}.mp4")
                    
                    if not os.path.exists(out_stretch):
                        orig_dur = VideoEngine.get_duration(source_clip) or target_dur
                        stretch_tasks.append((source_clip, out_stretch, target_dur, target_dur/orig_dur, orig_dur/target_dur))

                if stretch_tasks:
                    print(f"   ⏳ Đang ép xung {len(stretch_tasks)} clip...")
                    with ThreadPoolExecutor(max_workers=max_workers) as exe:
                        futures = [exe.submit(VideoEngine.process_clip, t[0], t[1], t[2], t[3], t[4]) for t in stretch_tasks]
                        [f.result() for f in futures] 

                # --- 2.2 NỐI CÁC CLIP ĐÃ ÉP XUNG (CONCAT) ---
                print(f"   🔗 Đang nối các clip ngắn thành 1 video liền mạch...")
                concat_list_path = os.path.join(stretch_dir, "concat_list.txt")
                temp_video = os.path.join(project_out_dir, f"temp_{lang_code}.mp4")
                
                clips = sorted([f for f in os.listdir(stretch_dir) if f.startswith("clip_") and f.endswith(".mp4")])
                if not clips:
                    print(f"❌ LỖI: Không tìm thấy clip nào trong {stretch_dir}")
                    continue
                
                # [SỬA LỖI CHÍ MẠNG NAS] 
                # 1. Dùng newline='\n' để ép chuẩn file text của Linux (FFmpeg rất thích điều này)
                with open(concat_list_path, "w", encoding="utf-8", newline='\n') as f:
                    for clip in clips:
                        # 2. Ghi TÊN FILE tương đối (Không chứa //Synology-new...)
                        f.write(f"file '{clip}'\n")
                
                # 3. Đổi dấu "\" thành "/" ở đường dẫn truyền vào lệnh FFmpeg
                concat_list_ff = concat_list_path.replace("\\", "/")
                #Sleep để NAS ghi xong file concat_list.txt
                time.sleep(3)
                # Gọi FFmpeg nối video (FFmpeg sẽ tự tìm clip trong cùng thư mục với concat_list.txt)
                concat_cmd = [
                    PATHS["ffmpeg"], "-y", "-f", "concat", "-safe", "0", 
                    "-i", concat_list_ff, "-c", "copy", temp_video
                ]
                
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
                concat_result = subprocess.run(concat_cmd, capture_output=True, text=True, startupinfo=startupinfo)
                if concat_result.returncode != 0:
                    print(f"❌ LỖI FFMPEG BƯỚC NỐI VIDEO (CONCAT):\n{concat_result.stderr}")
                    continue

                # --- 2.3 GỘP AUDIO & ĐÓNG DẤU PHỤ ĐỀ ---
                audio_name = f"{base_name}_final.mp3" if is_goc else f"{base_name}_{lang_code}_final.mp3"
                audio_file = os.path.join(project_out_dir, audio_name)
                final_dubbed_vid = os.path.join(project_out_dir, f"{base_name}_{lang_code}_DUBBED.mp4")

                if os.path.exists(temp_video) and os.path.exists(audio_file):
                    msg = "và Hardcode Subtitles" if generate_sub else "(Không ghép Sub)"
                    print(f"   🎬 Đang Mix Audio {msg} (Có thể mất vài phút)...")
                    
                    # 1. Khởi tạo mảng lệnh cơ bản
                    merge_cmd = [
                        PATHS["ffmpeg"], "-y",
                        "-i", temp_video,
                        "-i", audio_file,
                        "-map", "0:v:0",
                        "-map", "1:a:0"
                    ]
                    
                    # 2. KIỂM TRA ĐIỀU KIỆN: Nếu Giao diện chọn CÓ -> Nhét thêm filter Subtitle vào mảng
                    if generate_sub:
                        srt_ff_path = fixed_srt_path.replace('\\', '/').replace(':', '\\:')
                        merge_cmd.extend(["-vf", f"subtitles='{srt_ff_path}'"])
                    
                    # 3. Nối các cấu hình chốt hạ vào đuôi mảng
                    merge_cmd.extend([
                        "-c:v", "libx264",
                        "-preset", "fast", 
                        "-c:a", "aac",
                        "-b:a", "192k",
                        "-shortest",
                        final_dubbed_vid
                    ])
                    
                    # Chạy lệnh
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    merge_result = subprocess.run(merge_cmd, capture_output=True, text=True, startupinfo=startupinfo, timeout=1800)
                    
                    if merge_result.returncode != 0:
                        print(f"❌ LỖI FFMPEG BƯỚC GHÉP ÂM THANH/SUB:\n{merge_result.stderr}")
                        continue
                    
                    print(f"   ✅ ĐÃ XUẤT XƯỞNG THÀNH CÔNG: {os.path.basename(final_dubbed_vid)}")
                    
                    # --- 2.4 DỌN RÁC TẠM THỜI ---
                    if os.path.exists(temp_video): os.remove(temp_video)
                    if os.path.exists(stretch_dir): shutil.rmtree(stretch_dir)
                else:
                    print(f"   ⚠️ Thiếu file temp_video hoặc audio_file để gộp cho ngôn ngữ {lang_code}")

            except Exception as e:
                print(f"\n❌ LỖI KHI XỬ LÝ NGÔN NGỮ {lang_code}: {e}")
                traceback.print_exc()
                continue 

        # Xóa luôn folder cắt video gốc sau khi đã chạy xong toàn bộ ngôn ngữ
        if os.path.exists(clips_dir_goc): shutil.rmtree(clips_dir_goc)

        # =========================================================
        # CHỐT BẢO HIỂM CUỐI CÙNG
        # =========================================================
        # [ĐÃ SỬA] Đếm số lượng SRT y hệt như bộ lọc ở trên
        actual_fixed_srts = [
            f for f in os.listdir(project_out_dir) 
            if f.startswith(base_name) 
            and f.endswith("_fixed.srt") 
            and not "_Stretched_" in f
            and f != f"{base_name}_fixed.srt"
        ]
        
        dubbed_files = [f for f in os.listdir(project_out_dir) if f.endswith("_DUBBED.mp4")]
        
        expected_count = len(actual_fixed_srts)
        actual_count = len(dubbed_files)

        if expected_count == 0:
            print(f"\n⚠️ LỖI: Không tìm thấy bất kỳ file _fixed.srt hợp lệ nào để ghép video!")
            return False

        if actual_count < expected_count:
            print(f"\n⚠️ CẢNH BÁO ĐỎ: Thiếu Video! Yêu cầu {expected_count} video nhưng chỉ xuất được {actual_count} video.")
            print("🛑 Trả về False để giữ nguyên hiện trường cho bạn check lỗi FFmpeg.")
            return False

        print(f"\n✨ TẤT CẢ QUY TRÌNH VIDEO CHO [{base_name}] ĐÃ HOÀN TẤT THỰC SỰ! (Đã xuất đủ {actual_count}/{expected_count} Video)")
        print("-" * 50)
        return True

    except Exception as e:
        print(f"\n❌ LỖI KHÔNG XÁC ĐỊNH TRONG LUỒNG CHÍNH: {e}")
        traceback.print_exc()
        return False
