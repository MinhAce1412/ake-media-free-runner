# Ake Media Free Runner

## Ake Zero-Cost Discovery (13/11/2026)

- GitHub Actions `ake-discovery.yml`: chạy 11:23 Asia/Ho_Chi_Minh hằng ngày (04:23 UTC) bằng standard `ubuntu-latest` trên public repo; tối đa **1 video FAST/ngày**, không tự chạy DEEP.
- `config/ake_youtube_sources.json`: 7 nguồn YouTube công khai đã có trong Ake DB; RSS chỉ gồm video gần đây, không đại diện toàn bộ thị trường FC Online/TikTok.
- `scripts/ake_discover.py`: đọc RSS, kiểm identity nguồn, chống trùng **exact video ID** (không loại bỏ cả creator), giữ danh sách vào `data/ake_discovery_state.json`. Cập nhật source_health nội bộ nếu có quyền ghi.
- Trạng thái: `DISCOVERED_METADATA_ONLY` / `PENDING` -> `FAST_EVIDENCE_READY` chỉ khi thực sự có 12 frames và contact sheet; `SOURCE_BLOCKED` hoặc `LONGFORM_PENDING_INDEX` nếu không đủ điều kiện. Mặc định `training_status=NOT_APPROVED`.
- File nguồn video không được commit vào repo; FAST artifacts chỉ lưu 1 ngày. Nếu YouTube chặn nguồn public, không dùng cookie, CAPTCHA bypass hoặc API mất phí.
- ChatGPT Ake Content Learner được hướng dẫn đọc file này và xác minh read-back vào Google Sheet `AKE_CREATOR_INTELLIGENCE_DB`; GitHub hoàn tất hoặc có metadata không đồng nghĩa đã học được video. `MINH 30M SYSTEM` là đường ghi đề xuất chỉ khi có bằng chứng và cần được xác minh đọc lại.
- Giữ nguyên Site, URL, dữ liệu Owner; không tự đăng mạng xã hội, không thay đổi lịch 5 tác vụ Ake.

Runner miễn phí để Ake **xem, nghe và phân tích** video public phục vụ nghiên cứu content/đối thủ. Repo chỉ chứa code và evidence phân tích; không dùng để reupload nội dung.

## Ba tầng

### FAST — sàng lọc
- Metadata/public metrics.
- 12 frame + contact sheet khi cần xác minh hình.
- Dùng để chọn video nào đáng tốn công phân tích sâu.

### LONGFORM INDEX — quét toàn VOD/livestream
Dùng trước DEEP cho video dài.
- Quét toàn duration bằng frame sampling thưa, OCR context, visual-change và audio-energy signals.
- Dùng non-maximum suppression + time buckets để tạo **nhiều candidate windows tách biệt**, tránh peak dày kéo dính cả VOD.
- Xuất whole-timeline contact sheet + `candidate_windows.json`.
- Đây chỉ là **discovery evidence**: không tự gán content type/story/clip quality.
- Selected windows vẫn phải chạy DEEP multimodal trước khi `TRAINING_APPROVED` hoặc đưa clip recommendation cuối.

### DEEP — mổ xẻ như editor
Chỉ chạy cho video/cửa sổ đáng học hoặc content Minh sắp áp dụng.

Pipeline DEEP hiện gồm:
- **PySceneDetect**: tìm ranh giới hình/cảnh nghi ngờ; không mặc định là editor cut.
- **OpenCV**: motion spike, freeze/zoom candidate và thay đổi hình theo thời gian.
- **Tesseract vie+eng**: OCR chữ/caption/overlay.
- **faster-whisper CPU INT8**: transcript timestamp, VAD + no-VAD và hallucination guard.
- **ASR hallucination guard**: đối chiếu transcript với speech/music độc lập.
- **librosa**: onset, silence, energy và BPM ước tính của soundtrack trộn.
- **YAMNet / AudioSet**: speech/music/audio-event candidate.
- **CLAP zero-shot**: kiểm tra SFX semantic candidate quanh các mốc nghi ngờ; không tự biến thành exact SFX proof.
- **ShazamIO best-effort**: thử nhận diện track; không match/corroborate thì `UNKNOWN`.
- **FFmpeg/FFprobe**: decode, audio extraction, codec/duration.

Một DEEP job phân tích tối đa 180 giây. Video dài dùng `LONGFORM INDEX -> chọn window -> DEEP`, thay vì cố mổ nhiều giờ trong một job.

## Cách lấy video
1. URL public.
2. Thử public route trực tiếp.
3. Nếu GitHub bị YouTube anti-bot/login, **không dùng cookie/tài khoản/CAPTCHA bypass**.
4. Khi khả dụng dùng `vidIQ video_upload` **0 credit** làm cầu MP4 tạm.
5. Source media là transient và bị xóa trước artifact upload.

## Mức bằng chứng
- `METADATA_ONLY`
- `TRANSCRIPT_L2`
- `MEDIA_FILE_READY_UNINSPECTED`
- `VISUAL_FRAMES_READY`
- `VISUAL_REVIEW`
- `LONGFORM_INDEX_EVIDENCE_READY`: toàn VOD đã được index nhưng chưa được phép gán semantic content.
- `MULTIMODAL_MACHINE_EVIDENCE_READY`
- `FULL_EDITOR_REVIEW`: Ake đã mở visual proof, đối chiếu audio/transcript và giải thích **WHAT → WHY HERE → viewer/story effect → KEEP/ADAPT/SKIP → confidence**.

## Luật chống bịa
- Detector/classifier là machine evidence, không tự động thành kết luận editor.
- Longform peaks/OCR chỉ chọn nơi cần xem sâu, không phải content truth.
- Machine scene boundary không mặc định là cut.
- Zoom/freeze chỉ là candidate cho tới khi xem sequence.
- YAMNet/CLAP không chứng minh exact SFX/sample.
- BPM là mixed-audio estimate nếu chưa tách/verify BGM.
- Tên track không có independent match thì `UNKNOWN`.
- Transcript phải qua hallucination guard; proper noun vẫn thận trọng.
- Transcript không chứng minh visual; frame không chứng minh audio.
- Một video không chứng minh rule/retention/causality.

## QA đã chạy thật

### Tabi Tuấn Anh — `ej0mSE14enA`
- Run visual `41403501097`, ~24.64s, 12/12 frame + contact sheet PASS.
- FULL_EDITOR_REVIEW historical-format reference.

### Vodka Quang — `44pw-c1jXjQ`
- DEEP run `41411472832`, artifact `13124944734`, ~31.37s.
- Dense visual + OCR + guarded ASR + audio dynamics + CLAP + ShazamIO PASS.
- Hallucination ASR đã bị guard loại; exact reveal SFX/track giữ `UNKNOWN` khi thiếu bằng chứng.

### Pwen TikTok — `7671984934738791701`
- DEEP run `41429856497`, artifact `13134326735`, ~42.05s.
- TikTok public direct acquisition PASS, không cookie/login.
- Guarded ASR: vi ~0.997, speech coverage ~90.4%; YAMNet speech-dominant; CLAP 0/17 exact-SFX candidate accepted.
- Visual/timeline proof đã mở thật.
- Content được xác nhận multimodal là `EDUCATION / TACTICS / KEYBOARD FORMATION-RANK SETUP`, không dựa title riêng.
- Đã ghi `TRAINING_APPROVED`; claim “Win 90%” chỉ lưu là creator claim, không causal proof.

### Bình Be — whole-VOD 30:29
- Fixed Longform Index run `41431580563`, artifact `13133719357`.
- Duration `1829.338s`, 183 visual samples.
- 16 selected visual peaks + 52 selected audio peaks sau NMS.
- 16 candidate windows riêng biệt + whole-timeline contact sheet PASS.
- Initial chain-clustering bug tạo 1 window quá lớn đã được phát hiện và sửa trước khi đánh dấu READY.
- Index không tự gán semantic content; selected windows phải quay lại DEEP.

## Request files
- `request.json`: FAST visual pipeline.
- `deep_request.json`: DEEP editor pipeline.
- `longform_request.json`: whole-VOD indexing pipeline.
- `run:false`: queue nghỉ, không xử lý media.
