from flask import current_app, render_template_string
from flask_mail import Message
from app import mail


def send_password_reset_email(user, token):
    try:
        reset_url = f"{current_app.config['APP_URL']}/auth/reset-password/{token}"
        msg = Message(
            subject='Reset your ScanMark password',
            recipients=[user.email],
        )
        msg.html = f"""
        <div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto; padding: 40px 20px; background: #0f0f0f; color: #e5e5e5;">
            <h1 style="font-size: 24px; color: #ffffff; margin-bottom: 8px;">Reset your password</h1>
            <p style="color: #a3a3a3; margin-bottom: 32px;">Hi {user.full_name}, we received a request to reset your ScanMark password.</p>
            <a href="{reset_url}" style="display: inline-block; background: #3b82f6; color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: 600;">Reset Password</a>
            <p style="color: #737373; font-size: 14px; margin-top: 32px;">This link expires in 2 hours. If you didn't request this, you can safely ignore this email.</p>
        </div>
        """
        mail.send(msg)
    except Exception as e:
        current_app.logger.error(f'Failed to send password reset email: {e}')


def send_attendee_qr_email(attendee, event, qr_image_path):
    """Send personalised QR code to event attendee."""
    try:
        msg = Message(
            subject=f'Your ticket for {event.name}',
            recipients=[attendee.email],
        )
        with open(qr_image_path, 'rb') as f:
            msg.attach('ticket_qr.png', 'image/png', f.read(), 'inline', headers=[('Content-ID', '<qr_code>')])
        msg.html = f"""
        <div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto; padding: 40px 20px; background: #0f0f0f; color: #e5e5e5;">
            <h1 style="font-size: 24px; color: #ffffff;">You're registered for {event.name}</h1>
            <p style="color: #a3a3a3;">Hi {attendee.name}, here's your personal QR code for check-in. Please have it ready at the door.</p>
            <div style="text-align: center; margin: 32px 0;">
                <img src="cid:qr_code" style="width: 200px; height: 200px; border: 2px solid #3b82f6; border-radius: 12px;" />
            </div>
            <p style="color: #737373; font-size: 14px;"><strong style="color: #a3a3a3;">Date:</strong> {event.date.strftime('%A, %B %d, %Y')}</p>
            <p style="color: #737373; font-size: 14px;"><strong style="color: #a3a3a3;">Venue:</strong> {event.venue or 'TBC'}</p>
            {f'<p style="color: #737373; font-size: 14px;"><strong style="color: #a3a3a3;">Ticket Ref:</strong> {attendee.ticket_ref}</p>' if attendee.ticket_ref else ''}
        </div>
        """
        mail.send(msg)
        return True
    except Exception as e:
        current_app.logger.error(f'Failed to send attendee QR email: {e}')
        return False
