import subprocess
import os
from Code.config import PATHS

class VideoEngine:
    HARDWARE_INFO = "CPU Safe Mode"
    ENCODER_PRESET = "libx264" 
    HW_ACCEL = ""
    
    @staticmethod
    def detect_hardware():
        final_gpu_name = "Unknown"
        final_encoder = "libx264"
        final_hw_accel = ""
        
        try:
            ps_cmd = 'powershell -command "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"'
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            r = subprocess.run(ps_cmd, capture_output=True, text=True, shell=True, startupinfo=startupinfo)
            
            if r.stdout:
                lines = [line.strip() for line in r.stdout.split('\n') if line.strip()]
                found_dedicated = False 

                for line in lines:
                    upper_name = line.upper()
                    if "NVIDIA" in upper_name:
                        final_encoder = "h264_nvenc"
                        final_hw_accel = "-hwaccel cuda -hwaccel_output_format cuda"
                        final_gpu_name = f"{line} (NVENC Enabled)"
                        found_dedicated = True
                        break  
                    elif ("AMD" in upper_name or "RADEON" in upper_name) and not found_dedicated:
                        final_encoder = "h264_amf" 
                        final_gpu_name = f"{line} (AMF Enabled)"
                        found_dedicated = True
                    elif "INTEL" in upper_name and not found_dedicated:
                        final_encoder = "h264_qsv"
                        final_hw_accel = "-hwaccel qsv -c:v h264_qsv"
                        final_gpu_name = f"{line} (QSV Enabled)"
                
                if final_encoder == "libx264" and lines:
                     final_gpu_name = f"CPU Only ({lines[0]})"

        except Exception as e:
            final_gpu_name = "Lỗi nhận diện: " + str(e)

        VideoEngine.HARDWARE_INFO = final_gpu_name
        VideoEngine.ENCODER_PRESET = final_encoder
        VideoEngine.HW_ACCEL = final_hw_accel
        return final_gpu_name

    @classmethod
    def get_encoder_params(cls):
        if "nvenc" in cls.ENCODER_PRESET:
            return ["-preset", "p4", "-rc", "constqp", "-qp", "23"]
        elif "amf" in cls.ENCODER_PRESET:
            return ["-quality", "speed", "-rc", "cqp", "-qp_i", "23", "-qp_p", "23"]
        elif "qsv" in cls.ENCODER_PRESET:
            return ["-preset", "veryfast", "-global_quality", "23"]
        else:
            return ["-preset", "ultrafast", "-crf", "23"]

    @staticmethod
    def get_duration(file_path):
        cmd = [PATHS["ffprobe"], "-v", "error", "-show_entries", "format=duration", 
               "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)]
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, 
                                 startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW)
            return float(res.stdout.strip())
        except Exception as e:
            print(f"Lỗi Probe: {e}")
            return None

    @staticmethod
    def has_audio(file_path):
        """Kiểm tra xem file video có stream âm thanh hay không"""
        cmd = [PATHS["ffprobe"], "-v", "error", "-select_streams", "a", 
               "-show_entries", "stream=codec_type", "-of", 
               "default=noprint_wrappers=1:nokey=1", str(file_path)]
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, 
                                 startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW)
            # Nếu trả về chuỗi có độ dài > 0 (tức là có chữ 'audio'), nghĩa là có âm thanh
            return len(res.stdout.strip()) > 0
        except Exception:
            return False

    @staticmethod
    def build_atempo_filter(speed):
        chain = []
        if speed < 0.5: speed = 0.5
        if speed > 100: speed = 100 
        while speed > 2.0:
            chain.append("atempo=2.0"); speed /= 2.0
        while speed < 0.5:
            chain.append("atempo=0.5"); speed /= 0.5
        chain.append(f"atempo={speed}")
        return ",".join(chain)

    @staticmethod
    def run_ffmpeg_debug(cmd):
        """Hàm giờ đây trả về True (Thành công) hoặc False (Thất bại) để hệ thống tự cứu hộ"""
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        try:
            process = subprocess.run(
                cmd, 
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW,
                encoding='utf-8', errors='replace'
            )
            if process.returncode != 0:
                error_msg = f"=== FFMPEG ERROR ===\nCMD: {' '.join(cmd)}\n\nSTDERR:\n{process.stderr}\n"
                with open("error_log.txt", "a", encoding="utf-8") as f:
                    f.write(error_msg + "\n" + "-"*30 + "\n")
                return False # Báo lỗi
            return True # Thành công
                    
        except Exception as e:
            with open("error_log.txt", "a", encoding="utf-8") as f:
                f.write(f"PYTHON SUBPROCESS ERROR: {str(e)}\n")
            return False

    # ==========================================
    # CÁC HÀM RENDER ĐƯỢC TRANG BỊ AUTO-FALLBACK
    # ==========================================

    @classmethod
    def generate_image_clip(cls, image_path, output_path, duration, _force_cpu=False):
        # Chế độ này đã tự tạo audio giả (anullsrc) nên không cần kiểm tra has_audio
        cmd = [PATHS["ffmpeg"], "-y"]
        current_encoder = "libx264" if _force_cpu else cls.ENCODER_PRESET
        
        if not _force_cpu and "cuda" in cls.HW_ACCEL:
            cmd.extend(cls.HW_ACCEL.split())
            
        cmd.extend([
            "-loop", "1", "-i", str(image_path),
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", 
            "-c:v", current_encoder, 
            "-t", str(duration),
            "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:-1:-1:color=black", # Đã fix lỗi toán học
            "-pix_fmt", "yuv420p"
        ])
        
        if _force_cpu: cmd.extend(["-preset", "ultrafast", "-crf", "23"])
        else: cmd.extend(cls.get_encoder_params())
            
        cmd.extend(["-c:a", "aac", "-ar", "44100", "-shortest", "-r", "30", str(output_path)])
        
        success = cls.run_ffmpeg_debug(cmd)
        
        # Nếu GPU lỗi -> Lùi về CPU chạy lại ngay lập tức
        if not success and not _force_cpu and cls.ENCODER_PRESET != "libx264":
            cls.generate_image_clip(image_path, output_path, duration, _force_cpu=True)

    @classmethod
    def process_clip(cls, input_p, output_p, target_dur, pts_ratio, audio_speed, _force_cpu=False):
        # KIỂM TRA AUDIO CỦA CLIP ĐẦU VÀO
        has_aud = cls.has_audio(input_p)
        
        cmd_base = [PATHS["ffmpeg"], "-y"]
        current_encoder = "libx264" if _force_cpu else cls.ENCODER_PRESET
        
        if not _force_cpu and "cuda" in cls.HW_ACCEL:
            cmd_base.extend(cls.HW_ACCEL.split())
            
        cmd_base.extend(["-i", str(input_p)])
        
        # NẾU KHÔNG CÓ AUDIO, TẠO MỘT TRACK GIẢ (INDEX 1)
        if not has_aud:
            cmd_base.extend(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"])
        
        if not _force_cpu and "cuda" in cls.HW_ACCEL:
            vf_filter = f"[0:v]setpts={pts_ratio}*PTS,scale_cuda=1920:1080:format=yuv420p[v]"
        else:
            vf_filter = f"[0:v]scale=1920:1080,setpts={pts_ratio}*PTS,format=yuv420p[v]"

        # NẾU CÓ AUDIO, ÁP DỤNG ATEMPO. NẾU KHÔNG, MAP TRACK GIẢ VÀO.
        if has_aud:
            audio_filter = cls.build_atempo_filter(audio_speed)
            cmd_base.extend([
                "-filter_complex", f"{vf_filter};[0:a]{audio_filter}[a]",
                "-map", "[v]", "-map", "[a]",
            ])
        else:
            cmd_base.extend([
                "-filter_complex", f"{vf_filter}",
                "-map", "[v]", "-map", "1:a" 
            ])

        cmd_base.extend(["-c:v", current_encoder])

        if _force_cpu: cmd_base.extend(["-preset", "ultrafast", "-crf", "23"])
        else: cmd_base.extend(cls.get_encoder_params())
            
        cmd_base.extend(["-c:a", "aac", "-ar", "44100"])
        
        # NẾU DÙNG TRACK GIẢ, CẦN CẮT ĐUÔI
        if not has_aud:
             cmd_base.append("-shortest")
             
        cmd_base.extend(["-r", "30", str(output_p)])
        
        success = cls.run_ffmpeg_debug(cmd_base)
        
        if not success and not _force_cpu and cls.ENCODER_PRESET != "libx264":
             cls.process_clip(input_p, output_p, target_dur, pts_ratio, audio_speed, _force_cpu=True)

    @classmethod
    def split_video(cls, input_p, output_p, start_time, duration, _force_cpu=False):
        # KIỂM TRA AUDIO CỦA VIDEO GỐC
        has_aud = cls.has_audio(input_p)
        
        current_encoder = "libx264" if _force_cpu else cls.ENCODER_PRESET
        cmd_base = [PATHS["ffmpeg"], "-y"]
        
        cmd_base.extend(["-ss", str(start_time), "-i", str(input_p)])
        
        # NẾU KHÔNG CÓ AUDIO, TẠO MỘT TRACK GIẢ (INDEX 1)
        if not has_aud:
            cmd_base.extend(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"])

        cmd_base.extend(["-t", str(duration)])
        
        # XỬ LÝ MAP NẾU KHÔNG CÓ AUDIO
        if not has_aud:
            cmd_base.extend(["-map", "0:v", "-map", "1:a", "-shortest"])

        cmd_base.extend(["-c:v", current_encoder])

        if _force_cpu: cmd_base.extend(["-preset", "ultrafast", "-crf", "23"])
        else: cmd_base.extend(cls.get_encoder_params())
            
        cmd_base.extend(["-c:a", "aac", "-ar", "44100", str(output_p)])
        
        success = cls.run_ffmpeg_debug(cmd_base)
        
        if not success and not _force_cpu and cls.ENCODER_PRESET != "libx264":
             cls.split_video(input_p, output_p, start_time, duration, _force_cpu=True)