"""
Gera a identidade visual (PROMO DO BAIANO): assets/logo.png e assets/logo.ico.
Rodar: python assets/gerar_logo.py  (só Pillow; refaça quando a marca mudar)
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

PASTA = Path(__file__).parent
T = 1024  # desenha grande e reduz (bordas suaves)
AZUL_TOPO, AZUL_BASE = (33, 92, 214), (10, 38, 110)
LARANJA, LARANJA_ESC = (249, 115, 22), (194, 65, 12)
BRANCO = (255, 255, 255)


def fonte(tam):
    for nome in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(nome, tam)
        except OSError:
            continue
    return ImageFont.load_default()


def desenhar() -> Image.Image:
    # Fundo: quadrado arredondado com degradê azul
    grad = Image.new("RGB", (T, T))
    gd = ImageDraw.Draw(grad)
    for y in range(T):
        k = y / T
        gd.line([(0, y), (T, y)], fill=tuple(int(a + (b - a) * k) for a, b in zip(AZUL_TOPO, AZUL_BASE)))
    mascara = Image.new("L", (T, T), 0)
    ImageDraw.Draw(mascara).rounded_rectangle([0, 0, T - 1, T - 1], radius=230, fill=255)
    img = Image.new("RGBA", (T, T), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mascara)

    # Etiqueta de preço (laranja) inclinada, com furo e "%"
    tag = Image.new("RGBA", (T, T), (0, 0, 0, 0))
    td = ImageDraw.Draw(tag)
    x0, y0, x1, y1 = 250, 250, 790, 774
    corpo = [(x0 + 170, y0), (x1, y0), (x1, y1), (x0 + 170, y1), (x0, (y0 + y1) // 2)]
    td.polygon([(x + 18, y + 22) for x, y in corpo], fill=(0, 0, 0, 70))       # sombra
    td.polygon(corpo, fill=LARANJA)
    td.polygon([(x1 - 40, y0), (x1, y0), (x1, y1), (x1 - 40, y1)], fill=LARANJA_ESC)
    cx, cy, r = x0 + 120, (y0 + y1) // 2, 42
    td.ellipse([cx - r, cy - r, cx + r, cy + r], fill=AZUL_BASE)               # furo
    f = fonte(330)
    td.text((560, (y0 + y1) // 2 + 10), "%", font=f, fill=BRANCO, anchor="mm")
    tag = tag.rotate(-14, resample=Image.BICUBIC, center=(T // 2, T // 2))
    img.alpha_composite(tag)

    # Sem texto no ícone: ilegível em 16–48 px; o nome aparece ao lado do logo na interface
    return img


if __name__ == "__main__":
    logo = desenhar()
    logo.resize((256, 256), Image.LANCZOS).save(PASTA / "logo.png")
    logo.save(PASTA / "logo.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("Gerado:", PASTA / "logo.png", PASTA / "logo.ico")
