import requests
import pprint
import configparser
import json
import re
import time
from bs4 import BeautifulSoup
from pushover import Client

class Site:
    def __init__(self):
        config = configparser.ConfigParser()
        config.read('settings.ini')
        settings = config['Settings']
        self.email = settings['Email']
        self.center = settings['Center']
        self.password = settings['Password']
        self.data_file = settings['DataFile']
        self.activities = settings['Activities'].split(',')
        self.level = int(settings['Level'])
        self.sleep = int(settings['Sleep'])
        self.log_enabled = settings['Log'] == 'True'
        self.pushover_client = Client(
            settings['PushoverUserKey'],
            api_token=settings['PushoverApiToken']
        )
        with open(self.data_file, 'r') as f:
            self.data = json.load(f)
        self._login()

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

    # Main entry point into this class
    def update(self, save):
        new = self._get_all_flat()
        added = self._calculate_diff(new)
        msg = self._send_if_needed(added)
        if msg is not None:
            print(f'Sent: {msg}')
        if save:
            self._save(new)
        return added

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
                if l[1].get('src', '?') == '/module-inscriptions/images/planning-vert.svg':
                    onclick = l[1].get('onclick', '?')
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
                last_capacity = s[3].strip()

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

    def _send_if_needed(self, added):
        if len(added) > 0:
            msg = self._format_message(added)
            self.pushover_client.send_message(msg, title="Mon Centre Aquatique")
            return msg

    def _save(self, new):
        self.data = new
        with open(self.data_file, 'w') as f:
            json.dump(self.data, f, indent=2)

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
            d = site.update(save=True)
            print(d)
        except Exception as e:
            print(f'Error: {e}')

        time.sleep(site.sleep)

