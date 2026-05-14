import requests
import json
import re
import os
import urllib3
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pytz

# 1. DISABILITA WARNING SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def generate_time_slots():
    slots = []
    start_time = datetime.strptime("08:00", "%H:%M")
    end_time = datetime.strptime("19:30", "%H:%M")
    while start_time < end_time:
        next_time = start_time + timedelta(minutes=30)
        slots.append(f"{start_time.strftime('%H:%M')}-{next_time.strftime('%H:%M')}")
        start_time = next_time
    return slots

def split_schedule(schedule):
    base_slots = generate_time_slots()
    extra_slots = set()
    expanded_times = {}
    
    for day, times in schedule.items():
        expanded_times[day] = {}
        for time_range, activity in times.items():
            if activity:
                try:
                    start, end = time_range.split("-")
                    curr = datetime.strptime(start, "%H:%M")
                    last = datetime.strptime(end, "%H:%M")
                    while curr < last:
                        next_t = curr + timedelta(minutes=30)
                        slot = f"{curr.strftime('%H:%M')}-{next_t.strftime('%H:%M')}"
                        expanded_times[day][slot] = activity
                        if slot not in base_slots:
                            extra_slots.add(slot)
                        curr = next_t
                except ValueError:
                    continue

    all_slots = base_slots + sorted(list(extra_slots))
    normalized = {day: {slot: "" for slot in all_slots} for day in schedule.keys()}
    for day in expanded_times:
        for slot, activity in expanded_times[day].items():
            normalized[day][slot] = activity
    return normalized

def merge_time_slots(normalized_schedule):
    if not normalized_schedule:
        return {}
    half_hour_slots = list(next(iter(normalized_schedule.values())).keys())
    new_schedule = {day: {} for day in normalized_schedule}
    i = 0
    while i < len(half_hour_slots):
        slot1 = half_hour_slots[i]
        if i + 1 < len(half_hour_slots):
            slot2 = half_hour_slots[i+1]
            can_merge = True
            for day in normalized_schedule:
                v1, v2 = normalized_schedule[day][slot1], normalized_schedule[day][slot2]
                if not ((v1 == "" and v2 == "") or (v1 == v2 and v1 != "")):
                    can_merge = False
                    break
            if can_merge:
                merged = f"{slot1.split('-')[0]}-{slot2.split('-')[1]}"
                for day in normalized_schedule:
                    new_schedule[day][merged] = normalized_schedule[day][slot1] or normalized_schedule[day][slot2]
                i += 2
            else:
                for day in normalized_schedule:
                    new_schedule[day][slot1] = normalized_schedule[day][slot1]
                    new_schedule[day][slot2] = normalized_schedule[day][slot2]
                i += 2
        else:
            for day in normalized_schedule:
                new_schedule[day][slot1] = normalized_schedule[day][slot1]
            i += 1
    return new_schedule

def get_classroom_schedule():
    if not os.path.exists('data'):
        os.makedirs('data')

    url = "https://gomppublic.uniroma1.it/ScriptService/OffertaFormativa/Ofs.6.0/AuleOrariScriptService/GenerateOrarioAula.aspx"
    tz = pytz.timezone("Europe/Rome")
    start_day = datetime.now(tz)

    if start_day.weekday() >= 5:
        start_day += timedelta(days=(7 - start_day.weekday()))

    start_of_week = start_day - timedelta(days=start_day.weekday())
    end_of_week = start_of_week + timedelta(days=4)
    start_date_str = start_of_week.strftime("%Y/%m/%d")
    date_range = f"{start_of_week.strftime('%A %d %B %Y')} - {end_of_week.strftime('%A %d %B %Y')}"

    days_mapping = {
        "Lunedì": "monday", "Martedì": "tuesday", "Mercoledì": "wednesday",
        "Giovedì": "thursday", "Venerdì": "friday"
    }

    classrooms = {"T1": "RM113-E01PTEL001", "S1": "RM113-E01PINL001"}

    for room_name, codice in classrooms.items():
        params = json.dumps({"controlID": "schedule", "codiceInterno": codice, "displayMode": "OnlyAule", "startDate": start_date_str})
        query_params = {"params": params, "_": str(int(datetime.now().timestamp()))}
        
        response = requests.get(url, params=query_params, verify=False)
        
        if response.status_code == 200:
            # 1. FORZIAMO UTF-8 per evitare la mojibake (â€“)
            response.encoding = 'utf-8'
            
            match = re.search(r'\.html\("(.+?)"\);', response.text, re.DOTALL)
            if match:
                raw_content = match.group(1)
                
                # 2. FIX ROBUSTO ENCODING: 
                # Converte i caratteri speciali in \uXXXX letterali e poi li decodifica tutti insieme.
                # Questo evita l'errore 'latin-1' e pulisce gli escape come \"
                html_content = raw_content.encode('ascii', 'backslashreplace').decode('unicode_escape')
                
                soup = BeautifulSoup(html_content, 'html.parser')
                header_row = next((tr for tr in soup.find_all('tr') if tr.find('th', class_='Orario')), None)
                days = [th.get_text(strip=True) for th in header_row.find_all('th')[1:]] if header_row else []
                days = [d for d in days if d in days_mapping]

                schedule = {days_mapping[day]: {} for day in days}
                for row in soup.find_all('tr'):
                    ts_cell = row.find('td', class_='orario')
                    if ts_cell:
                        timeslot = "-".join(ts_cell.stripped_strings)
                        cells = row.find_all('td')[1:]
                        for day, cell in zip(days, cells):
                            schedule[days_mapping[day]][timeslot] = " ".join(cell.stripped_strings)

                final = merge_time_slots(split_schedule(schedule))
                output = {"date_range": date_range, "timetables": final}

                with open(f"data/timetables_classrooms_{room_name}.json", "w", encoding="utf-8") as f:
                    json.dump(output, f, indent=4, ensure_ascii=False)
                
                print(f"Scrape completato per {room_name}")

if __name__ == "__main__":
    get_classroom_schedule()
