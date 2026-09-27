"""Gera tiles 2D top-down (varios biomas) para um colony-sim medieval via Higgsfield API.

Dois tipos:
  - tile   : textura de chao/agua/piso vista de cima, tornada seamless (repete sem costuras)
  - object : arvores, rochas, plantas... isolados com fundo transparente

Uso:
    pip install -r tiles/requirements.txt
    export HF_API_KEY=...  HF_API_SECRET=...   (ou HF_KEY="key:secret")
    python tiles/generate_tiles.py                  # gera tudo
    python tiles/generate_tiles.py floresta deserto # so esses biomas/grupos
    python tiles/generate_tiles.py --list           # lista o que existe

Saida: tiles/output/<grupo>/<nome>.png        (2K)
       tiles/output/<grupo>/<nome>_256.png    (pronto para o jogo)
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
GAME_SIZE = 256
MAX_PARALLEL = 5

# Mesmo estilo dos sprites das personagens: guache plano, sombreado cel em 2 tons,
# paleta terrosa, textura de papel. Os tiles de chao sao mais calmos (sem contorno
# forte) para as personagens e objetos se destacarem por cima.
TILE_STYLE = (
    'Seamless tileable square game texture, strictly top-down orthographic view looking '
    'straight down, flat even lighting, no perspective, no horizon, no shadows cast from '
    'outside. Stylized hand-painted 2D art: flat gouache colors with soft two-tone cel '
    'shading, subtle paper grain, muted earthy medieval palette, low-contrast so characters '
    'stand out on top. Colony-sim game ground tile, uniform detail across the whole square, '
    'no single focal object, no text, no border, no frame. Surface: '
)

OBJECT_STYLE = (
    'Single 2D game object sprite for a top-down colony-sim, seen from a high three-quarter '
    'top-down angle, centered, whole object visible. Stylized hand-painted art: chunky '
    'rounded shapes, bold dark brown outline of even thickness, flat gouache colors with '
    'two-tone cel shading, subtle paper grain, muted earthy medieval palette. Isolated on a '
    'plain flat pure white background, no ground, no cast shadow, no text, no frame. Object: '
)

# grupo -> [(nome, tipo, descricao)]
CATALOG = {
    'prado': [
        ('relva', 'tile', 'lush short meadow grass with tiny clover and a few small white flowers'),
        ('relva_alta', 'tile', 'tall wild meadow grass blades with yellow buttercups'),
        ('terra', 'tile', 'bare packed brown dirt with small pebbles and dry grass tufts'),
        ('arbusto_bagas', 'object', 'round green bush with clusters of red berries'),
        ('flores', 'object', 'small patch of mixed wildflowers, poppies and cornflowers'),
    ],
    'floresta': [
        ('chao_floresta', 'tile', 'forest floor of dark soil, fallen oak leaves, moss and twigs'),
        ('musgo', 'tile', 'thick spongy green moss carpet with tiny ferns'),
        ('carvalho', 'object', 'large leafy oak tree with a round dense canopy'),
        ('pinheiro', 'object', 'tall dark green pine tree'),
        ('toco', 'object', 'cut tree stump with visible rings and a small axe notch'),
        ('cogumelos', 'object', 'cluster of red spotted and brown forest mushrooms'),
    ],
    'outono': [
        ('folhas_outono', 'tile', 'ground covered in orange, red and golden fallen leaves'),
        ('arvore_outono', 'object', 'maple tree with bright orange and red autumn foliage'),
        ('abobora', 'object', 'a few orange pumpkins with curly vines'),
    ],
    'pantano': [
        ('lama', 'tile', 'wet dark swamp mud with puddles and bubbles'),
        ('agua_pantano', 'tile', 'murky green swamp water with floating duckweed and algae'),
        ('canicos', 'object', 'clump of tall cattail reeds'),
        ('arvore_morta', 'object', 'twisted dead gnarled tree with hanging grey moss'),
        ('nenufares', 'object', 'group of lily pads with one pink water lily flower'),
    ],
    'deserto': [
        ('areia', 'tile', 'fine golden desert sand with soft wind ripples'),
        ('terra_rachada', 'tile', 'dry cracked sun-baked clay earth'),
        ('cato', 'object', 'tall saguaro-like cactus with two arms'),
        ('rocha_arenito', 'object', 'layered red sandstone rock'),
        ('ossos', 'object', 'bleached animal skull and scattered bones'),
    ],
    'tundra': [
        ('neve', 'tile', 'fresh soft white snow with subtle blue shading and smooth wind-shaped drifts'),
        ('gelo', 'tile', 'frozen pale blue ice with cracks and frost patterns'),
        ('tundra', 'tile', 'frozen tundra ground with patches of snow, grey lichen and dead grass'),
        ('pinheiro_neve', 'object', 'snow-covered pine tree'),
        ('cristal_gelo', 'object', 'cluster of jagged pale blue ice crystals'),
    ],
    'montanha': [
        ('rocha', 'tile', 'rough grey mountain rock surface with cracks'),
        ('cascalho', 'tile', 'loose grey gravel and small stones'),
        ('pedregulho', 'object', 'large rounded grey boulder'),
        ('minerio_ferro', 'object', 'grey rock with rusty orange iron ore veins'),
        ('minerio_ouro', 'object', 'dark rock with shiny gold ore nuggets'),
        ('minerio_cristal', 'object', 'rock with glowing purple crystal shards'),
    ],
    'vulcanico': [
        ('cinza', 'tile', 'dark volcanic ash ground with black basalt pebbles'),
        ('lava', 'tile', 'molten orange lava with dark cooling crust plates'),
        ('obsidiana', 'object', 'sharp black glossy obsidian rock'),
        ('arvore_queimada', 'object', 'charred burnt black tree trunk with glowing embers'),
    ],
    'costa': [
        ('areia_praia', 'tile', 'pale beach sand with tiny shells'),
        ('agua_rasa', 'tile', 'clear shallow turquoise water over sandy bottom'),
        ('agua_funda', 'tile', 'deep dark blue ocean water with gentle wave patterns'),
        ('rio', 'tile', 'flowing blue river water with light ripples'),
        ('rochas_costa', 'object', 'wet coastal rocks with barnacles and seaweed'),
        ('barco_rio', 'object', 'small wooden rowboat'),
    ],
    'construcao': [
        ('chao_madeira', 'tile', 'wooden plank floor, warm oak boards'),
        ('chao_pedra', 'tile', 'cut stone flagstone floor with mortar lines'),
        ('calcada', 'tile', 'cobblestone road with rounded grey stones'),
        ('caminho_terra', 'tile', 'worn dirt footpath with wagon ruts'),
        ('campo_cultivo', 'tile', 'tilled farmland soil in neat dark furrows'),
        ('palha', 'tile', 'thatched straw roof texture'),
        ('parede_pedra', 'tile', 'top of a thick stone castle wall, grey blocks'),
        ('parede_madeira', 'tile', 'top view of a wooden log palisade wall, sharpened log tips'),
    ],
}


def make_tileable(img: Image.Image) -> Image.Image:
    """Remove as costuras: mistura a imagem com a sua versao deslocada meio tile.

    A versao deslocada e perfeita nas bordas (as bordas originais ficam no centro),
    a original e perfeita no centro, por isso usa-se a deslocada perto das bordas
    e a original no meio.
    """
    img = img.convert('RGB')
    w, h = img.size
    shifted = Image.new('RGB', (w, h))
    shifted.paste(img.crop((w // 2, h // 2, w, h)), (0, 0))
    shifted.paste(img.crop((0, h // 2, w // 2, h)), (w - w // 2, 0))
    shifted.paste(img.crop((w // 2, 0, w, h // 2)), (0, h - h // 2))
    shifted.paste(img.crop((0, 0, w // 2, h // 2)), (w - w // 2, h - h // 2))
    mask = Image.new('L', (w, h))
    px = mask.load()
    for y in range(h):
        dy = min(y, h - 1 - y) / (h / 2)
        for x in range(w):
            dx = min(x, w - 1 - x) / (w / 2)
            px[x, y] = int(255 * min(1.0, min(dx, dy) * 2.5))
    return Image.composite(img, shifted, mask)


def remove_background(img: Image.Image, tolerance: int = 40) -> Image.Image:
    """Torna transparente o fundo claro ligado as margens (flood-fill a partir das bordas)."""
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


def fit_square(img: Image.Image, size: int) -> Image.Image:
    """Encaixa um objeto transparente num quadrado size x size, centrado em baixo."""
    img = img.copy()
    img.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    canvas.paste(img, ((size - img.width) // 2, size - img.height), img)
    return canvas


async def generate(group, name, kind, desc, http, sem):
    style = TILE_STYLE if kind == 'tile' else OBJECT_STYLE
    async with sem:
        print(f'[{group}/{name}] a gerar...')
        result = await higgsfield_client.subscribe_async(
            MODEL,
            arguments={'prompt': style + desc + '.', 'resolution': '2K', 'aspect_ratio': '1:1'},
        )
        data = (await http.get(result['images'][0]['url'])).content
    out = OUT_DIR / group
    out.mkdir(parents=True, exist_ok=True)
    img = Image.open(io.BytesIO(data))
    if kind == 'tile':
        full = make_tileable(img)
        small = full.resize((GAME_SIZE, GAME_SIZE), Image.LANCZOS)
    else:
        full = remove_background(img)
        small = fit_square(full, GAME_SIZE)
    full.save(out / f'{name}.png')
    small.save(out / f'{name}_{GAME_SIZE}.png')
    print(f'[{group}/{name}] ok')


async def main(groups):
    jobs = [(g, *item) for g, items in CATALOG.items() if not groups or g in groups for item in items]
    sem = asyncio.Semaphore(MAX_PARALLEL)
    async with httpx.AsyncClient(timeout=120) as http:
        results = await asyncio.gather(*(generate(*j, http, sem) for j in jobs), return_exceptions=True)
    failed = [(j, r) for j, r in zip(jobs, results) if isinstance(r, Exception)]
    for (g, n, *_), err in failed:
        print(f'[{g}/{n}] FALHOU: {err!r}')
    print(f'{len(jobs) - len(failed)}/{len(jobs)} gerados em {OUT_DIR}')


if __name__ == '__main__':
    args = sys.argv[1:]
    if args == ['--list']:
        for g, items in CATALOG.items():
            print(f'{g}: ' + ', '.join(f'{n} ({k})' for n, k, _ in items))
    else:
        unknown = [a for a in args if a not in CATALOG]
        if unknown:
            sys.exit(f'Grupos desconhecidos: {unknown}. Usa --list.')
        asyncio.run(main(args))
