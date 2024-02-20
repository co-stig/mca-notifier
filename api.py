import traceback
import requests
import pprint
import configparser
import json
import re
import time
from bs4 import BeautifulSoup
from pushover import Client
from oauth2client import client, file, tools
from googleapiclient.http import build_http
from googleapiclient import discovery


class Site:
    def __init__(self):
        config = configparser.ConfigParser()
        config.read('settings.ini')
        settings = config['Settings']
        self.email = settings['Email']
        self.center = settings['Center']
        self.password = settings['Password']
        self.data_file = settings['DataFile']
        self.calendar_file = settings['CalendarFile']
        self.activities = settings['Activities'].split(',')
        self.level = int(settings['Level'])
        self.sleep = int(settings['Sleep'])
        self.log_enabled = settings['Log'] == 'True'
        self.calendar_id = settings['CalendarId']

        # Initialize Google Calendar client
        if self.calendar_id:
            self._initialize_calendar_client()

        # Initialize Pushover client
        self.pushover_client = Client(
            settings['PushoverUserKey'],
            api_token=settings['PushoverApiToken']
        )

        # Read existing data and calendar events
        with open(self.data_file, 'r') as f:
            self.data = json.load(f)
        with open(self.calendar_file, 'r') as f:
            self.calendar_data = json.load(f)

        # Login into MCA
        self._login()

    def _initialize_calendar_client(self):
        flow = client.flow_from_clientsecrets(
            "client_secrets.json",
            scope="https://www.googleapis.com/auth/calendar.events"
        )
        storage = file.Storage("calendar.dat")
        credentials = storage.get()
        if credentials is None or credentials.invalid:
            credentials = tools.run_flow(flow, storage)
        http = credentials.authorize(http=build_http())
        self.calendar_client = discovery.build("calendar", "v3", http=http)

    def _add_calendar_event(self, name, date, time_from, time_to):
        return self.calendar_client.events().quickAdd(
            calendarId=self.calendar_id,
            text=f'{name} on {date} {time_from} - {time_to}'
        ).execute()

    def _get_all_nested(self):
        json_all = {}
        for activity in self.activities:
            json_activity = {}
            all_periods = self._get_periods(activity)
            for period in all_periods:
                json_period = {}
                all_tarifs = self._get_tarifs(activity, self.level, period)
                for tarif in all_tarifs:
                    json_tarif = {}
                    all_slots = self._get_availabilities(self.level, period, tarif)
                    for slot in all_slots:
                        s = all_slots[slot]
                        json_tarif[slot] = {
                            "period": all_periods[period],
                            "tarif": all_tarifs[tarif]
                        }
                    json_period[tarif] = json_tarif
                json_activity[period] = json_period
            json_all[activity] = json_activity
        return json_all

    def _get_all_flat(self):
        flat = list()
        for activity in self.activities:
            all_periods = self._get_periods(activity)
            for period in all_periods:
                all_tarifs = self._get_tarifs(activity, self.level, period)
                for tarif in all_tarifs:
                    all_slots = self._get_availabilities(self.level, period, tarif)
                    for slot in all_slots:
                        s = all_slots[slot]
                        flat.append({
                            "period": all_periods[period],
                            "period_id": period,
                            "tarif": all_tarifs[tarif].replace('&eacute;', 'é'),
                            "tarif_id": tarif,
                            "activity": activity,
                            "slot_id": slot,
                            "date": s['date'],
                            "time": s['time'],
                            "duration": s['duration'],
                            "capacity": s['capacity'],
                        })
        return flat

    def _get_all_events_flat(self):
        flat = list()

        reservations = self._send_get(f'espace-perso/reservations/')
        self._log(reservations, f"Getting list of reservations")
        soup = BeautifulSoup(reservations.text, 'html.parser')

        for table in soup.find_all('table'):
            for tr in list(table.children):
                if tr.name == 'tr':
                    l = list(tr.children)
                    if len(l) == 5:
                        if list(l[1].children)[0].strip() == 'Activité:':
                            descr = list(l[3].children)[0].strip()
                            # Aquabiking Noir le vendredi 29/07/2022 de 18h15 à 19h00 (45 minutes)
                            m = re.search("(.+) le .+ (\\d+)/(\\d+)/(\\d+) de (\\d+)h(\\d+) à (\\d+)h(\\d+) .+", descr)
                            if m is not None:
                                flat.append({
                                    'event_type': m.group(1),
                                    'event_date': f'{m.group(4)}-{m.group(3)}-{m.group(2)}',
                                    'event_from': f'{m.group(5)}:{m.group(6)}',
                                    'event_to': f'{m.group(7)}:{m.group(8)}',
                                })
        return flat

    # Main entry point into this class
    def update(self, save):
        new = self._get_all_flat()
        added = self._calculate_diff(new)
        msg = self._send_if_needed(added)
        if msg is not None:
            print(f'Sent: {msg}')
        if save:
            self._save(new)

        new_events = self._get_all_events_flat()
        added_events = self._calculate_events_diff(new_events)
        if self.calendar_id:
            self._create_events(added_events)
        if save:
            self._save_calendar(new_events)

        return added, added_events

    def _send_get(self, url):
        return self.session.get(
            f'https://moncentreaquatique.com/{url}',
            headers={
                'User-Agent': 'Mozilla/5.0',
                'Host': 'moncentreaquatique.com',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-User': '?1',
                'Cache-Control': 'max-age=0',
            },
            cookies=self.cookies
        )

    def _get_periods(self, activity):
        res = dict()
        act = self._send_get(f'module-inscriptions/activite/?activite={activity}')
        self._log(act, f"Select activity {activity}")
        for line in act.text.split('\n'):
            if line.startswith("<option  value='"):
                m = re.search("<option  value='(.+)'>(.+)", line)
                res[m.group(1)] = m.group(2)
        print(f'Periods: {res}')
        print()
        return res

    def _get_tarifs(self, activity, level, period):
        res = dict()
        tarifs = self._send_get(f'module-inscriptions/activite/?scroll=content&activite={activity}&niveau={level}&periode={period}')
        self._log(tarifs, f"Select period {period}")
        for line in tarifs.text.split('\n'):
            if line.startswith("<option value='"):
                m = re.search("<option value='(.+)'>(.+)", line)
                res[m.group(1)] = m.group(2)
        print(f'Tarifs: {res}')
        print()
        return res

    def _get_availabilities(self, level, period, tarif):
        res = dict()
        print(f'URL: module-inscriptions/creneaux/?scroll=content&niveau={level}&periode={period}&tarif={tarif}')
        avail = self._send_get(f'module-inscriptions/creneaux/?scroll=content&niveau={level}&periode={period}&tarif={tarif}')
        self._log(avail, f"Select tarif {tarif}")

        soup = BeautifulSoup(avail.text, 'html.parser')

        last_date = None
        last_time = None
        last_duration = None
        last_capacity = None
        last_id = None

        for td in soup.find_all('td'):
            style = td.get('style', '/')
            if style == 'padding:20px;text-align:left;vertical-align:middle;font-weight:900;font-size:24px;color:#1c5861;padding-right:50px;':
                l = list(td.children)
                last_date = str(l[0]).strip() + ', ' + str(l[2]).strip()
            elif style == 'padding:20px;text-align:left;vertical-align:middle;padding-right:50px;':
                l = list(td.children)
                s = list(l[1].children)
                last_capacity = s[2].strip()
                if s[1].get('src', '?') == '/module-inscriptions/images/personne_vert.svg':
                    onclick = l[8].get('onclick', '?')
                    m = re.search('afficher_popup_reserver\((.+?),', onclick)
                    last_id = m.group(1)
                    res[last_id] = {
                        "date": last_date,
                        "time": last_time,
                        "duration": last_duration,
                        "capacity": last_capacity,
                    }
            elif style == 'vertical-align:middle;':
                l = list(td.children)
                last_time = list(l[1].children)[0].replace('\xa0', ' ')
                s = list(l[5].children)
                last_duration = s[1].strip()

        print(f'Availabilities: {res}')
        print()
        return res

    def _activity_to_str(self, a):
        if a == '109':
            return 'Aquabiking Noir'
        elif a == '48':
            return 'Aquaboxing'
        else:
            return 'UNKNOWN ACTIVITY'

    def _format_message(self, added):
        res = f'Il y a {len(added)} nouveaux créneaux: \n\n'
        for a in added:
            res += f' - {self._activity_to_str(a["activity"])} à {a["date"]} {a["time"]} pour {a["tarif"]}: {a["capacity"]}\n\n'
        return res

    def _calculate_diff(self, new):
        old = self.data
        print (f'Calculating diff between {len(old)} and {len(new)}')
        added = list()
        for n in new:
            is_added = True
            for o in old:
                if n['period_id'] == o['period_id'] \
                and n['tarif_id'] == o['tarif_id'] \
                and n['slot_id'] == o['slot_id']:
                    is_added = False
                    break
            if is_added:
                added.append(n)
        return added

    def _calculate_events_diff(self, new):
        old = self.calendar_data
        print (f'Calculating events diff between {len(old)} and {len(new)}')
        added = list()
        for n in new:
            is_added = True
            for o in old:
                if n['event_type'] == o['event_type'] \
                and n['event_date'] == o['event_date'] \
                and n['event_from'] == o['event_from']:
                    is_added = False
                    break
            if is_added:
                added.append(n)
        return added

    def _send_if_needed(self, added):
        if len(added) > 0:
            msg = self._format_message(added)
            self.pushover_client.send_message(msg, title="Mon Centre Aquatique")
            return msg

    def _create_events(self, added_events):
        for e in added_events:
            self._add_calendar_event(e['event_type'], e['event_date'], e['event_from'], e['event_to'])

    def _save(self, new):
        self.data = new
        with open(self.data_file, 'w') as f:
            json.dump(self.data, f, indent=2)

    def _save_calendar(self, new):
        self.calendar_data = new
        with open(self.calendar_file, 'w') as f:
            json.dump(self.calendar_data, f, indent=2)

    def _log(self, res, name):
        if self.log_enabled:
            print(f'*** {name} ***')
            print(f'URL: {res.url}')
            print(f'Status: {res.status_code}')
            print(f'Headers: {res.headers}')
            print(f'Encoding: {res.encoding}')
            print(f'Cookies: {res.cookies.get_dict()}')
            print(f'Text: {len(res.text)}')
            print()

    def _login(self):
        self.session = requests.Session()
        self.cookies = requests.cookies.RequestsCookieJar()
        self.cookies.set('OKSES', 'o6up7mham4dih0nsahkdf3u1n9', domain='moncentreaquatique.com', path='/')

        res = requests.post(
            'https://moncentreaquatique.com/espace-perso/connexion/',
            headers={'User-Agent': 'Mozilla/5.0'},
            data={'email': self.email, 'password': self.password},
            cookies=self.cookies
        )
        self._log(res, "Login")

        res = self._send_get(f'module-inscriptions/?centre={self.center}')
        self._log(res, "Select center")


if __name__ == '__main__':
    site = Site()
    while True:
        try:
            d, e = site.update(save=True)
            print(d)
            print(e)
        except Exception as e:
            print(f'Error: {e}')
            print(traceback.format_exc())            

        time.sleep(site.sleep)

