import tempfile
import shutil
import subprocess
import streamlit as st
from streamlit.elements import image as st_image
from streamlit.elements.lib.image_utils import image_to_url as streamlit_image_to_url
from streamlit.elements.lib.layout_utils import LayoutConfig
from ultralytics import YOLO
from ultralytics.utils.plotting import Annotator, colors
from PIL import Image, ImageFilter
import os
import cv2
from pillow_heif import register_heif_opener

try:
    from streamlit_drawable_canvas import st_canvas
except ImportError:
    st_canvas = None

if not hasattr(st_image, "image_to_url"):

    def image_to_url_compat(image, width, clamp, channels, output_format, image_id):
        return streamlit_image_to_url(
            image,
            LayoutConfig(width=width),
            clamp,
            channels,
            output_format,
            image_id,
        )

    st_image.image_to_url = image_to_url_compat

import utils
from admin import admin_panel
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Enable support for HEIC images
register_heif_opener()

# Set theme and page layout
utils.set_page_configs()

# Directory to save uploaded images
media_dir_root = "uploaded_media"
image_dir = f"{media_dir_root}/images"
video_dir = f"{media_dir_root}/videos"

# Make sure the dirs exist
os.makedirs(image_dir, exist_ok=True)
os.makedirs(video_dir, exist_ok=True)


@st.cache_resource(ttl=24 * 3600)  # Cache models to save on resources
def load_models():
    classification_model = YOLO("models/classification_model.pt")
    segmentation_model = YOLO("models/segmentation_model.pt")
    return classification_model, segmentation_model


classification_model, segmentation_model = load_models()

# Session state to track image navigation
if "image_index" not in st.session_state:
    st.session_state.image_index = 0

# Initialize saved_image_paths in session state if it doesn't exist
if "saved_image_paths" not in st.session_state:
    st.session_state.saved_image_paths = []

# Init session state for caching results
if "results_cache" not in st.session_state:
    st.session_state.results_cache = {}

# Toggle between image and video mode
on = st.toggle("Video mode")

st.info(
    "メディア内の露骨な領域を分類、検出、セグメント化します。"
    "画像または動画をアップロードしてください。"
    "センシティブな領域のぼかし強度は、対象が検出された後にスライダーで調整できます。"
)

CLASS_NAME_JA = {
    "breast": "乳房",
    "anus": "肛門",
    "female_genital": "女性器",
    "male_genital": "男性器",
    "background": "背景",
}


def build_class_option_map(names_obj):
    if isinstance(names_obj, dict):
        class_names = [names_obj[k] for k in sorted(names_obj.keys())]
    else:
        class_names = list(names_obj)

    option_map = {}
    for class_name in class_names:
        ja_name = CLASS_NAME_JA.get(class_name)
        option_label = f"{ja_name} ({class_name})" if ja_name else class_name
        option_map[option_label] = class_name

    return option_map


def classify_image(image):
    results = classification_model(image, verbose=True)
    category = results[0].names[results[0].probs.top1]
    return category


def segment_image(image):
    results = segmentation_model(
        image, agnostic_nms=True, retina_masks=True, verbose=True
    )
    return results


def apply_effect_to_image_region(
    image, box, effect_strength, effect_type, mosaic_pixel_size
):
    left, top, right, bottom = (int(value) for value in box)
    region = image.crop((left, top, right, bottom))
    if effect_type == "AV風モザイク":
        region_width = max(1, right - left)
        region_height = max(1, bottom - top)
        block_w = max(1, mosaic_pixel_size)
        block_h = max(1, int(mosaic_pixel_size * 0.8))
        mosaic_size = (
            max(1, region_width // block_w),
            max(1, region_height // block_h),
        )
        masked_region = region.resize(
            mosaic_size, resample=Image.Resampling.BILINEAR
        ).resize(
            (region_width, region_height),
            resample=Image.Resampling.NEAREST,
        )
    else:
        masked_region = region.filter(ImageFilter.GaussianBlur(radius=effect_strength))

    if masked_region.mode == "RGBA":
        masked_region = masked_region.convert("RGB")

    image.paste(masked_region, (left, top))


def create_video_writer(fps, frame_size):
    safe_fps = fps if fps and fps > 0 else 30
    codec_candidates = [
        {
            "key": "mp4v",
            "label": "MPEG-4 (mp4v / .mp4)",
            "suffix": ".mp4",
            "mime": "video/mp4",
        },
    ]

    for candidate in codec_candidates:
        suffix = candidate["suffix"]
        codec = candidate["key"]
        mime_type = candidate["mime"]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            output_path = temp_file.name

        writer = cv2.VideoWriter(
            output_path, cv2.VideoWriter_fourcc(*codec), safe_fps, frame_size
        )
        if writer.isOpened():
            return writer, codec, output_path, mime_type
        writer.release()
        if os.path.exists(output_path):
            os.unlink(output_path)

    return None, None, None, None


def transcode_video_for_streamlit(input_path, audio_source_path=None):
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin is None:
        return input_path, "ffmpeg is not available; skipping transcode."

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_file:
        transcoded_path = temp_file.name

    command = [ffmpeg_bin, "-y", "-i", input_path]
    if audio_source_path:
        command.extend(
            [
                "-i",
                audio_source_path,
                "-map",
                "0:v:0",
                "-map",
                "1:a?",
            ]
        )

    command.extend(
        [
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
        ]
    )
    if audio_source_path:
        command.extend(["-c:a", "aac", "-b:a", "192k", "-shortest"])
    else:
        command.append("-an")
    command.append(transcoded_path)

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        if os.path.exists(transcoded_path):
            os.unlink(transcoded_path)
        return input_path, "ffmpeg transcode failed; using original encoded preview."

    if not os.path.exists(transcoded_path) or os.path.getsize(transcoded_path) == 0:
        if os.path.exists(transcoded_path):
            os.unlink(transcoded_path)
        return input_path, "ffmpeg output is empty; using original encoded preview."

    return transcoded_path, None


def apply_effect_to_video_region(
    frame, box, effect_strength, effect_type, mosaic_pixel_size
):
    left, top, right, bottom = (int(value) for value in box)
    region = frame[top:bottom, left:right]
    if region.size == 0:
        return

    if effect_type == "AV風モザイク":
        region_height, region_width = region.shape[:2]
        block_w = max(1, mosaic_pixel_size)
        block_h = max(1, int(mosaic_pixel_size * 0.8))
        mosaic_size = (
            max(1, region_width // block_w),
            max(1, region_height // block_h),
        )
        reduced = cv2.resize(region, mosaic_size, interpolation=cv2.INTER_LINEAR)
        masked_region = cv2.resize(
            reduced, (region_width, region_height), interpolation=cv2.INTER_NEAREST
        )
    else:
        kernel_size = max(1, effect_strength)
        if kernel_size % 2 == 0:
            kernel_size += 1
        masked_region = cv2.GaussianBlur(region, (kernel_size, kernel_size), 0)

    frame[top:bottom, left:right] = masked_region


if on:
    st.write("Model will segment explicit regions in videos.")
    uploaded_file = st.file_uploader(
        "📁 Choose a video...",
        type=[
            "asf",
            "avi",
            "gif",
            "m4v",
            "mkv",
            "mov",
            "mp4",
            "mpeg",
            "mpg",
            "ts",
            "wmv",
            "webm",
        ],
    )

    if uploaded_file is not None:
        uploaded_video_bytes = uploaded_file.getvalue()

        # Save uploaded video to local disk
        file_path = os.path.join(video_dir, uploaded_file.name)
        with open(file_path, "wb") as f:
            f.write(uploaded_video_bytes)

        # Open the video file
        cap = cv2.VideoCapture(file_path)
        assert cap.isOpened(), "Error reading video file"
        w, h, fps = (
            int(cap.get(x))
            for x in (
                cv2.CAP_PROP_FRAME_WIDTH,
                cv2.CAP_PROP_FRAME_HEIGHT,
                cv2.CAP_PROP_FPS,
            )
        )

        # Video writer
        video_writer, selected_codec, temp_video_path, output_mime_type = (
            create_video_writer(fps, (w, h))
        )
        if video_writer is None:
            cap.release()
            st.error(
                "動画を書き出せませんでした。コーデック候補を1つ以上選択し、ブラウザ再生に対応する codec/container を指定してください。"
            )
            st.stop()
        output_suffix = os.path.splitext(temp_video_path)[1].lower()
        st.caption(
            f"書き出し codec: {selected_codec} ({output_suffix}, {output_mime_type})"
        )

        # Process video frame-by-frame
        progress_bar = st.progress(0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        current_frame = 0

        effect_type = st.selectbox(
            "マスクの種類", ["ぼかし", "AV風モザイク"], key="video_effect_type"
        )
        if effect_type == "AV風モザイク":
            av_mosaic_preset = st.selectbox(
                "AV風モザイクプリセット",
                ["弱", "中", "強", "カスタム"],
                index=1,
                key="video_mosaic_preset",
            )
            preset_pixel_size = {"弱": 16, "中": 24, "強": 36}

            if av_mosaic_preset == "カスタム":
                mosaic_pixel_size = st.slider(
                    "AV風モザイクのピクセルサイズ",
                    min_value=8,
                    max_value=96,
                    value=24,
                    key="video_mosaic_pixel_size",
                )
            else:
                mosaic_pixel_size = preset_pixel_size[av_mosaic_preset]
                st.caption(
                    f"現在のピクセルサイズ: {mosaic_pixel_size} ({av_mosaic_preset} プリセット)"
                )
        else:
            mosaic_pixel_size = 16

        effect_strength = st.slider(
            "マスク強度",
            min_value=1,
            max_value=100,
            value=85,
            key="video_effect_strength",
        )

        apply_mask_video = st.checkbox("マスク処理を適用", True, key="video_apply_mask")
        hold_frames = st.slider(
            "判定ロスト時の保持フレーム",
            min_value=0,
            max_value=300,
            value=12,
            key="video_hold_frames",
        )

        use_auto_boxes_video = st.checkbox(
            "自動検出範囲を使用", True, key="video_use_auto_boxes"
        )
        video_class_option_map = build_class_option_map(segmentation_model.model.names)
        video_class_options = list(video_class_option_map.keys())
        selected_video_options = st.multiselect(
            "自動検出対象（複数選択）",
            options=video_class_options,
            default=video_class_options,
            key="video_selected_classes",
            disabled=not use_auto_boxes_video,
        )
        selected_video_class_names = {
            video_class_option_map[option] for option in selected_video_options
        }

        last_detected_detections = []
        detect_hold_remaining = 0

        while cap.isOpened():
            success, im0 = cap.read()
            if not success:
                break

            if not apply_mask_video:
                video_writer.write(im0)
                current_frame += 1
                safe_total_frames = max(frame_count, 1)
                progress_bar.progress(current_frame / safe_total_frames)
                continue

            # Perform segmentation on the frame
            results = segmentation_model.predict(
                im0,
                imgsz=416,
                show=False,
                agnostic_nms=True,
                device="cpu",
                verbose=False,
            )
            boxes = results[0].boxes.xyxy.cpu().tolist()
            clss = results[0].boxes.cls.cpu().tolist()
            if apply_mask_video and use_auto_boxes_video and boxes is not None:
                active_detections = list(zip(boxes, clss))
                if active_detections:
                    last_detected_detections = active_detections
                    detect_hold_remaining = hold_frames
                elif detect_hold_remaining > 0 and last_detected_detections:
                    active_detections = last_detected_detections
                    detect_hold_remaining -= 1
                else:
                    active_detections = []

                for box, cls in active_detections:
                    class_name = segmentation_model.model.names[int(cls)]
                    if class_name not in selected_video_class_names:
                        continue
                    apply_effect_to_video_region(
                        im0, box, effect_strength, effect_type, mosaic_pixel_size
                    )

            # Write the processed frame to the output video
            video_writer.write(im0)

            # Update progress bar
            current_frame += 1
            safe_total_frames = max(frame_count, 1)
            progress_bar.progress(current_frame / safe_total_frames)

        # Release video objects
        cap.release()
        video_writer.release()

        # Display the processed video
        if current_frame == 0 or not os.path.exists(temp_video_path):
            st.error(
                "処理後の動画を生成できませんでした。入力動画の形式を確認してください。"
            )
        elif os.path.getsize(temp_video_path) == 0:
            st.error("処理後の動画ファイルが空です。codec 設定を見直してください。")
        else:
            preview_video_path = temp_video_path
            preview_mime_type = output_mime_type
            transcoded_preview_path, transcode_note = transcode_video_for_streamlit(
                temp_video_path,
                audio_source_path=file_path,
            )
            if transcode_note:
                st.caption(transcode_note)
            elif transcoded_preview_path != temp_video_path:
                preview_video_path = transcoded_preview_path
                preview_mime_type = "video/mp4"
                st.caption("プレビュー互換化: ffmpeg (libx264)")

            st.success("Video processing complete!")
            print("[DEBUG] Video processing  completed.")
            col_original_video, col_processed_video = st.columns(2)
            with open(preview_video_path, "rb") as vf:
                video_bytes = vf.read()

            if not video_bytes:
                st.error("処理後動画の読み込みに失敗しました。")
            else:
                with col_original_video:
                    uploaded_mime_type = uploaded_file.type or "video/mp4"
                    st.video(uploaded_video_bytes, format=uploaded_mime_type)
                    st.caption("元動画")

                with col_processed_video:
                    st.video(video_bytes, format=preview_mime_type)
                    preview_caption = (
                        "プレビュー動画（マスク適用後）"
                        if apply_mask_video
                        else "プレビュー動画（マスク未適用）"
                    )
                    st.caption(preview_caption)

            if preview_video_path != temp_video_path and os.path.exists(
                preview_video_path
            ):
                os.unlink(preview_video_path)

        # Clean up temporary file
        if os.path.exists(temp_video_path):
            os.unlink(temp_video_path)

else:
    st.write("Models will classify and segment explicit regions in images.")
    uploaded_files = st.file_uploader(
        "📁 Choose an image...",
        type=[
            "bmp",
            "dng",
            "jpg",
            "jpeg",
            "mpo",
            "png",
            "tif",
            "tiff",
            "webp",
            "pfm",
            "HEIC",
        ],
        accept_multiple_files=True,
    )

    if uploaded_files:
        current_uploaded_files = {file.name for file in uploaded_files}

        # Update saved_image_paths to remove deleted files
        st.session_state.saved_image_paths = [
            path
            for path in st.session_state.saved_image_paths
            if os.path.basename(path) in current_uploaded_files
        ]

        # Add new files to saved_image_paths
        for uploaded_file in uploaded_files:
            file_path = os.path.join(image_dir, uploaded_file.name)
            if file_path not in st.session_state.saved_image_paths:  # Avoid duplicates
                with open(file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                st.session_state.saved_image_paths.append(file_path)

        # Handle invalid image_index
        if st.session_state.image_index >= len(st.session_state.saved_image_paths):
            st.session_state.image_index = max(
                0, len(st.session_state.saved_image_paths) - 1
            )

        # Load the current image based on image_index
        if st.session_state.saved_image_paths:
            current_image_path = st.session_state.saved_image_paths[
                st.session_state.image_index
            ]
            image = Image.open(current_image_path)
            _, cent_co, _ = st.columns(3)
            with cent_co:
                st.image(
                    image,
                    caption=f"Image {st.session_state.image_index + 1} of {len(st.session_state.saved_image_paths)}",
                    width="stretch",
                )

            col1, _, col3 = st.columns([1, 10, 1])

            with col1:
                if st.button("Previous") and st.session_state.image_index > 0:
                    st.session_state.image_index -= 1
                    _ = """
                            Force re-run the script as streamlit's UI re-rendering on session state change is slightly buggy.
                            This fixes the issue where the user to has to click "Previous" button twice on the last image
                            to cycle through the classification and segmentation results respectively.
                        """
                    st.rerun()
            with col3:
                if (
                    st.button("Next")
                    and st.session_state.image_index
                    < len(st.session_state.saved_image_paths) - 1
                ):
                    st.session_state.image_index += 1
                    _ = """
                            Force re-run the script as streamlit's UI re-rendering on session state change is slightly buggy.
                            This fixes the issue where the user to has to click "Next" button twice on the first image
                            to cycle through the classification and segmentation results respectively.
                        """
                    st.rerun()

            # Display cached results if present
            if current_image_path in st.session_state.results_cache:
                cached_results = st.session_state.results_cache[current_image_path]
                category = cached_results["category"]
                st.success(f"**Classification Result:** {category}")
                print(f"Using cached results for {current_image_path}")
            else:
                with st.spinner("Classifying image..."):
                    print(f"No cached results found for {current_image_path}")
                    with ThreadPoolExecutor() as executor:
                        future = executor.submit(classify_image, image)
                        category = future.result()
                        st.success(f"**Classification Result:** {category}")

                    print(
                        f"[INFO] Inference information about file: {current_image_path}"
                    )

            _ = """ 
                Do not cache segmentation results, it borks website
                Pass to segmentation model only if images need blur, otherwise skip
            """

            if category == "porn" or category == "hentai":
                with st.spinner("Detecting explicit regions..."):
                    segmentation_results = []
                    with ThreadPoolExecutor() as executor:
                        future = executor.submit(segment_image, image)
                        segmentation_results = future.result()

                boxes = segmentation_results[0].boxes.xyxy.cpu().tolist()
                clss = segmentation_results[0].boxes.cls.cpu().tolist()
                confs = segmentation_results[0].boxes.conf.cpu().tolist()

                _ = """
                    Copy of the image for drawing segmentation masks.
                    Prevents segmentation mask's color from being picked up during the blurring process, results in a clean blur.
                """
                image_with_blur = image.copy()
                image_with_boxes = image.copy()

                annotator = Annotator(
                    image_with_boxes,
                    line_width=2,
                    example=segmentation_results[0].names,
                )

                for box, cls, conf in zip(boxes, clss, confs):
                    class_name = segmentation_results[0].names[int(cls)]
                    label = f"{class_name} ({conf:.2f})"
                    annotator.box_label(box, color=colors(int(cls), True), label=label)

                effect_type = st.selectbox(
                    "マスクの種類", ["ぼかし", "AV風モザイク"], key="image_effect_type"
                )
                if effect_type == "AV風モザイク":
                    av_mosaic_preset = st.selectbox(
                        "AV風モザイクプリセット",
                        ["弱", "中", "強", "カスタム"],
                        index=1,
                        key="image_mosaic_preset",
                    )
                    preset_pixel_size = {"弱": 16, "中": 24, "強": 36}

                    if av_mosaic_preset == "カスタム":
                        mosaic_pixel_size = st.slider(
                            "AV風モザイクのピクセルサイズ",
                            min_value=8,
                            max_value=96,
                            value=24,
                            key="image_mosaic_pixel_size",
                        )
                    else:
                        mosaic_pixel_size = preset_pixel_size[av_mosaic_preset]
                        st.caption(
                            f"現在のピクセルサイズ: {mosaic_pixel_size} ({av_mosaic_preset} プリセット)"
                        )
                else:
                    mosaic_pixel_size = 16

                effect_strength = st.slider(
                    "マスク強度",
                    min_value=1,
                    max_value=100,
                    value=85,
                    key="image_effect_strength",
                )

                use_auto_boxes = st.checkbox(
                    "自動検出範囲を使用", True, key="image_use_auto_boxes"
                )
                image_class_option_map = build_class_option_map(
                    segmentation_results[0].names
                )
                image_class_options = list(image_class_option_map.keys())
                selected_image_options = st.multiselect(
                    "自動検出対象（複数選択）",
                    options=image_class_options,
                    default=image_class_options,
                    key="image_selected_classes",
                    disabled=not use_auto_boxes,
                )
                selected_image_class_names = {
                    image_class_option_map[option] for option in selected_image_options
                }
                use_manual_box = st.checkbox(
                    "手動で範囲を指定", False, key="image_use_manual_box"
                )

                target_boxes = []
                if use_auto_boxes:
                    for box, cls in zip(boxes, clss):
                        class_name = segmentation_results[0].names[int(cls)]
                        if class_name in selected_image_class_names:
                            target_boxes.append(box)

                if use_manual_box:
                    st.caption(
                        "ドラッグで矩形を描画してマスク範囲を選択してください。複数選択も可能です。"
                    )
                    if st_canvas is None:
                        st.error(
                            "ドラッグ選択には streamlit-drawable-canvas が必要です。requirements をインストールしてください。"
                        )
                    else:
                        canvas_result = st_canvas(
                            fill_color="rgba(255, 75, 75, 0.25)",
                            stroke_width=2,
                            stroke_color="#FF4B4B",
                            background_image=image,
                            update_streamlit=True,
                            height=image.height,
                            width=image.width,
                            drawing_mode="rect",
                            key=f"image_manual_canvas_{st.session_state.image_index}",
                        )

                        if (
                            canvas_result.json_data
                            and "objects" in canvas_result.json_data
                        ):
                            for obj in canvas_result.json_data["objects"]:
                                if obj.get("type") != "rect":
                                    continue

                                left = int(obj.get("left", 0))
                                top = int(obj.get("top", 0))
                                width = int(obj.get("width", 0) * obj.get("scaleX", 1))
                                height = int(
                                    obj.get("height", 0) * obj.get("scaleY", 1)
                                )

                                right = min(image.width, left + max(1, width))
                                bottom = min(image.height, top + max(1, height))
                                left = max(0, left)
                                top = max(0, top)

                                manual_box = [left, top, right, bottom]
                                annotator.box_label(
                                    manual_box, color=colors(0, True), label="manual"
                                )
                                target_boxes.append(manual_box)

                # Apply selected effect to explicit regions
                for box in target_boxes:
                    apply_effect_to_image_region(
                        image_with_blur,
                        box,
                        effect_strength,
                        effect_type,
                        mosaic_pixel_size,
                    )

                if not target_boxes:
                    st.warning(
                        "マスク対象がありません。自動検出範囲または手動範囲を有効化してください。"
                    )

                blur_sensitive_regions = st.checkbox("マスク処理を適用", True)
                col_original, col_preview = st.columns(2)
                if blur_sensitive_regions:
                    preview_image = image_with_blur
                    preview_caption = "プレビュー画像（マスク適用）"
                else:
                    preview_image = image_with_boxes
                    preview_caption = "プレビュー画像（セグメンテーション）"

                with col_original:
                    st.image(image, caption="元画像", width="stretch")

                with col_preview:
                    st.image(preview_image, caption=preview_caption, width="stretch")
        else:
            st.warning("No images to display.")

st.markdown("---")

# Call the admin panel
asyncio.run(admin_panel())

# A small button to link to the Github repo
st.write("---")
st.markdown(
    "ℹ️ Please note that I collect uploaded images and videos to re-train my models. However, the user remains anonymous."
)
st.link_button(
    "🐙 View on GitHub", "https://github.com/Forenche/nsfw_detector_annotator"
)
