from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from io import BytesIO
from datetime import datetime


BLUE = colors.HexColor('#3b82f6')
DARK = colors.HexColor('#111111')
GRAY = colors.HexColor('#737373')
LIGHT = colors.HexColor('#f4f4f4')
RED  = colors.HexColor('#ef4444')
GREEN = colors.HexColor('#16a34a')


def _base_doc(buffer, title):
    return SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=20*mm, leftMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm,
        title=title
    )


def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle('ScanTitle', fontSize=18, textColor=DARK, spaceAfter=4, fontName='Helvetica-Bold'))
    s.add(ParagraphStyle('ScanSub',   fontSize=11, textColor=GRAY, spaceAfter=16))
    s.add(ParagraphStyle('ScanLabel', fontSize=9,  textColor=GRAY, fontName='Helvetica'))
    s.add(ParagraphStyle('ScanMono',  fontSize=9,  fontName='Courier'))
    return s


def _header_table(rows):
    """Renders a 2-column key/value metadata block."""
    data = [[Paragraph(f'<b>{k}</b>', ParagraphStyle('k', fontSize=9, textColor=GRAY)),
             Paragraph(str(v), ParagraphStyle('v', fontSize=9, textColor=DARK))]
            for k, v in rows]
    t = Table(data, colWidths=[45*mm, 120*mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), LIGHT),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [LIGHT, colors.white]),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
    ]))
    return t


def _checkin_table(checkins):
    header = [['#', 'Name', 'Employee ID', 'Time', 'Status']]
    data = header + [
        [str(i+1), c.name, c.employee_id or '—',
         c.checkin_time.strftime('%H:%M:%S') if c.checkin_time else '—',
         'Late' if c.is_late else 'On time']
        for i, c in enumerate(checkins)
    ]
    col_w = [10*mm, 55*mm, 35*mm, 25*mm, 20*mm]
    t = Table(data, colWidths=col_w, repeatRows=1)
    style = [
        ('BACKGROUND',   (0,0), (-1,0), BLUE),
        ('TEXTCOLOR',    (0,0), (-1,0), colors.white),
        ('FONTNAME',     (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',     (0,0), (-1,-1), 9),
        ('ROWBACKGROUNDS',(0,1),(-1,-1), [colors.white, LIGHT]),
        ('TOPPADDING',   (0,0), (-1,-1), 5),
        ('BOTTOMPADDING',(0,0), (-1,-1), 5),
        ('LEFTPADDING',  (0,0), (-1,-1), 6),
        ('GRID',         (0,0), (-1,-1), 0.25, colors.HexColor('#dddddd')),
    ]
    for i, c in enumerate(checkins, 1):
        col = RED if c.is_late else GREEN
        style.append(('TEXTCOLOR', (4,i), (4,i), col))
    t.setStyle(TableStyle(style))
    return t


def generate_session_pdf(session, checkins, expected, missing):
    buffer = BytesIO()
    doc = _base_doc(buffer, session.name)
    s = _styles()
    story = []

    story.append(Paragraph('ScanMark', ParagraphStyle('brand', fontSize=10, textColor=BLUE, fontName='Helvetica-Bold')))
    story.append(Paragraph(session.name, s['ScanTitle']))
    t = 'Training Session' if session.session_type == 'training' else 'Shift'
    if session.is_mandatory:
        t += ' · Mandatory'
    story.append(Paragraph(t, s['ScanSub']))

    story.append(_header_table([
        ('Date', session.date.strftime('%d %B %Y')),
        ('Start time', session.start_time.strftime('%H:%M')),
        ('Dept / Facilitator', session.department or session.facilitator or '—'),
        ('Late threshold', f'{session.late_threshold_minutes} minutes'),
        ('Check-ins', len(checkins)),
        ('Expected', len(expected) if not session.open_attendance else 'Open'),
        ('Generated', datetime.utcnow().strftime('%d %b %Y %H:%M UTC')),
    ]))
    story.append(Spacer(1, 12))

    if missing:
        story.append(Paragraph(f'⚠ {len(missing)} missing attendee{"s" if len(missing)!=1 else ""}',
            ParagraphStyle('warn', fontSize=10, textColor=RED, fontName='Helvetica-Bold', spaceAfter=6)))
        miss_data = [['Name', 'Employee ID']] + [[m.name, m.employee_id or '—'] for m in missing]
        mt = Table(miss_data, colWidths=[90*mm, 50*mm])
        mt.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), RED),
            ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
            ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE',   (0,0), (-1,-1), 9),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#fff5f5'), colors.white]),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(mt)
        story.append(Spacer(1, 12))

    story.append(Paragraph('Check-in record',
        ParagraphStyle('sh', fontSize=10, textColor=DARK, fontName='Helvetica-Bold', spaceAfter=8)))

    if checkins:
        story.append(_checkin_table(checkins))
    else:
        story.append(Paragraph('No check-ins recorded for this session.', s['ScanLabel']))

    doc.build(story)
    return buffer.getvalue()


def generate_event_pdf(event, checkins, attendees, intervals):
    buffer = BytesIO()
    doc = _base_doc(buffer, event.name)
    s = _styles()
    story = []

    story.append(Paragraph('ScanMark', ParagraphStyle('brand', fontSize=10, textColor=BLUE, fontName='Helvetica-Bold')))
    story.append(Paragraph(event.name, s['ScanTitle']))
    story.append(Paragraph(
        f"{event.date.strftime('%A, %d %B %Y')}  ·  {event.start_time.strftime('%H:%M')}"
        + (f"  ·  {event.venue}" if event.venue else ''),
        s['ScanSub']))

    checked = len(checkins)
    total = len(attendees)
    rate = round(checked/total*100) if total else 0
    walkins = sum(1 for a in attendees if a.is_walkin)

    story.append(_header_table([
        ('Registered', total),
        ('Checked in', checked),
        ('Attendance rate', f'{rate}%'),
        ('Walk-ins', walkins),
        ('Pre-registered', total - walkins),
        ('No-shows', total - checked),
        ('Generated', datetime.utcnow().strftime('%d %b %Y %H:%M UTC')),
    ]))
    story.append(Spacer(1, 12))

    # Check-in timeline as simple bar table
    if intervals:
        story.append(Paragraph('Check-in timeline (15-min intervals)',
            ParagraphStyle('sh', fontSize=10, textColor=DARK, fontName='Helvetica-Bold', spaceAfter=8)))
        max_v = max(intervals.values()) or 1
        bar_data = [['Time', 'Count', 'Volume']]
        for slot, count in intervals.items():
            bar = '█' * int(count / max_v * 30)
            bar_data.append([slot, str(count), bar])
        bt = Table(bar_data, colWidths=[20*mm, 15*mm, 110*mm])
        bt.setStyle(TableStyle([
            ('BACKGROUND',   (0,0), (-1,0), BLUE),
            ('TEXTCOLOR',    (0,0), (-1,0), colors.white),
            ('FONTNAME',     (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTNAME',     (2,1), (2,-1), 'Courier'),
            ('TEXTCOLOR',    (2,1), (2,-1), BLUE),
            ('FONTSIZE',     (0,0), (-1,-1), 8),
            ('ROWBACKGROUNDS',(0,1),(-1,-1), [colors.white, LIGHT]),
            ('TOPPADDING',   (0,0), (-1,-1), 4),
            ('BOTTOMPADDING',(0,0), (-1,-1), 4),
            ('LEFTPADDING',  (0,0), (-1,-1), 6),
        ]))
        story.append(bt)
        story.append(Spacer(1, 12))

    # Full attendee list
    story.append(Paragraph('Full attendee list',
        ParagraphStyle('sh', fontSize=10, textColor=DARK, fontName='Helvetica-Bold', spaceAfter=8)))

    checkin_map = {c.attendee_id: c for c in checkins if c.attendee_id}
    att_data = [['#', 'Name', 'Email', 'Type', 'Status', 'Time']]
    for i, a in enumerate(attendees):
        c = checkin_map.get(a.id)
        att_data.append([
            str(i+1), a.name, a.email or '—',
            'Walk-in' if a.is_walkin else 'Registered',
            '✓ In' if c else 'No-show',
            c.checkin_time.strftime('%H:%M') if c else '—'
        ])
    at = Table(att_data, colWidths=[8*mm, 45*mm, 48*mm, 22*mm, 16*mm, 15*mm], repeatRows=1)
    style = [
        ('BACKGROUND',   (0,0), (-1,0), BLUE),
        ('TEXTCOLOR',    (0,0), (-1,0), colors.white),
        ('FONTNAME',     (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',     (0,0), (-1,-1), 8),
        ('ROWBACKGROUNDS',(0,1),(-1,-1), [colors.white, LIGHT]),
        ('TOPPADDING',   (0,0), (-1,-1), 4),
        ('BOTTOMPADDING',(0,0), (-1,-1), 4),
        ('LEFTPADDING',  (0,0), (-1,-1), 5),
        ('GRID',         (0,0), (-1,-1), 0.25, colors.HexColor('#dddddd')),
    ]
    for i, a in enumerate(attendees, 1):
        c = checkin_map.get(a.id)
        style.append(('TEXTCOLOR', (4,i), (4,i), GREEN if c else GRAY))
    at.setStyle(TableStyle(style))
    story.append(at)

    doc.build(story)
    return buffer.getvalue()