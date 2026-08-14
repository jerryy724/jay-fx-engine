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
    except:
        font_header = font_main = font_sub = font_footer = ImageFont.load_default()

    if is_update:
        # Market Brief Style: Electric Blue Text on Pure Dark Slate/Black
        theme_color = '#00B0FF'
        header_text = "★ JAY FX MARKET BRIEF ★"
        main_text = pair_or_title
        sub_text = direction_or_sub

        # Header Drawing
        bbox_h = draw.textbbox((0, 0), header_text, font=font_header)
        w_h = bbox_h[2] - bbox_h[0]
        draw.text(((W - w_h) // 2, 45), header_text, fill='#FFFFFF', font=font_header)
        draw.line([((W - w_h) // 2 + 30, 95), ((W + w_h) // 2 - 30, 95)], fill='#00B0FF', width=3)

        # Handle Long Titles (e.g. "FOREX MARKET INTELLIGENCE") by Splitting into 2 Centered Lines
        words = main_text.strip().split()
        if len(words) > 2:
            line1 = " ".join(words[:2])  # "FOREX MARKET"
            line2 = " ".join(words[2:])  # "INTELLIGENCE"
            
            # Use a slightly scaled font size for double line to fit comfortably
            try:
                font_title_stacked = ImageFont.truetype("DejaVuSans-Bold.ttf", 46)
            except:
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

        # Subtitle Drawing
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
