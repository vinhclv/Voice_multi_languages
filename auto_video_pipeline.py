import os
import subprocess
import shutil
from concurrent.futures import ThreadPoolExecutor

# Import từ source code của bạn
from Code.video_engine import VideoEngine
from Code.srt_utils import SRTProcessor
from Code.config import PATHS

def run_video_sync_pipeline(project_out_dir, base_name, max_workers=6):
    orig_vid = os.path.join(project_out_dir, f"{base_name}.mp4")
    orig_srt = os.path.join(project_out_dir, f"{base_name}.srt")

    if not os.path.exists(orig_vid) or not os.path.exists(orig_srt):
        print(f"⚠️ Thiếu Video/SRT gốc. Bỏ qua Hậu kỳ Video cho: {base_name}")
        return False

    print(f"\n🎬 BẮT ĐẦU QUY TRÌNH AUTO VIDEO CHO DỰ ÁN: {base_name}")

    # =========================================================
    # BƯỚC 1: CẮT VIDEO GỐC THEO NHỊP SRT GỐC
    # =========================================================
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

    # =========================================================
    # BƯỚC 2 & 3: CO KÉO CLIP -> NỐI LẠI -> GHÉP AUDIO & PHỤ ĐỀ
    # =========================================================
    fixed_srts = [f for f in os.listdir(project_out_dir) if f.endswith("_fixed.srt")]
    
    for f_srt in fixed_srts:
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
        with open(concat_list_path, "w", encoding="utf-8") as f:
            for clip in clips:
                f.write(f"file '{clip}'\n")
                
        concat_cmd = [
            PATHS["ffmpeg"], "-y", "-f", "concat", "-safe", "0", 
            "-i", concat_list_path, "-c", "copy", temp_video
        ]
        subprocess.run(concat_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # --- 2.3 GỘP AUDIO & ĐÓNG DẤU PHỤ ĐỀ (TỪ LOGIC CỦA BẠN) ---
        audio_name = f"{base_name}_final.mp3" if is_goc else f"{base_name}_{lang_code}_final.mp3"
        audio_file = os.path.join(project_out_dir, audio_name)
        final_dubbed_vid = os.path.join(project_out_dir, f"{base_name}_{lang_code}_DUBBED.mp4")

        if os.path.exists(temp_video) and os.path.exists(audio_file):
            print(f"   🎬 Đang Mix Audio và Hardcode Subtitles (Có thể mất vài phút)...")
            
            # Xử lý đường dẫn cho bộ lọc subtitles của FFmpeg trên Windows
            # Chuyển C:\A\B.srt -> C\:/A/B.srt
            srt_ff_path = fixed_srt_path.replace('\\', '/').replace(':', '\\:')
            
            merge_cmd = [
                PATHS["ffmpeg"], "-y",
                "-i", temp_video,
                "-i", audio_file,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-vf", f"subtitles='{srt_ff_path}'",
                "-c:v", "libx264",
                "-preset", "fast", # Để fast cho đỡ tốn thời gian chờ
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                final_dubbed_vid
            ]
            
            # Ẩn cửa sổ cmd đen
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.run(merge_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo)
            
            print(f"   ✅ ĐÃ XUẤT XƯỞNG THÀNH CÔNG: {os.path.basename(final_dubbed_vid)}")
            
            # --- 2.4 DỌN RÁC NGAY SAU KHI XONG NGÔN NGỮ NÀY ---
            if os.path.exists(temp_video): os.remove(temp_video)
            if os.path.exists(stretch_dir): shutil.rmtree(stretch_dir)

    # Xóa luôn folder cắt video gốc sau khi đã chạy xong toàn bộ ngôn ngữ
    if os.path.exists(clips_dir_goc): shutil.rmtree(clips_dir_goc)

    print(f"\n✨ TẤT CẢ QUY TRÌNH VIDEO CHO [{base_name}] ĐÃ HOÀN TẤT!")
    print("-" * 50)
    return True
