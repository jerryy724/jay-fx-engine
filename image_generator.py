from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

def generate_signal_card(pair_or_title, direction_or_sub, session_text="JAY EMPIRE SYSTEM", is_update=False):
    W, H = 1000, 562
    img = Image.new('RGB', (W, H), color='#0A0E14')
    draw = ImageDraw.Draw(img)

    try:
        font_header = ImageFont.truetype("DejaVuSans-Bold.ttf", 36)
        font_main = ImageFont.truetype("DejaVuSans-Bold.ttf", 64)
        font_sub = ImageFont.truetype("DejaVuSans.ttf", 22)
        font_footer = ImageFont.truetype("DejaVuSans-Bold.ttf", 24)
    except Exception:
        font_header = font_main = font_sub = font_footer = ImageFont.load_default()

    if is_update:
        # Market Brief & Friday Rotation Style: Electric Blue Text on Pure Dark Slate/Black
        theme_color = '#00B0FF'
        header_text = "★ JAY FX MARKET BRIEF ★"
        main_text = pair_or_title
        sub_text = direction_or_sub

        bbox_h = draw.textbbox((0, 0), header_text, font=font_header)
        w_h = bbox_h[2] - bbox_h[0]
        draw.text(((W - w_h) // 2, 45), header_text, fill='#FFFFFF', font=font_header)
        draw.line([((W - w_h) // 2 + 30, 95), ((W + w_h) // 2 - 30, 95)], fill='#00B0FF', width=3)

        words = main_text.strip().split()
        if len(words) > 2:
            line1 = " ".join(words[:2])
            line2 = " ".join(words[2:])
            
            try:
                font_title_stacked = ImageFont.truetype("DejaVuSans-Bold.ttf", 46)
            except Exception:
                font_title_stacked = font_main

            bbox_l1 = draw.textbbox((0, 0), line1, font=font_title_stacked)
            w_l1 = bbox_l1[2] - bbox_l1[0]
            draw.text(((W - w_l1) // 2, 160), line1, fill=theme_color, font=font_title_stacked)

            bbox_l2 = draw.textbbox((0, 0), line2, font=font_title_stacked)
            w_l2 = bbox_l2[2] - bbox_l2[0]
            draw.text(((W - w_l2) // 2, 220), line2, fill=theme_color, font=font_title_stacked)

            sub_y_pos = 320
        else:
            bbox_m = draw.textbbox((0, 0), main_text, font=font_main)
            w_m = bbox_m[2] - bbox_m[0]
            h_m = bbox_m[3] - bbox_m[1]
            center_y = (H // 2) - (h_m // 2) - 10
            draw.text(((W - w_m) // 2, center_y), main_text, fill=theme_color, font=font_main)
            sub_y_pos = center_y + h_m + 25

        bbox_s = draw.textbbox((0, 0), sub_text, font=font_sub)
        w_s = bbox_s[2] - bbox_s[0]
        draw.text(((W - w_s) // 2, sub_y_pos), sub_text, fill='#8A99AD', font=font_sub)

    else:
        direction = direction_or_sub.upper()
        theme_color = '#00E676' if direction == "BUY" else '#FF2D55'
        header_text = f"★ {pair_or_title} ★"

        bbox_h = draw.textbbox((0, 0), header_text, font=font_header)
        w_h = bbox_h[2] - bbox_h[0]
        draw.text(((W - w_h) // 2, 45), header_text, fill='#FFFFFF', font=font_header)
        draw.line([((W - w_h) // 2 + 30, 95), ((W + w_h) // 2 - 30, 95)], fill='#D4AF37', width=2)

        cx = W // 2
        cy = (H // 2) - 35

        if direction == "BUY":
            arrow_pts = [(cx, cy - 35), (cx - 30, cy + 10), (cx + 30, cy + 10)]
        else:
            arrow_pts = [(cx, cy + 10), (cx - 30, cy - 35), (cx + 30, cy - 35)]

        draw.polygon(arrow_pts, fill=theme_color)

        bbox_m = draw.textbbox((0, 0), direction, font=font_main)
        w_m = bbox_m[2] - bbox_m[0]
        h_m = bbox_m[3] - bbox_m[1]

        text_y = cy + 25
        draw.text(((W - w_m) // 2, text_y), direction, fill=theme_color, font=font_main)

        bbox_s = draw.textbbox((0, 0), session_text, font=font_sub)
        w_s = bbox_s[2] - bbox_s[0]
        draw.text(((W - w_s) // 2, text_y + h_m + 18), session_text, fill='#8A99AD', font=font_sub)

    draw.rectangle([12, 12, W - 12, H - 12], outline=theme_color, width=3)
    draw.rectangle([18, 18, W - 18, H - 18], outline='#00B0FF' if is_update else '#D4AF37', width=2)

    footer_text = "⚡ JAY FX PREMIUM SIGNALS ⚡"
    bbox_f = draw.textbbox((0, 0), footer_text, font=font_footer)
    w_f = bbox_f[2] - bbox_f[0]
    draw.text(((W - w_f) // 2, H - 52), footer_text, fill='#00B0FF' if is_update else '#D4AF37', font=font_footer)

    bio = BytesIO()
    bio.name = 'jay_card.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio


def generate_performance_card(title, win_rate, total_pips, total_trades, wins, losses):
    """
    Generates high-impact Performance Tracker Cards with Yellow Text on a Black Background.
    """
    W, H = 1000, 562
    img = Image.new('RGB', (W, H), color='#050505')
    draw = ImageDraw.Draw(img)

    YELLOW = '#FFD700'
    DARK_YELLOW = '#FFC107'
    WHITE = '#FFFFFF'
    GRAY = '#8A99AD'

    try:
        font_header = ImageFont.truetype("DejaVuSans-Bold.ttf", 34)
        font_big_stat = ImageFont.truetype("DejaVuSans-Bold.ttf", 54)
        font_label = ImageFont.truetype("DejaVuSans-Bold.ttf", 22)
        font_footer = ImageFont.truetype("DejaVuSans-Bold.ttf", 24)
    except Exception:
        font_header = font_big_stat = font_label = font_footer = ImageFont.load_default()

    # Outer Double Borders
    draw.rectangle([12, 12, W - 12, H - 12], outline=YELLOW, width=3)
    draw.rectangle([18, 18, W - 18, H - 18], outline=DARK_YELLOW, width=1)

    # Title Banner
    bbox_h = draw.textbbox((0, 0), title, font=font_header)
    w_h = bbox_h[2] - bbox_h[0]
    draw.text(((W - w_h) // 2, 40), title, fill=YELLOW, font=font_header)
    draw.line([((W - w_h) // 2 + 20, 90), ((W + w_h) // 2 - 20, 90)], fill=DARK_YELLOW, width=3)

    # Core Metric Boxes (Win Rate & Total Pips)
    draw.rectangle([80, 120, 460, 260], outline=YELLOW, width=2, fill='#0F0F0F')
    draw.text((100, 135), "WIN RATE", fill=GRAY, font=font_label)
    bbox_wr = draw.textbbox((0, 0), win_rate, font=font_big_stat)
    w_wr = bbox_wr[2] - bbox_wr[0]
    draw.text((270 - (w_wr // 2), 175), win_rate, fill=YELLOW, font=font_big_stat)

    draw.rectangle([540, 120, 920, 260], outline=YELLOW, width=2, fill='#0F0F0F')
    draw.text((560, 135), "TOTAL NET PIPS", fill=GRAY, font=font_label)
    bbox_tp = draw.textbbox((0, 0), total_pips, font=font_big_stat)
    w_tp = bbox_tp[2] - bbox_tp[0]
    draw.text((730 - (w_tp // 2), 175), total_pips, fill=YELLOW, font=font_big_stat)

    # Detailed Stats Rows
    stats_y = 300
    row_height = 45

    stats = [
        ("TOTAL SIGNALS ISSUED", total_trades),
        ("TAKE PROFIT WINS", wins),
        ("STOP LOSSES HIT", losses)
    ]

    for label, val in stats:
        draw.rectangle([80, stats_y, 920, stats_y + row_height], outline='#222222', fill='#0A0A0A')
        draw.text((100, stats_y + 10), label, fill=WHITE, font=font_label)
        bbox_v = draw.textbbox((0, 0), val, font=font_label)
        w_v = bbox_v[2] - bbox_v[0]
        draw.text((900 - w_v, stats_y + 10), val, fill=YELLOW, font=font_label)
        stats_y += row_height + 10

    # Footer
    footer_text = "⚡ JAY FX PERFORMANCE TRACKER ⚡"
    bbox_f = draw.textbbox((0, 0), footer_text, font=font_footer)
    w_f = bbox_f[2] - bbox_f[0]
    draw.text(((W - w_f) // 2, H - 50), footer_text, fill=YELLOW, font=font_footer)

    bio = BytesIO()
    bio.name = 'performance_card.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio
