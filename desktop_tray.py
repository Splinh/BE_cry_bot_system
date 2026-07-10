import time
import threading
import sys
import requests
from PIL import Image, ImageDraw, ImageFont
import pystray

# Global control variables
icon = None
running = True

# Parse command line argument for the coin (e.g. BTC, ETH, SOL)
LABEL = "BTC"
if len(sys.argv) > 1:
    LABEL = sys.argv[1].upper()

SYMBOL = f"{LABEL}USDT"
BINANCE_API_URL = f"https://api.binance.com/api/v3/ticker/24hr?symbol={SYMBOL}"

def get_crypto_price_info():
    """Fetch current price and 24h change from Binance public API."""
    try:
        r = requests.get(BINANCE_API_URL, timeout=5)
        if r.status_code == 200:
            data = r.json()
            price = float(data.get("lastPrice", 0.0))
            change = float(data.get("priceChangePercent", 0.0))
            return price, change
    except Exception:
        pass
    return None, None

def create_price_icon(price_text_lines, is_up=True):
    """
    Generate a 32x32 image with the price text drawn on two lines.
    Green for positive, red for negative.
    """
    # Create RGBA image with transparent background
    img = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Neon Green for Up, Bright Red for Down
    color = (34, 197, 94, 255) if is_up else (239, 68, 68, 255)
    
    try:
        # Load Arial Bold fonts (standard on Windows)
        font_large = ImageFont.truetype("arialbd.ttf", 15)
        font_small = ImageFont.truetype("arialbd.ttf", 12)
    except IOError:
        # Fallback to default if Arial Bold is not found
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()
        
    line1, line2 = price_text_lines
        
    # Draw Line 1 (Large) - Centered Horizontally on top half
    try:
        bbox1 = draw.textbbox((0, 0), line1, font=font_large)
        w1 = bbox1[2] - bbox1[0]
        x1 = (32 - w1) // 2
        draw.text((x1, 1), line1, fill=color, font=font_large)
    except Exception:
        draw.text((4, 1), line1, fill=color, font=font_large)
        
    # Draw Line 2 (Small) - Centered Horizontally on bottom half
    if line2:
        try:
            bbox2 = draw.textbbox((0, 0), line2, font=font_small)
            w2 = bbox2[2] - bbox2[0]
            x2 = (32 - w2) // 2
            draw.text((x2, 16), line2, fill=color, font=font_small)
        except Exception:
            draw.text((8, 16), line2, fill=color, font=font_small)
            
    return img

def update_loop():
    """Background thread to query price and update system tray icon."""
    global icon, running
    last_price = 0.0
    current_change = 0.0
    
    while running:
        price, change = get_crypto_price_info()
        if price is not None:
            is_up = change >= 0
            last_price = price
            current_change = change
            
            # Format price
            price_int = int(round(price))
            price_str = str(price_int)
            
            # Split digits into two lines to fit nicely in 32x32 icon
            if len(price_str) == 4:    # E.g. ETH (1736 -> "17" and "36")
                line1 = price_str[:2]
                line2 = price_str[2:]
            elif len(price_str) == 5:  # E.g. BTC (62500 -> "625" and "00")
                line1 = price_str[:3]
                line2 = price_str[3:]
            elif len(price_str) == 6:  # E.g. BTC 100k+ (102500 -> "102" and "50")
                line1 = price_str[:3]
                line2 = price_str[3:5]
            else:
                line1 = price_str
                line2 = ""
            
            # Update tray icon image
            img = create_price_icon((line1, line2), is_up)
            icon.icon = img
            
            # Update dynamic hover tooltip text
            icon.title = f"{LABEL}: ${price:,.2f} ({change:+.2f}%)"
            
        time.sleep(5)  # Refresh price every 5 seconds

def show_notification(icon, item):
    """Trigger a Windows balloon notification with current price details."""
    price, change = get_crypto_price_info()
    if price is not None:
        title = f"Cập nhật {LABEL}"
        message = f"Giá hiện tại: ${price:,.2f}\nBiến động 24h: {change:+.2f}%"
        icon.notify(message, title)

def on_quit(icon, item):
    """Callback when user clicks 'Exit' in system tray menu."""
    global running
    running = False
    icon.stop()

def main():
    global icon
    
    # Initial placeholder icon
    img = create_price_icon(("...", ""), True)
    
    # Create menu
    menu = pystray.Menu(
        pystray.MenuItem('Hiện thông báo (Notify)', show_notification),
        pystray.MenuItem('Cập nhật ngay (Refresh)', show_notification),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Thoát (Exit)', on_quit)
    )
    
    # Create Icon with initial title/tooltip
    icon = pystray.Icon(f"crypto_{LABEL.lower()}_tray", img, f"{LABEL} Price: Loading...", menu)
    
    # Start background update thread
    t = threading.Thread(target=update_loop)
    t.daemon = True
    t.start()
    
    # Run the pystray main loop
    icon.run()

if __name__ == "__main__":
    main()
