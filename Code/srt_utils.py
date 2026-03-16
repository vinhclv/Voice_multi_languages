import re

class SRTProcessor:
    @staticmethod
    def time_to_seconds(time_str):
        try:
            hours, minutes, seconds = time_str.split(':')
            seconds, milliseconds = seconds.split(',')
            return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(milliseconds) / 1000.0
        except (ValueError, IndexError):
            return 0.0

    @classmethod
    def parse_timestamps(cls, srt_path):
        timestamps = []
        pattern = re.compile(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})')
        
        try:
            with open(srt_path, 'r', encoding='utf-8-sig') as f:
                content = f.read()
                matches = pattern.findall(content)
                for start_str, end_str in matches:
                    start = cls.time_to_seconds(start_str)
                    end = cls.time_to_seconds(end_str)
                    if end > start:
                        timestamps.append({'start': start, 'end': end})
            return timestamps
        except FileNotFoundError:
            return []