"""The Qwen 3.5 0.8B Dictionary of the English Language.

    python3 dictionary.py              define every word in data/words.txt  -> data/definitions.jsonl
    python3 dictionary.py illustrate   draw the first drawable words        -> data/drawable.jsonl, data/illustrations/
    python3 dictionary.py page         refill the entries of index.html    -> index.html
"""
import html, json, os, re, sys, time, requests
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

SERVER = "http://localhost:6982"  # llama-server running Qwen3.5-0.8B
WORKERS = 4
DEFINITION_TOKENS = 40
PICTURES, PICTURE_TOKENS, PICTURE_TEMPERATURE = 200, 1200, 0.5
PALETTE = [(0.35, "#e8dfcc"), (0.7, "#c9a45c"), (1.01, "#16130f")]  # luminance upper bound -> ink, accent, paper
SHAPES = "line rect circle ellipse polygon polyline"
BLOCK = 200  # entries per page block


def chat(prompt, **kw):
    r = requests.post(SERVER + "/v1/chat/completions", json={"messages": [{"role": "user", "content": prompt}],
        "chat_template_kwargs": {"enable_thinking": False}, **kw}).json()
    return r["choices"][0]["message"]["content"]


# ---------- definitions ----------

def define(w):
    t = chat(f"Write a one-line dictionary entry, exactly like this example.\nhouse: /haʊs/ n. A building in which people live.\n{w}:",
             max_tokens=DEFINITION_TOKENS, temperature=0).strip()
    m = re.match(r"(?:[\w'-]+:)?\W*/([^/]+)/\s*([a-z]+\.)?\s*(.+)", t)
    return {"word": w, "ipa": m[1], "pos": m[2], "definition": m[3]} if m else {"word": w, "definition": t}


def definitions():
    words, t0 = open("data/words.txt").read().split(), time.time()
    with open("data/definitions.jsonl", "w") as out, ThreadPoolExecutor(WORKERS) as ex:
        for n, entry in enumerate(ex.map(define, words), 1):
            out.write(json.dumps(entry) + "\n")
            if n % 100 == 0: print(f"{n}/{len(words)}, {n / (time.time() - t0):.1f} words/s", flush=True)


# ---------- illustrations ----------

def drawable(w, cache):
    if w not in cache:
        cache[w] = chat(f"Is \"{w}\" a physical thing you can see or touch? Answer Yes or No.", grammar='root ::= "Yes" | "No"', max_tokens=2, temperature=0) == "Yes"
        with open("data/drawable.jsonl", "a") as f: f.write(json.dumps({"word": w, "drawable": cache[w]}) + "\n")
    return cache[w]


NAMED = {"black": "000000", "white": "ffffff", "red": "ff0000", "green": "008000", "blue": "0000ff", "yellow": "ffff00", "orange": "ffa500",
         "brown": "a52a2a", "gray": "808080", "grey": "808080", "pink": "ffc0cb", "purple": "800080", "gold": "ffd700", "silver": "c0c0c0"}


def tone(color):
    """Snap any color to the page palette by luminance; keep none/transparent."""
    c = color.strip().lower()
    if c in ("none", "transparent"): return c
    if c.startswith("#"): h = c[1:]; h = "".join(x * 2 for x in h) if len(h) == 3 else h[:6]
    elif c.startswith("rgb"): h = "".join(f"{int(float(v)):02x}" for v in re.findall(r"[\d.]+", c)[:3])
    else: h = NAMED.get(c, "000000")  # unknown names and gradients go to ink
    try: r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError: return PALETTE[0][1]
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return next(col for top, col in PALETTE if lum < top)


def draw(w):
    t = chat(f"Draw a recognizable \"{w}\" as an SVG with viewBox=\"0 0 100 100\", in the style of an antique dictionary woodcut engraving. "
             f"Use 10 to 25 shapes ({SHAPES}): black outlines with stroke and fill=\"none\" for the main form, a few solid black blocks for shadows, "
             "and short parallel hatching lines for texture. Show its characteristic parts. Absolutely no text, no letters. Output only the SVG code.",
             max_tokens=PICTURE_TOKENS, temperature=PICTURE_TEMPERATURE)
    m = re.search(r"<svg.*?</svg>", t, re.S)
    if not m: return None
    svg = re.sub(r"<text.*?</text>|<text[^>]*/>", "", m[0], flags=re.S)
    svg = re.sub(r'((?:fill|stroke|stop-color)\s*[=:]\s*"?)([^";>]+)', lambda x: x[1] + tone(x[2]), svg)
    svg = re.sub(r"(<svg[^>]*>)", rf'\1<g fill="{PALETTE[0][1]}">', svg, 1).replace("</svg>", "</g></svg>")  # default fill is black otherwise
    try: ET.fromstring(svg)
    except ET.ParseError: return None
    open(f"data/illustrations/{w}.svg", "w").write(svg)
    return w


def illustrate():
    os.makedirs("data/illustrations", exist_ok=True)
    words = [json.loads(l)["word"] for l in open("data/definitions.jsonl")]  # most common first
    cache = {r["word"]: r["drawable"] for r in map(json.loads, open("data/drawable.jsonl"))} if os.path.exists("data/drawable.jsonl") else {}
    done = [f.removesuffix(".svg") for f in os.listdir("data/illustrations")]  # keep what is already drawn
    with ThreadPoolExecutor(WORKERS) as ex:
        for i in range(0, len(words), 50):
            chunk = words[i:i + 50]
            picked = [w for w, ok in zip(chunk, ex.map(lambda w: drawable(w, cache), chunk)) if ok and w not in done][:PICTURES - len(done)]
            done += [w for w in ex.map(draw, picked) if w]
            print(f"scanned {i + len(chunk)}, illustrated {len(done)}/{PICTURES}", flush=True)
            if len(done) >= PICTURES: break


# ---------- page ----------

def page():
    entries = sorted((json.loads(l) for l in open("data/definitions.jsonl")), key=lambda e: e["word"])
    folder = "data/illustrations"
    pictures = {f.removesuffix(".svg"): open(f"{folder}/{f}").read() for f in os.listdir(folder)} if os.path.isdir(folder) else {}
    parts, letter, n = [], None, 0
    for e in entries:
        w = e["word"]
        if w[0] != letter:  # new letter: heading, then a fresh block
            if letter: parts.append("</section>")
            letter, n = w[0], 0; parts.append(f"<h2>{letter.upper()}</h2><section>")
        elif n % BLOCK == 0: parts.append("</section><section>")  # small blocks so the browser skips off-screen ones
        n += 1
        ipa = f' <span class="ipa">/{html.escape(e["ipa"].strip("/"))}/</span>' if e.get("ipa") else ""
        pos = f' <i>{html.escape(e["pos"])}</i>' if e.get("pos") else ""
        parts.append(f'<p id="{w}"><b>{w}</b>{ipa}{pos} {html.escape(e["definition"])}</p>')
        if w in pictures: parts.append(f"<figure>{pictures[w]}<figcaption>{w}</figcaption></figure>")
    parts.append("</section>")
    out = open("index.html").read()  # the page is its own template: only the entries and the word count change
    out = re.sub(r"<main>.*</main>", lambda _: "<main>\n" + "\n".join(parts) + "\n</main>", out, flags=re.S)
    out = re.sub(r'<b id="word-count">[\d,]*</b>', f'<b id="word-count">{len(entries):,}</b>', out)
    open("index.html", "w").write(out)
    print(f"index.html: {len(entries)} words, {len(pictures)} illustrations, {len(out) / 1e6:.1f} MB")


if __name__ == "__main__":
    {"illustrate": illustrate, "page": page}.get(sys.argv[1] if len(sys.argv) > 1 else "", definitions)()
