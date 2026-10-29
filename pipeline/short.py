"""Stage 8: a Short a day - three turns of the day's guessing game, standing up.

New children's channels get their first viewers from Shorts, so every video has one: 1080x1920,
30 to 45 seconds, three subjects of the day's video as the game plays them - a piece of the
frame, "Who is this?", 3-2-1, the reveal, the name and the real sound - then a line sending the
child to the full video. Made for kids, like every upload on this channel.

Nothing new is drawn or generated. The clips, the sounds, the questions and the answers were all
made for the long video; only the closing line is spoken anew, by the same voice. No Cloudflare
neurons. One videos.insert, from the 100-a-day bucket the project's four daily uploads share.

Standing up, the turn is the game's turn re-cut: the frozen frame is a 9:16 slice of the clip
centred on the subject, the riddle a detail of that slice (or the slice blurred, by the same
rule as the game), the reveal the board's eased affine flight pulled back to the slice, and then
the clip plays on through exactly the chain the still came from, so the cut is invisible. The
words a muted viewer needs - the question and the name - are on screen, and kept clear of the
strip at the bottom and the column on the right that the Shorts player covers.
"""
import json
import math
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from core.logger import get_logger
from pipeline import game, grid

log = get_logger("short")

W, H, FPS = 1080, 1920, game.FPS
SRC_W, SRC_H = 1920, 1080
# The picture is 4:5, not the whole 9:16. A 9:16 slice of a landscape clip is a third of its
# width, and the first build cut the wolf in two - its head was a sliver at the edge of the
# reveal. A 4:5 slice takes 45 per cent, the question sits in the band above the picture, and
# the band is the board's own sky.
PIC_W, PIC_H = 1080, 1350
PIC_Y = 300
SLICE_W = 864                       # 1080 * 1080 / 1350: a 4:5 slice of a 1920x1080 frame
TURNS = 3
MIN_SECONDS, MAX_SECONDS = 30.0, 45.0
END_SECONDS = 3.0
QUESTION_Y = 160                    # the centre of the on-screen question, in the band
LABEL_Y = PIC_Y + PIC_H - 190       # the top of the name: on the picture, above the player's strip
DIGIT_Y = PIC_Y + PIC_H // 2
# Less of a close-up than the long video's 2.4: on a phone, at 2.4, the wolf and the lion were
# a patch of fur each - fair, but a riddle a two-year-old cannot start on.
PIECE_ZOOM = 1.9


def vchain(x0):
    """The filter that makes a frame of the clip into the Short's picture - for the still and
    for the playing clip alike, so the two sides of the cut are the same picture."""
    return (f"scale={SRC_W}:{SRC_H}:force_original_aspect_ratio=increase,crop={SRC_W}:{SRC_H},"
            f"eq=saturation=1.30:contrast=1.10,crop={SLICE_W}:{SRC_H}:{x0}:0,"
            f"scale={PIC_W}:{PIC_H}:flags=bicubic")


def slice_left(still):
    """Where the 4:5 slice starts: on the centre of the frame's detail, weighted towards the
    middle - usually the animal against a plainer background. Not on the riddle's piece: the
    piece was a patch of fur, and centring on it put the wolf's head off the edge."""
    import numpy as np
    texture, colour = game._detail_map(still)
    weight = (texture * (0.5 + colour)).sum(axis=0)
    xs = np.arange(len(weight)) / len(weight)
    weight = weight * np.exp(-((xs - 0.5) ** 2) / (2 * 0.3 ** 2))
    centre = float((xs * weight).sum() / max(weight.sum(), 1e-9)) * SRC_W
    return int(min(max(round(centre - SLICE_W / 2), 0), SRC_W - SLICE_W)) // 2 * 2


def vertical_still(source, x0, dst):
    dst = Path(dst)
    if not dst.exists():
        is_image = Path(source).suffix.lower() in game.IMAGE_SUFFIXES
        args = ["ffmpeg", "-y", "-v", "error"]
        args += (["-i", str(source)] if is_image else
                 ["-ss", f"{game.START_IN_CLIP:.3f}", "-i", str(source)])
        subprocess.run(args + ["-vf", vchain(x0), "-frames:v", "1", str(dst)],
                       check=True, capture_output=True, timeout=300)
    return Image.open(dst).convert("RGB")


def piece_in_slice(vstill, zoom=PIECE_ZOOM, floor=game.PIECE_MIN_DETAIL):
    """The riddle's window inside the 4:5 picture - the same shape, 1/zoom of it, favoured
    towards the middle - or None for the blur. The game's measure of detail (texture times
    colour), run on a portrait grid instead of a landscape one."""
    import numpy as np
    small = np.asarray(vstill.convert("RGB").resize((108, 135), Image.BILINEAR),
                       dtype=np.float32) / 255.0
    grads = []
    for c in range(3):
        gy, gx = np.gradient(small[..., c])
        grads.append(np.sqrt(gx ** 2 + gy ** 2))
    texture = np.mean(grads, axis=0)
    hi, lo = small.max(axis=2), small.min(axis=2)
    colour = np.where(hi > 0, (hi - lo) / np.maximum(hi, 1e-6), 0) * hi
    combined = texture * (0.5 + colour)
    h, w = combined.shape
    bw, bh = int(round(w / zoom)), int(round(h / zoom))
    integral = np.pad(combined.cumsum(axis=0).cumsum(axis=1), ((1, 0), (1, 0)))
    best, at = -1.0, None
    for y in range(0, h - bh + 1, 2):
        for x in range(0, w - bw + 1, 2):
            mean = (integral[y + bh, x + bw] - integral[y, x + bw]
                    - integral[y + bh, x] + integral[y, x]) / (bw * bh)
            cx, cy = (x + bw / 2) / w - 0.5, (y + bh / 2) / h - 0.5
            score = mean * (0.4 + 0.6 * math.exp(-(cx ** 2 + cy ** 2) / (2 * 0.24 ** 2)))
            if score > best:
                best, at = score, (x, y)
    if at is None or best < floor:
        return None, round(float(best), 4)
    s = PIC_W / w
    return (at[0] * s, at[1] * s, bw * s, bh * s), round(float(best), 4)


def _affine(img, cx, cy, window):
    s = window / PIC_W
    return img.transform((PIC_W, PIC_H), Image.AFFINE,
                         (s, 0, cx - s * PIC_W / 2, 0, s, cy - s * PIC_H / 2), Image.BICUBIC)


def _scaled(img, scale):
    return game._scaled_about_centre_size(img, scale, PIC_W, PIC_H)


def _banner(text, size=96):
    font = game._font(size)
    probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    box = probe.textbbox((0, 0), text, font=font, stroke_width=12)
    img = Image.new("RGBA", (box[2] - box[0] + 80, box[3] - box[1] + 60), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=40,
                        fill=(255, 92, 170, 235))
    d.text((40 - box[0], 30 - box[1]), text, font=font, fill=(255, 255, 255),
           stroke_width=12, stroke_fill=(22, 28, 70))
    return img


class _Confetti(game.Confetti):
    def draw(self, frame, age):
        # The parent's burst is centred on a 1920x1080 frame; the offsets move it to this one.
        if not 0 <= age < self.life:
            return
        layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        fade = 1.0 if age < self.life * 0.6 else max(0.0, (self.life - age) / (self.life * 0.4))
        for b in self.bits:
            x = W / 2 + b["vx"] * age * 0.7
            y = H * 0.45 + b["vy"] * age + 0.5 * 1800 * age * age
            a = b["turn"] + b["spin"] * age
            cw, sw = math.cos(a), math.sin(a)
            hw, hh = b["w"] / 2, b["h"] / 2
            d.polygon([(x + dx * cw - dy * sw, y + dx * sw + dy * cw)
                       for dx, dy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))],
                      fill=b["colour"] + (int(255 * fade),))
        frame.alpha_composite(layer)


def head_frames(vstill, box, label, question, t, seed, workers=6):
    """Raw frames from the turn's start until the clip starts playing: the sky, the picture
    in the middle, the question in the band above it."""
    full = vstill.convert("RGBA")
    if box:
        x, y, w, h = box
        riddle = vstill.transform((PIC_W, PIC_H), Image.EXTENT, (x, y, x + w, y + h),
                                  Image.BICUBIC)
    else:
        riddle = vstill.filter(ImageFilter.GaussianBlur(game.BLUR_RADIUS))
    riddle = riddle.convert("RGBA")
    badge = game.question_badge(150)
    riddle.alpha_composite(badge, (PIC_W - badge.width - 30, 30))
    asked = _banner(question.upper())
    sky = Image.new("RGBA", (W, H), game.BRAND + (255,))
    confetti = _Confetti(seed)
    move = max(2, int(round(game.REVEAL_MOVE * FPS)))
    flight = (grid.zoom_geometry(box, move, into=False, spin=0.0, width=PIC_W, height=PIC_H)
              if box else None)
    n = int(round(t["frozen_until"] * FPS))

    def frame_at(i):
        now = i / FPS
        img = sky.copy()
        if now < t["riddle"]:
            e = game.ease_in_out(now / t["riddle"])
            pic = _scaled(riddle, 0.92 + 0.08 * e)
            pic.putalpha(pic.getchannel("A").point(lambda v: int(v * e)))
        elif now < t["reveal"]:
            pic = riddle
        else:
            since = now - t["reveal"]
            if box and since < game.REVEAL_MOVE:
                cx, cy, window, _a = flight[min(int(round(since * FPS)), move - 1)]
                pic = _affine(vstill, cx, cy, window).convert("RGBA")
            elif not box and since < 0.35:
                pic = _scaled(full, 1.10 - 0.10 * game.ease_out_cubic(since / 0.35))
            else:
                pic = full
        img.alpha_composite(pic, (0, PIC_Y))
        if t["question"] <= now < t["reveal"]:
            e = game.ease_out_back(min((now - t["question"]) / 0.35, 1.0))
            game._paste_centre(img, asked, 0.4 + 0.6 * e, 1.0, (W / 2, QUESTION_Y))
        if t["countdown"] <= now < t["reveal"]:
            k = int(now - t["countdown"])
            u = (now - t["countdown"]) - k
            if game.COUNT - k >= 1:
                scale = 0.35 + 0.65 * game.ease_out_back(min(u / 0.28, 1.0))
                alpha = 1.0 if u < 0.8 else max(0.0, (1.0 - u) / 0.2)
                game._paste_centre(img, game.digit_image(game.COUNT - k, 360), scale, alpha,
                                   (W / 2, DIGIT_Y))
        if now >= t["reveal"]:
            confetti.draw(img, now - t["reveal"])
            shown = now - t["answer"]
            if shown >= 0:
                e = game.ease_out_cubic(shown / 0.3)
                lab = label.copy()
                lab.putalpha(lab.getchannel("A").point(lambda v: int(v * e)))
                img.alpha_composite(lab, ((W - label.width) // 2,
                                          LABEL_Y + int(round(40 * (1 - e)))))
        return img.convert("RGB").tobytes()

    with ThreadPoolExecutor(workers) as pool:
        for start in range(0, n, workers * 2):
            for data in pool.map(frame_at, range(start, min(n, start + workers * 2))):
                yield data


def encode(frames, out_path, timeout=1800):
    args = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(out_path)]
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=errors)
        try:
            for f in frames:
                proc.stdin.write(f)
        finally:
            proc.stdin.close()
        if proc.wait(timeout=timeout) != 0:
            errors.seek(0)
            raise RuntimeError(errors.read()[-400:].decode("utf-8", "replace"))
    return Path(out_path)


def tail_segment(source, x0, seconds, label_png, dst, timeout=900):
    """The clip playing on from the frozen frame, standing up, with the name, out to the sky."""
    colour = "0x%02X%02X%02X" % game.BRAND
    is_image = Path(source).suffix.lower() in game.IMAGE_SUFFIXES
    head = (["-loop", "1", "-i", str(source)] if is_image else
            ["-stream_loop", "-1", "-ss", f"{game.START_IN_CLIP:.3f}", "-i", str(source)])
    subprocess.run(["ffmpeg", "-y", "-v", "error", *head, "-loop", "1", "-i", str(label_png),
                    "-t", f"{seconds:.4f}", "-filter_complex",
                    f"[0:v]{vchain(x0)},pad={W}:{H}:0:{PIC_Y}:color={colour},fps={FPS}[v];"
                    f"[v][1:v]overlay=(W-w)/2:{LABEL_Y},"
                    f"fade=t=out:st={max(seconds - game.OUT, 0):.4f}:d={game.OUT}:color={colour}[o]",
                    "-map", "[o]", "-an", "-r", str(FPS), "-c:v", "libx264", "-preset",
                    "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(dst)],
                   check=True, capture_output=True, timeout=timeout)
    return Path(dst)


def end_card_frames(theme_words, count, seconds, workers=6):
    """The last three seconds: the sky, and how many more there are in the full video."""
    base = Image.new("RGBA", (W, H), game.BRAND + (255,))
    d = ImageDraw.Draw(base)
    top, bottom = (46, 196, 255), (120, 92, 255)
    for y in range(H):
        k = y / (H - 1)
        d.line([(0, y), (W, y)], fill=tuple(round(a + (b - a) * k) for a, b in zip(top, bottom)) + (255,))
    lines = [_banner(f"{count} {theme_words}", 110), _banner("in the full video!", 84)]
    n = int(round(seconds * FPS))

    def frame_at(i):
        now = i / FPS
        img = base.copy()
        e = game.ease_out_back(min(now / 0.5, 1.0))
        game._paste_centre(img, lines[0], 0.3 + 0.7 * e, 1.0, (W / 2, H * 0.40))
        game._paste_centre(img, lines[1], 0.3 + 0.7 * e, 1.0, (W / 2, H * 0.40 + 190))
        return img.convert("RGB").tobytes()

    with ThreadPoolExecutor(workers) as pool:
        for start in range(0, n, workers * 2):
            for data in pool.map(frame_at, range(start, min(n, start + workers * 2))):
                yield data


# --- which three, and the whole Short ------------------------------------------------------

def choose_turns(cards, video_id, count=TURNS):
    """Three of the game's turns: ones with a real sound first, in the game's own order.

    The sound is the channel's hook - the reason a two-year-old looks up - and a Short of three
    silent turns throws away the one thing this channel has that the others do not.
    """
    ordered = list(enumerate(game.order(cards, video_id)))
    with_sound = [(n, c) for n, c in ordered if c.get("sound_id")]
    rest = [(n, c) for n, c in ordered if not c.get("sound_id")]
    return (with_sound + rest)[:count]


def build(video_id, cfg, db, output_dir):
    """Make short.mp4. Returns a report dict."""
    from core import music as music_lib, tts
    from pipeline import catalogue, narrate, render, thumbnail
    out = Path(output_dir)
    work = out / "short"
    work.mkdir(parents=True, exist_ok=True)
    video = db.get_video(video_id) or {}
    cards = db.get_cards(video_id)
    if len(cards) < TURNS:
        raise RuntimeError(f"only {len(cards)} cards, a Short needs {TURNS}")
    book = catalogue.load()
    lines = out / "audio" / "game"

    picked = choose_turns(cards, video_id)
    plans = []
    for turn, card in picked:
        stem = f"{card['idx']:02d}_{card['subject'].replace(' ', '_')}"
        source = next((p for p in (out / "game_clips" / f"{stem}.mp4", out / "clips" / f"{stem}.mp4")
                       if p.exists()), card.get("image_path"))
        if not source:
            raise RuntimeError(f"no picture for {card['subject']}")
        clip_id = card.get("game_clip_id") if "game_clips" in str(source) else card.get("clip_id")
        area = next((c.get("subject_area") for c in (book.get(card["subject"]) or {}).get("clips", [])
                     if str(c.get("id")) == str(clip_id)), None)
        raw = narrate.game_sound(card, out / "sounds")
        sound = None
        if raw is not None:
            sound = work / f"sound_{card['idx']:02d}.mp3"
            if not sound.exists():
                tts.normalise(raw, sound, float(cfg.get("sound_lufs", tts.SOUND_LUFS)),
                              game.SOUND_SECONDS)
        q, a = lines / f"q_{turn:02d}.mp3", lines / f"a_{turn:02d}.mp3"
        if not (q.exists() and a.exists()):
            raise RuntimeError(f"the game's lines for turn {turn} are missing")
        plans.append({"card": card, "turn": turn, "source": source, "area": area,
                      "sound": sound, "q": q, "a": a,
                      "base": game.timeline(tts.duration(q), tts.duration(a), sound is not None)})

    count = len(cards)
    theme = (video.get("theme") or "animals").lower()
    words = thumbnail.COVER_WORD.get(theme, theme.upper())
    end_line = work / "end.mp3"
    if not end_line.exists():
        tts.say_part(f"Watch all {count} in the full video!", "cue", end_line, cfg)
    end_seconds = round(max(END_SECONDS, tts.duration(end_line) + 0.8) * FPS) / FPS

    base = sum(p["base"]["end"] for p in plans)
    hold = min(0.0, max(-1.5, (MAX_SECONDS - 1.0 - end_seconds - base) / len(plans)))
    voice_db = game.active_db(plans[0]["q"])

    videos, audios, report = [], [], []
    for n, p in enumerate(plans):
        t = game.timeline(tts.duration(p["q"]), tts.duration(p["a"]), p["sound"] is not None, hold)
        hstill = game.still_from(p["source"], game.START_IN_CLIP, work / f"h_{n}.png")
        x0 = slice_left(hstill)
        vstill = vertical_still(p["source"], x0, work / f"v_{n}_{x0}.png")
        small = p["area"] is not None and p["area"] < game.SMALL_SUBJECT
        box, detail = (None, 0.0) if small else piece_in_slice(vstill)
        label = render.label_image(p["card"]["subject"], work / f"label_{n}.png")
        n_head, n_total = int(round(t["frozen_until"] * FPS)), int(round(t["end"] * FPS))
        question = game.question_for(p["turn"], p["sound"] is not None)
        head = encode(head_frames(vstill, box, Image.open(label).convert("RGBA"), question, t,
                                  seed=n * 11 + 3), work / f"turn_{n}_{n_total}_a.mp4")
        tail = tail_segment(p["source"], x0, (n_total - n_head) / FPS, label,
                            work / f"turn_{n}_{n_total}_b.mp4")
        hit = "whoosh" if box else "pop"
        items = [(p["q"], t["question"], 0.0), (p["a"], t["answer"], 0.0),
                 (game.sfx(hit), t["reveal"], game.effect_gain(hit, voice_db))]
        items += [(game.sfx("tick"), t["countdown"] + k, game.effect_gain("tick", voice_db))
                  for k in range(game.COUNT)]
        if p["sound"] is not None:
            items += [(p["sound"], t["sound1"], 0.0), (p["sound"], t["sound2"], 0.0)]
        audios.append(game.mix(items, n_total / FPS, work / f"turn_{n}_{n_total}.m4a"))
        videos += [head, tail]
        report.append({"subject": p["card"]["subject"], "seconds": n_total / FPS,
                       "riddle": "piece" if box else "blur", "sound": p["sound"] is not None})

    end_video = encode(end_card_frames(words, count, end_seconds),
                       work / f"end_{int(end_seconds * FPS)}.mp4")
    videos.append(end_video)
    audios.append(game.mix([(end_line, 0.4, 0.0)], end_seconds, work / "end.m4a"))

    silent = render.concat(videos, work / "_video.mp4")
    track = render.concat(audios, work / "_audio.m4a")
    seconds = render.probe_duration(silent)
    chosen = music_lib.pick(video_id)
    if not chosen:
        raise RuntimeError("no music to score the Short with")
    gain = music_lib.pick_gain(chosen, track, float(cfg.get("music_under_voice_db",
                                                             music_lib.GAIN_UNDER_VOICE_DB)))
    bed = music_lib.bed(chosen, seconds, work / "_music.m4a", gain)
    final = render.mux(silent, track, out / "short.mp4", cfg, bed)
    render.check_music_is_audible(track, final)
    length = render.probe_duration(final)
    if not MIN_SECONDS <= length <= MAX_SECONDS + 0.5:
        raise RuntimeError(f"the Short is {length:.1f} s, outside {MIN_SECONDS:.0f}-{MAX_SECONDS:.0f}")
    result = {"seconds": round(length, 2), "turns": report, "hold": hold,
              "full_video_cards": count, "theme": theme, "path": str(final)}
    (out / "short.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    log.info("Short: %.1f s, %s", length,
             ", ".join(f"{r['subject']} ({r['riddle']}{', sound' if r['sound'] else ''})"
                       for r in report))
    return result


# --- upload --------------------------------------------------------------------------------

def short_body(video, report, cfg):
    """Made for kids, like everything on this channel, and public with its full video."""
    from pipeline import seo, upload
    theme = report["theme"]
    what, _hook = seo.THEME_WORDS.get(theme, (theme.title(), ""))
    title = f"Can You Guess These {len(report['turns'])} {what}? #shorts"
    description = "\n\n".join([
        f"Guess who! {len(report['turns'])} {what.lower()} for toddlers - a piece of the "
        f"picture, the real sound, then the answer.",
        f"Watch all {report['full_video_cards']} in the full video: "
        f"https://youtu.be/{video['youtube_id']}",
        "#shorts #kidslearning #toddlerlearning"])
    status = {"privacyStatus": cfg.get("privacy_status", "private"),
              "selfDeclaredMadeForKids": upload.MADE_FOR_KIDS,
              "containsSyntheticMedia": upload.CONTAINS_SYNTHETIC_MEDIA}
    if video.get("published_at"):
        status["privacyStatus"] = "private"
        status["publishAt"] = video["published_at"]
    yt = cfg.get("youtube") or {}
    return {"snippet": {"title": title, "description": description,
                        "tags": ["shorts", "guess the animal", "kids learning", "toddler learning",
                                 what.lower(), f"{what.lower()} for kids"],
                        "categoryId": str(yt.get("category_id", upload.CATEGORY_ID)),
                        "defaultLanguage": yt.get("default_language", upload.DEFAULT_LANGUAGE)},
            "status": status}


def run(video_id, cfg, db, output_dir, service=None):
    """Build and upload the day's Short. Never fails the day: a missing Short is logged."""
    try:
        return _run(video_id, cfg, db, output_dir, service)
    except Exception as e:                                       # noqa: BLE001
        log.warning("no Short today: %s", str(e)[:300])
        db.log_event(video_id, "short", "warning", f"no Short today: {str(e)[:300]}")
        return True


def _run(video_id, cfg, db, output_dir, service=None):
    if not cfg.get("shorts", True):
        return True
    out = Path(output_dir)
    video = db.get_video(video_id) or {}
    # Recorded in the database, which is committed after every run, and in a file beside the
    # video for the run itself: either one stops a second upload.
    marker = out / "short_uploaded.json"
    if video.get("short_youtube_id"):
        log.info("the Short is already up: %s", video["short_youtube_id"])
        return True
    if marker.exists():
        db.update_video(video_id, short_youtube_id=json.loads(marker.read_text())["youtube_id"])
        return True
    if not video.get("youtube_id"):
        raise RuntimeError("the full video is not on YouTube, so the Short would point nowhere")
    report = (json.loads((out / "short.json").read_text(encoding="utf-8"))
              if (out / "short.mp4").exists() and (out / "short.json").exists()
              else build(video_id, cfg, db, out))
    from pipeline import upload
    body = short_body(video, report, cfg)
    upload.assert_mandatory_flags(body)
    if service is None:
        from core import youtube
        service = youtube.build_service(youtube.load_credentials())
    response, _stats = upload.upload_video(service, body, out / "short.mp4",
                                           out / "short_session.json")
    youtube_id = response.get("id")
    if not youtube_id:
        raise RuntimeError(f"YouTube returned no id for the Short: {response}")
    marker.write_text(json.dumps({"youtube_id": youtube_id}), encoding="utf-8")
    db.update_video(video_id, short_youtube_id=youtube_id)
    log.info("Short uploaded: https://youtube.com/shorts/%s; YouTube stored: %s", youtube_id,
             upload.describe_stored(response))
    db.log_event(video_id, "short", "info",
                 f"https://youtube.com/shorts/{youtube_id}, {report['seconds']:.0f} s, made for "
                 f"kids; YouTube stored: {upload.describe_stored(response)}")
    return True
