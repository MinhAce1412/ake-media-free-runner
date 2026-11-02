# Ake Media Free Runner

Runner miễn phí để Ake kiểm tra **hình ảnh thật** của video public phục vụ nghiên cứu content/đối thủ.

## Cách hoạt động

1. Ake có URL video public.
2. Thử đường public trực tiếp trước.
3. Nếu GitHub bị YouTube chặn anti-bot/login, **không dùng cookie, tài khoản hay cách vượt CAPTCHA**.
4. Khi có thể, dùng `vidIQ video_upload` giá **0 credit** làm cầu chuyển tạm sang MP4.
5. GitHub Actions dùng FFmpeg tạo **12 frame theo thứ tự thời gian + 1 contact sheet 4×3**.
6. Artifact chỉ giữ bằng chứng phân tích; **không lưu video nguồn**.
7. Chỉ sau khi Ake thực sự mở frame/contact sheet mới được ghi `VISUAL_REVIEW`.

## Mức bằng chứng

- `METADATA_ONLY`: chỉ biết link/title/số liệu.
- `TRANSCRIPT_L2`: biết lời nói/câu chuyện từ transcript.
- `MEDIA_FILE_READY_UNINSPECTED`: đã có file video thật nhưng chưa xem frame.
- `VISUAL_FRAMES_READY`: đã tạo frame nhưng Ake chưa mở xem.
- `VISUAL_REVIEW`: Ake đã thực sự xem frame/contact sheet.
- `MULTIMODAL_REVIEW`: đã có cả bằng chứng hình + âm thanh/nội dung.

## Giới hạn

- 12 frame đủ để xác nhận bố cục lớn, facecam/gameplay, overlay, thay đổi reaction và các cảnh xuất hiện ở các mốc lấy mẫu.
- 12 frame **không đủ** để khẳng định toàn bộ nhịp cắt, mọi zoom, toàn bộ meme/SFX/music hoặc câu hook nói.
- Muốn kết luận âm thanh/lời nói phải có transcript/ASR/audio evidence riêng.

## QA đầu tiên đã PASS

Video test: Tabi Tuấn Anh — `ej0mSE14enA`.

GitHub run: `41403501097`.

Kết quả:
- MP4 phân tích 1080×1920, ~24.64s.
- 12/12 frame tạo thành công.
- Contact sheet 4×3 tạo thành công.
- Artifact tải lại và mở xem thành công.
- Video nguồn không nằm trong artifact.

Repo này là hạ tầng phân tích nội bộ của Ake, không phải công cụ reupload nội dung.
