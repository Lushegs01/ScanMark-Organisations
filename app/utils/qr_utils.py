import qrcode
import qrcode.image.svg
from io import BytesIO
import base64
import os


def generate_qr_png_b64(url: str, box_size: int = 10, border: int = 2) -> str:
    """Generate a QR code as base64 PNG string."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=box_size,
        border=border,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color='#ffffff', back_color='#0f0f0f')
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode('utf-8')


def save_qr_png(url: str, filepath: str, box_size: int = 10, border: int = 2):
    """Generate and save a QR code PNG to disk."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=box_size,
        border=border,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color='#ffffff', back_color='#0f0f0f')
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    img.save(filepath, format='PNG')
    return filepath


def generate_qr_svg(url: str) -> str:
    """Generate a QR code as SVG string."""
    factory = qrcode.image.svg.SvgPathImage
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        image_factory=factory,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image()
    buffer = BytesIO()
    img.save(buffer)
    return buffer.getvalue().decode('utf-8')
