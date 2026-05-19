def parse_time(time_str):
    # Parse HH:MM:SS to seconds
    h, m, s = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s

def format_time(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"