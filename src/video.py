"""Build a 9:16 short video: edge-tts narration over the rendered slide cards."""
import asyncio
import subprocess
from pathlib import Path
from PIL import Image
from utils import load_config, load_json, save_json, MEDIA, ROOT


async def tts(text: str, voice: str, out: Path):
    import edge_tts
    await edge_tts.Communicate(text, voice).save(str(out))


def audio_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    return float(r.stdout.strip())


def to_vertical(src: Path, dst: Path, size):
    """Letterbox a carousel card onto a 9:16 canvas."""
    w, h = size
    img = Image.open(src).convert("RGB")
    img.thumbnail((w, h))
    canvas = Image.new("RGB", (w, h), "#0E1116")
    canvas.paste(img, ((w - img.width) // 2, (h - img.height) // 2))
    canvas.save(dst)


def build_video(draft, cfg) -> str:
    out_dir = MEDIA / draft["draft_id"]
    voice = cfg["visuals"]["tts_voice"]
    audio = out_dir / "narration.mp3"
    asyncio.run(tts(draft["content"]["video_script"], voice, audio))
    dur = audio_duration(audio)

    frames = []
    for i, rel in enumerate(draft["media"]["slides"]):
        dst = out_dir / f"frame_{i:02d}.png"
        to_vertical(ROOT / rel, dst, cfg["visuals"]["video_size"])
        frames.append(dst)
    per = dur / len(frames)

    # concat via ffmpeg (lighter than moviepy in CI)
    listing = out_dir / "frames.txt"
    listing.write_text(
        "".join(f"file '{f.name}'\nduration {per:.2f}\n" for f in frames)
        + f"file '{frames[-1].name}'\n"
    )
    out = out_dir / "video.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listing.name,
         "-i", audio.name, "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-r", "30", "-c:a", "aac", "-shortest", out.name],
        cwd=out_dir, check=True, capture_output=True,
    )
    return str(out.relative_to(ROOT))


def main():
    cfg = load_config()
    drafts = load_json("drafts.json", [])
    for d in drafts:
        if d["status"] != "pending_video":
            continue
        try:
            d["media"]["video"] = build_video(d, cfg)
            print(f"Video built for {d['draft_id']}")
        except Exception as e:
            print(f"Video failed for {d['draft_id']} ({e}); falling back to carousel")
            d["content"]["format"] = "carousel"
        d["status"] = "pending_review"
    save_json("drafts.json", drafts)


if __name__ == "__main__":
    main()
