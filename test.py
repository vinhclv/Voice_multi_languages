import os
import shutil

# 1. CẤU HÌNH ĐƯỜNG DẪN
# Đổi lại đường dẫn này thành thư mục thực tế của bạn
INPUT_DIR = r"\\192.168.1.17\processing\Giai thich\chuyen anh sang viet"

def organize_files():
    # Tạo thư mục tổng chứa kết quả (nằm cùng cấp với thư mục gốc)
    parent_dir = os.path.dirname(INPUT_DIR)
    folder_name = os.path.basename(INPUT_DIR)
    output_base_dir = os.path.join(parent_dir, f"{folder_name}_Organized")
    
    os.makedirs(output_base_dir, exist_ok=True)
    print(f"📁 Thư mục lưu kết quả: {output_base_dir}\n")

    # Quét tất cả file mp4 trong thư mục
    for file in os.listdir(INPUT_DIR):
        if file.lower().endswith(".mp4"):
            base_name = os.path.splitext(file)[0]
            mp4_path = os.path.join(INPUT_DIR, file)
            
            # Tên file SRT mà script cần tìm (có đuôi _Final_Merged)
            srt_name = f"{base_name}_Final_Merged.srt"
            srt_path = os.path.join(INPUT_DIR, srt_name)

            # Nếu tìm thấy file SRT tương ứng
            if os.path.exists(srt_path):
                print(f"⏳ Đang xử lý: {base_name}")
                
                # 2. TẠO FOLDER CÙNG TÊN VỚI MP4
                sub_dir = os.path.join(output_base_dir, base_name)
                os.makedirs(sub_dir, exist_ok=True)
                
                # Đường dẫn đích (lúc này SRT đã được bỏ đuôi _Final_Merged)
                dest_mp4 = os.path.join(sub_dir, f"{base_name}.mp4")
                dest_srt = os.path.join(sub_dir, f"{base_name}.srt")

                # 3. NÉM FILE VÀO FOLDER VÀ ĐỔI TÊN
                try:
                    shutil.copy2(mp4_path, dest_mp4)
                    shutil.copy2(srt_path, dest_srt)
                    print(f"  ✅ Đã gom và đổi tên SRT thành công vào folder: {base_name}")
                except Exception as e:
                    print(f"  ❌ Lỗi khi xử lý file {base_name}: {e}")
            else:
                print(f"⚠️ Bỏ qua: {base_name} (Không tìm thấy {srt_name})")

    print("\n✨ HOÀN THÀNH QUY TRÌNH GOM FILE!")

if __name__ == "__main__":
    organize_files()