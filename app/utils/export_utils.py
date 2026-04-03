import csv
import io
from datetime import datetime


def generate_session_csv(session, checkins):
    """Generate CSV export for a corporate session."""
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['ScanMark — Session Report'])
    writer.writerow(['Session:', session.name])
    writer.writerow(['Type:', session.session_type.title()])
    writer.writerow(['Date:', session.date.strftime('%Y-%m-%d')])
    writer.writerow(['Start Time:', session.start_time.strftime('%H:%M')])
    writer.writerow(['Total Check-ins:', len(checkins)])
    writer.writerow([])
    writer.writerow(['Name', 'Employee ID', 'Check-in Time', 'Status'])
    
    for c in checkins:
        writer.writerow([
            c.name,
            c.employee_id or '',
            c.checkin_time.strftime('%Y-%m-%d %H:%M:%S') if c.checkin_time else '',
            'Late' if c.is_late else 'On Time'
        ])
    
    if not session.open_attendance:
        expected = list(session.expected_attendees.all())
        checked_ids = {c.employee_id for c in checkins if c.employee_id}
        checked_names = {c.name.lower() for c in checkins}
        missing = [e for e in expected if e.employee_id not in checked_ids and e.name.lower() not in checked_names]
        
        if missing:
            writer.writerow([])
            writer.writerow(['MISSING ATTENDEES'])
            writer.writerow(['Name', 'Employee ID'])
            for m in missing:
                writer.writerow([m.name, m.employee_id or ''])
    
    output.seek(0)
    return output.getvalue()


def generate_event_csv(event, checkins, attendees):
    """Generate CSV export for an event."""
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['ScanMark — Event Report'])
    writer.writerow(['Event:', event.name])
    writer.writerow(['Date:', event.date.strftime('%Y-%m-%d')])
    writer.writerow(['Venue:', event.venue or ''])
    writer.writerow(['Total Registered:', len(attendees)])
    writer.writerow(['Total Checked In:', len(checkins)])
    writer.writerow(['Attendance Rate:', f'{event.attendance_rate()}%'])
    writer.writerow([])
    writer.writerow(['Name', 'Email', 'Ticket Ref', 'Status', 'Check-in Time', 'Type'])
    
    checkin_map = {}
    for c in checkins:
        if c.attendee_id:
            checkin_map[c.attendee_id] = c
    
    for a in attendees:
        c = checkin_map.get(a.id)
        writer.writerow([
            a.name,
            a.email or '',
            a.ticket_ref or '',
            'Checked In' if c else 'Not Arrived',
            c.checkin_time.strftime('%Y-%m-%d %H:%M:%S') if c else '',
            'Walk-in' if a.is_walkin else 'Pre-registered'
        ])
    
    output.seek(0)
    return output.getvalue()
