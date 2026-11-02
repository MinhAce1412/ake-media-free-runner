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
- **PySceneDetect**: tìm ranh giới hình/cảnh nghi ngờ. Không mặc định đó là editor cut vì gameplay/UI cũng có thể kích hoạt detector.
- **OpenCV**: motion spike, freeze/zoom candidate và các thay đổi hình theo thời gian.
- **Tesseract vie+eng**: OCR chữ/caption/overlay ở frame mẫu.
- **faster-whisper CPU INT8**: transcript có timestamp, chạy cả VAD và no-VAD rồi qua bộ chống nghe nhầm.
- **ASR hallucination guard**: đối chiếu độ phủ transcript với tín hiệu speech/music độc lập; nếu ASR nghe ra lời dài trong đoạn chủ yếu là nhạc thì quay về bản VAD thận trọng hơn.
- **librosa**: onset, silence, thay đổi năng lượng và BPM ước tính của soundtrack trộn.
- **YAMNet / AudioSet 521 classes**: speech/music và audio-event candidate.
- **CLAP zero-shot**: chỉ kiểm tra các cửa sổ nghi ngờ quanh boundary/energy spike với nhãn như whoosh, impact, pop, chime, game audio…; output vẫn chỉ là candidate, không phải tên SFX chắc chắn.
- **ShazamIO best-effort**: thử nhận diện track; không match thì tên nhạc bắt buộc `UNKNOWN`.
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
- `MULTIMODAL_MACHINE_EVIDENCE_READY`: máy đã đo temporal visual + OCR + guarded ASR + audio/music/SFX candidates.
- `FULL_EDITOR_REVIEW`: chỉ được gắn sau khi Ake thực sự mở visual proof, đối chiếu audio/transcript và giải thích mỗi điểm quan trọng theo **WHAT → WHY HERE → tác dụng với người xem/câu chuyện → KEEP/ADAPT/SKIP cho Minh → mức chắc**.

## Luật chống bịa

- Scene detector/zoom detector/audio classifier là bằng chứng máy, không tự động biến thành kết luận editor.
- Zoom/freeze từ OpenCV chỉ là **candidate** cho tới khi xem sequence xung quanh.
- YAMNet/CLAP cho candidate loại âm thanh, không phải tên SFX/sample chắc chắn.
- BPM của librosa là BPM ước tính trên soundtrack trộn, không mặc định là BPM của BGM.
- Tên bài nhạc chỉ ghi khi metadata/public evidence/fingerprint xác minh được; nếu không là `UNKNOWN`.
- Transcript phải qua hallucination guard trước khi dùng; proper noun vẫn phải thận trọng.
- Transcript không chứng minh visual; frame không chứng minh audio.
- Một video không chứng minh quy luật thuật toán hay retention.

## QA đã chạy thật

### Tabi Tuấn Anh — `ej0mSE14enA`
- Run visual: `41403501097`.
- MP4 1080×1920, ~24.64s.
- 12/12 frame + contact sheet PASS.
- Artifact tải và mở xem thành công.
- Đã tạo FULL_EDITOR_REVIEW historical-format reference.

### Vodka Quang — `44pw-c1jXjQ`
- Final DEEP run: `41411472832`.
- Artifact: `13124944734`.
- Duration ~31.37s.
- Dense timeline + visual boundaries + OCR + guarded ASR + YAMNet + mixed-audio dynamics + CLAP + ShazamIO đều chạy.
- Hallucination guard đã phát hiện và loại một transcript no-VAD dài giả vì audio độc lập cho thấy music mạnh ~92.3% còn speech rõ chỉ ~7.7%.
- CLAP test 12 cửa sổ; chỉ nhận một candidate game-audio quanh ~5.5s. Reveal ~15s không đủ bằng chứng để gọi whoosh/impact/pop nên giữ `UNKNOWN`.
- ShazamIO không match track, vì vậy tên nhạc = `UNKNOWN`.
- Visual timeline đã được mở kiểm tra và kết quả đã ghi vào `editor_analysis` dưới `FULL_EDITOR_REVIEW`.

## Request files

- `request.json`: FAST visual pipeline.
- `deep_request.json`: DEEP editor pipeline.
- `run:false`: hàng đợi ở trạng thái nghỉ; không xử lý media.
