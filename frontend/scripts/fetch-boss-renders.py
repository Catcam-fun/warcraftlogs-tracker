"""Fetch official Blizzard creature renders for the landing-page boss strip.

Usage: python fetch-boss-renders.py ["Boss Name" ...]
With names, only those bosses are (re)fetched; otherwise all of BOSSES.
Writes public/art/bosses/<slug>.webp (300px tall, transparent) directly.
"""
import csv, io, json, os, re, sys, time, urllib.parse, urllib.request
from PIL import Image, ImageDraw, ImageFilter

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public", "art", "bosses")
os.makedirs(OUT, exist_ok=True)

BOSSES = [
    "Plexus Sentinel", "Loom'ithar", "Soulbinder Naazindhri", "Forgeweaver Araz",
    "The Soul Hunters", "Fractillus", "Nexus-King Salhadaar", "Dimensius, the All-Devouring",
    "Ulgrax the Devourer", "The Bloodbound Horror", "Sikran, Captain of the Sureki",
    "Rasha'nan", "Broodtwister Ovi'nax", "Nexus-Princess Ky'veza", "The Silken Court",
    "Queen Ansurek", "Vexie and the Geargrinders", "Cauldron of Carnage", "Rik Reverb",
    "Stix Bunkjunker", "Sprocketmonger Lockenstock", "One-Armed Bandit",
    "Mug'Zee, Heads of Security", "Chrome King Gallywix", "Imperator Averzian",
    "Vorasius", "Fallen-King Salhadaar", "Vaelgor & Ezzorak", "Lightblinded Vanguard",
    "Crown of the Cosmos", "Chimaerus, the Undreamt God", "Belo'ren", "L'ura",
    # Midnight Season 2: The Venomous Abyss + Tidebound Grotto
    "Nek'zali the Soulcoiler", "Entombed Sentinels", "The Lost Explorers",
    "Vashnik the Malignant", "Sszorak", "The Twin Fangs", "The Coiled Altar",
    "Ula'tek", "Nymrissa Wavecaller",
]
if len(sys.argv) > 1:
    BOSSES = [b for b in BOSSES if b in sys.argv[1:]]
ENC_OVERRIDE = {"l'ura": "2740"}
# Hand-picked display IDs where the journal's first creatures render badly
# (The Lost Explorers: Mor'zahi renders as a spell effect and the other
# three explorers share one ogre model).
DISPLAY_OVERRIDE = {"the-lost-explorers": ["143082"]}
COUNCIL = {"the-soul-hunters": 3, "vaelgor-ezzorak": 2,
           "cauldron-of-carnage": 2, "the-silken-court": 3,
           "lightblinded-vanguard": 3, "entombed-sentinels": 2,
           "the-twin-fangs": 2, "the-coiled-altar": 2}
BG = (24, 24, 24)

def slug(n): return re.sub(r'^-|-$', '', re.sub(r'[^a-z0-9]+', '-', n.lower()))
def norm(s): return re.sub(r'[^a-z0-9]', '', s.lower())
def token(name):
    w = [x for x in re.findall(r"[A-Za-z]+", name) if x.lower() not in ("the","of","and")]
    return max(w, key=len) if w else name
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers={
        "User-Agent": UA, "Referer": "https://wago.tools/"}), timeout=40).read().decode("utf-8","replace")
def get_img(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA,
        "Accept": "image/*,*/*", "Referer": "https://worldofwarcraft.blizzard.com/"}), timeout=40).read()

def cutout(im):
    """Flood-fill the flat #181818 background from the borders → transparent,
    then tight-crop to the model. Interior dark pixels are preserved."""
    rgb = im.convert("RGB")
    W, H = rgb.size
    work = rgb.copy()
    KEY = (255, 0, 255)
    for seed in [(0,0),(W-1,0),(0,H-1),(W-1,H-1),(W//2,0),(W//2,H-1),(0,H//2),(W-1,H//2)]:
        try:
            ImageDraw.floodfill(work, seed, KEY, thresh=26)
        except Exception:
            pass
    wpx = work.load()
    alpha = Image.new("L", (W, H), 0)
    apx = alpha.load()
    for y in range(H):
        for x in range(W):
            apx[x, y] = 0 if wpx[x, y] == KEY else 255
    # clean up: close small holes, then feather edges
    alpha = alpha.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.8))
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    bb = alpha.getbbox()
    if bb:
        pad = 6
        l, t, r, b = bb
        out = out.crop((max(0,l-pad), max(0,t-pad), min(W,r+pad), min(H,b+pad)))
    return out

def shadow(rgba):
    a = rgba.split()[3]
    sh = Image.new("RGBA", rgba.size, (0,0,0,0))
    blk = Image.new("RGBA", rgba.size, (0,0,0,150))
    sh.paste(blk, (0,0), a)
    return sh.filter(ImageFilter.GaussianBlur(7))

results = {}
for boss in BOSSES:
    sl = slug(boss); tok = token(boss); key = boss.strip().lower()
    try:
        enc = ENC_OVERRIDE.get(key)
        if not enc:
            je = get(f"https://wago.tools/db2/JournalEncounter/csv?search={urllib.parse.quote(tok)}")
            cand = [r for r in csv.DictReader(io.StringIO(je))
                    if norm(r.get("Name_lang","")) == norm(boss)
                    or (len(norm(boss))>5 and norm(boss) in norm(r.get("Name_lang","")))
                    or (len(norm(r.get("Name_lang","")))>5 and norm(r.get("Name_lang","")) in norm(boss))]
            if not cand:
                results[sl]={"boss":boss,"status":"no_enc"}; print("MISS enc",boss); continue
            enc = max(cand, key=lambda r:int(r["ID"]))["ID"]
        jc = get(f"https://wago.tools/db2/JournalEncounterCreature/csv?search={urllib.parse.quote(tok)}")
        crows = sorted([r for r in csv.DictReader(io.StringIO(jc))
                        if r.get("JournalEncounterID")==enc],
                       key=lambda r:int(r.get("OrderIndex") or 0))
        want = COUNCIL.get(sl, 1)
        disp, seen = [], set()
        for r in crows:
            d = r.get("CreatureDisplayInfoID")
            if d and d!="0" and d not in seen:
                seen.add(d); disp.append(d)
                if len(disp) >= want: break
        disp = DISPLAY_OVERRIDE.get(sl, disp)
        if not disp:
            results[sl]={"boss":boss,"status":"no_disp","enc":enc}; print("MISS disp",boss); continue
        cuts = []
        for d in disp:
            try:
                cuts.append(cutout(Image.open(io.BytesIO(get_img(
                    f"https://render.worldofwarcraft.com/us/npcs/zoom/creature-display-{d}.jpg")))))
            except Exception as e:
                print("  cut fail", d, e)
        if not cuts:
            results[sl]={"boss":boss,"status":"cut_fail","enc":enc}; print("MISS cut",boss); continue
        H = 560
        sc = []
        for c in cuts:
            w = max(1, int(c.size[0]*H/c.size[1]))
            sc.append(c.resize((w, H), Image.LANCZOS))
        overlap = int(H*0.10) if len(sc) > 1 else 0
        W = sum(s.size[0] for s in sc) - overlap*(len(sc)-1)
        canvas = Image.new("RGBA", (W, H), (0,0,0,0))
        x = 0
        for s in sc:
            canvas.alpha_composite(shadow(s), (x, 10))
            x += s.size[0] - overlap
        x = 0
        for s in sc:
            canvas.alpha_composite(s, (x, 0))
            x += s.size[0] - overlap
        bb = canvas.split()[3].getbbox()
        if bb: canvas = canvas.crop(bb)
        TILE_H = 300  # matches the existing tiles
        canvas = canvas.resize((max(1, round(canvas.size[0] * TILE_H / canvas.size[1])), TILE_H), Image.LANCZOS)
        canvas.save(f"{OUT}/{sl}.webp", "WEBP", quality=82, method=6)
        results[sl]={"boss":boss,"status":"ok","enc":enc,"models":len(cuts),"size":list(canvas.size)}
        print(f"OK   {boss:<32} enc={enc} models={len(cuts)} {canvas.size}")
    except Exception as e:
        results[sl]={"boss":boss,"status":f"err:{e}"}; print("ERR",boss,e)
    time.sleep(0.2)

json.dump(results, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_boss_results.json"),"w"), indent=1)
ok=sum(1 for v in results.values() if v["status"]=="ok")
print(f"\n=== {ok}/{len(BOSSES)} ; misses:",[k for k,v in results.items() if v['status']!='ok'])
