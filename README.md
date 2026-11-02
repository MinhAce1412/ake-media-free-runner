# Ake Media Free Runner

Runner miễn phí để Ake **xem, nghe và phân tích** video public phục vụ nghiên cứu content/đối thủ. Repo chỉ chứa code và evidence phân tích; không dùng để reupload nội dung.

## Hai tầng

### FAST — sàng lọc
- Metadata/public metrics.
- 12 frame + contact sheet khi cần xác minh hình.
- Dùng để chọn video nào đáng tốn công phân tích sâu.

### DEEP — mổ xẻ như editor
Chỉ chạy cho video đáng học hoặc content Minh sắp áp dụng.

Pipeline DEEP hiện gồm:
- **PySceneDetect**: phát hiện scene/cut.
- **OpenCV**: theo dõi biến đổi hình, motion spike, freeze/zoom candidate.
- **Tesseract vie+eng**: OCR chữ/caption/overlay ở các frame mẫu.
- **faster-whisper CPU INT8**: transcript tiếng Việt có timestamp.
- **librosa**: onset, silence, energy và BPM ước tính của soundtrack trộn.
- **YAMNet / AudioSet 521 classes**: xác suất speech/music/laughter/click/impact/whoosh/game audio và các audio event khác.
- **FFmpeg/FFprobe**: decode, audio extraction, codec/duration.

Một DEEP job phân tích tối đa 180 giây. Video dài hơn phải chia chunk/chapter để giữ thời gian chạy và free compute hợp lý.

## Cách lấy video

1. Ake có URL video public.
2. Thử đường public trực tiếp trước.
3. Nếu GitHub bị YouTube chặn anti-bot/login, **không dùng cookie, tài khoản hay cách vượt CAPTCHA**.
4. Khi có thể, dùng `vidIQ video_upload` giá **0 credit** làm cầu chuyển MP4 tạm.
5. GitHub Actions xử lý media rồi xóa file nguồn trước khi upload artifact.

## Mức bằng chứng

- `METADATA_ONLY`: link/title/số liệu.
- `TRANSCRIPT_L2`: lời nói/câu chuyện từ transcript.
- `MEDIA_FILE_READY_UNINSPECTED`: file thật tồn tại nhưng chưa đọc media.
- `VISUAL_FRAMES_READY`: frame đã tạo nhưng Ake chưa mở.
- `VISUAL_REVIEW`: Ake đã xem frame/contact sheet.
- `DEEP_EVIDENCE_READY`: máy đã đo temporal visual + ASR + OCR + audio features/events.
- `FULL_EDITOR_REVIEW`: chỉ được gắn sau khi Ake thực sự đọc evidence, xem visual cần thiết và giải thích các quyết định dựng bằng mức VERIFIED / STRONG INFERENCE / HYPOTHESIS / UNKNOWN.

## Luật chống bịa

- Scene detector/zoom detector/audio classifier là bằng chứng máy, không tự động biến thành kết luận editor.
- Zoom/freeze từ OpenCV chỉ là **candidate** cho tới khi xem sequence xung quanh.
- YAMNet cho xác suất loại âm thanh, không phải tên SFX chắc chắn.
- BPM của librosa là BPM ước tính trên soundtrack trộn, không mặc định là BPM của BGM.
- Tên bài nhạc chỉ ghi khi metadata/public evidence/fingerprint xác minh được; nếu không là `UNKNOWN`.
- Transcript không chứng minh visual; frame không chứng minh audio.
- Một video không chứng minh quy luật thuật toán hay retention.

## QA visual đầu tiên

Video: Tabi Tuấn Anh — `ej0mSE14enA`.
Run visual: `41403501097`.

Kết quả:
- MP4 1080×1920, ~24.64s.
- 12/12 frame + contact sheet PASS.
- Artifact tải và mở xem thành công.
- Video nguồn không nằm trong artifact.

## Request files

- `request.json`: FAST visual pipeline.
- `deep_request.json`: DEEP editor pipeline.
- `run:false`: hàng đợi ở trạng thái nghỉ; không xử lý media.
