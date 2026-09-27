"""Gera 10 sprites 2D medievais (cabeca + tronco, sem bracos/pernas) via Higgsfield API.

Uso:
    pip install -r sprites/requirements.txt
    export HF_API_KEY=...  HF_API_SECRET=...   (ou HF_KEY="key:secret")
    python sprites/generate_sprites.py            # gera os 10
    python sprites/generate_sprites.py 3 7        # gera so os indicados

Saida: sprites/output/<nome>.png (original) e sprites/output/<nome>_transparent.png
(fundo removido por flood-fill a partir das margens).
"""

import asyncio
import io
import sys
from pathlib import Path

import higgsfield_client
import httpx
from PIL import Image, ImageDraw

MODEL = 'bytedance/seedream/v4/text-to-image'
OUT_DIR = Path(__file__).parent / 'output'

# Estilo comum: inspirado em colony-sims (RimWorld/Norland) mas com identidade propria:
# formas arredondadas e robustas, contorno escuro grosso, paleta terrosa com um unico
# acento de cor saturada por personagem, sombreado cel em 2 tons, textura de papel/guache.
STYLE = (
    '2D game character sprite, bust portrait of a single character: head and torso only, '
    'NO arms, NO hands, NO legs, the torso ends in a clean rounded bottom edge like a chess '
    'piece or a paper-doll token. Front three-quarter view, centered, facing the viewer. '
    'Original stylized art style: chunky rounded shapes, slightly oversized head, bold dark '
    'brown outline of even thickness, flat gouache colors with two-tone cel shading, subtle '
    'paper grain texture, muted earthy medieval palette with ONE vivid accent color. '
    'Charming, readable at small size, top-down colony-sim game aesthetic. '
    'Isolated on a plain flat pure white background, no ground shadow, no text, no frame, '
    'no scenery.'
)

CHARACTERS = [
    ('herbalista',
     'an old wise herbalist woman with a deep moss-green hood overgrown with tiny mushrooms '
     'and dried herbs, wrinkled kind face, round spectacles, bundles of lavender tied to her '
     'shawl; accent color: violet'),
    ('ferreiro',
     'a broad burly blacksmith with a soot-smudged face, thick red beard in two iron-ringed '
     'braids, bald head with a burn scar, heavy leather apron over a rough linen shirt; '
     'accent color: glowing ember orange'),
    ('apicultor_monge',
     'a gentle beekeeper monk wearing a wide straw hat with a hanging mesh veil pulled back, '
     'brown tonsured hair, rosy cheeks, a few bees orbiting his head, a honeycomb emblem '
     'stitched on his robe; accent color: honey gold'),
    ('escudeiro',
     'a nervous young squire with a slightly too big dented kettle helmet, freckles, big '
     'hopeful eyes, patched gambeson with a hand-painted crest of a tiny rooster; '
     'accent color: bright red'),
    ('cobrador_impostos',
     'a smug medieval tax collector with a tall floppy chaperon hat, thin curled mustache, '
     'narrow eyes, fur-trimmed velvet doublet with a heavy coin-purse chain across the chest; '
     'accent color: royal purple'),
    ('cacadora_norte',
     'a fierce northern huntress wearing a grey wolf-pelt hood with the wolf head on top, '
     'blue woad face paint stripes, long pale braids with bone beads, fur-lined leather '
     'vest; accent color: icy cyan'),
    ('bardo',
     'a charismatic wandering bard with a crooked feathered cap, mischievous grin, curly '
     'dark hair, striped mi-parti tunic in two colors, a lute strap crossing the chest; '
     'accent color: teal'),
    ('abadessa',
     'a stern elderly abbess in a black and white wimple, sharp nose, piercing grey eyes, '
     'a huge ornate iron key hanging from a chain on her chest, stitched cross on her habit; '
     'accent color: deep crimson'),
    ('pescador',
     'a weathered old fisherman with a wide woven straw hat, salt-crusted white beard, sun '
     'tanned face with laugh lines, knitted wool sweater with a small fish-bone charm '
     'necklace, a bit of seaweed on his shoulder; accent color: sea blue'),
    ('alquimista',
     'an eccentric young alchemist with brass-rimmed round goggles pushed up on her forehead, '
     'singed eyebrows, wild frizzy hair with a streak of smoke, stained apron over a hooded '
     'robe covered in little glass vials on a bandolier; accent color: toxic lime green'),
]


def remove_background(img: Image.Image, tolerance: int = 40) -> Image.Image:
    """Torna transparente o fundo claro ligado as margens (flood-fill a partir dos cantos/bordas)."""
    rgb = img.convert('RGB')
    w, h = rgb.size
    marker = (255, 0, 255)
    seeds = [(x, y) for x in range(0, w, max(1, w // 32)) for y in (0, h - 1)]
    seeds += [(x, y) for y in range(0, h, max(1, h // 32)) for x in (0, w - 1)]
    for seed in seeds:
        r, g, b = rgb.getpixel(seed)
        if min(r, g, b) >= 255 - tolerance and (r, g, b) != marker:
            ImageDraw.floodfill(rgb, seed, marker, thresh=tolerance)
    rgba = img.convert('RGBA')
    pixels = rgba.load()
    mask = rgb.load()
    for y in range(h):
        for x in range(w):
            if mask[x, y] == marker:
                pixels[x, y] = (0, 0, 0, 0)
    bbox = rgba.getbbox()
    return rgba.crop(bbox) if bbox else rgba


async def generate(name: str, description: str, http: httpx.AsyncClient) -> None:
    print(f'[{name}] a gerar...')
    result = await higgsfield_client.subscribe_async(
        MODEL,
        arguments={
            'prompt': f'{STYLE} Character: {description}.',
            'resolution': '2K',
            'aspect_ratio': '1:1',
        },
    )
    url = result['images'][0]['url']
    data = (await http.get(url)).content
    (OUT_DIR / f'{name}.png').write_bytes(data)
    remove_background(Image.open(io.BytesIO(data))).save(OUT_DIR / f'{name}_transparent.png')
    print(f'[{name}] ok -> {url}')


async def main(indices: list[int]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    chosen = [CHARACTERS[i - 1] for i in indices] if indices else CHARACTERS
    async with httpx.AsyncClient(timeout=120) as http:
        results = await asyncio.gather(
            *(generate(n, d, http) for n, d in chosen), return_exceptions=True
        )
    for (name, _), res in zip(chosen, results):
        if isinstance(res, Exception):
            print(f'[{name}] FALHOU: {res!r}')


if __name__ == '__main__':
    asyncio.run(main([int(a) for a in sys.argv[1:]]))
