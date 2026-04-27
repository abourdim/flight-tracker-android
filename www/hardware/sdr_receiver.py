#!/usr/bin/env python3
"""
✈️ Planes in the Sky — SDR ADS-B Receiver
Captures live ADS-B (1090 MHz) from an RTL-SDR dongle,
decodes aircraft data, and serves it as JSON for the web app.

REQUIREMENTS:
  pip install pyModeS flask flask-cors
  RTL-SDR dongle plugged in + rtl_sdr drivers installed

USAGE:
  python3 sdr_receiver.py              # auto-detect RTL-SDR
  python3 sdr_receiver.py --port 8090  # custom port
  python3 sdr_receiver.py --dump1090   # use dump1090 as backend
  python3 sdr_receiver.py --lat 48.86 --lon 2.35  # set position

Then in the web app, tap the 📡 SDR button to connect.
"""

import argparse
import json
import math
import subprocess
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime

# === Try imports ===
try:
    import pyModeS as pms
    HAS_PYMS = True
except ImportError:
    HAS_PYMS = False
    print("⚠️  pyModeS not installed. Install with: pip install pyModeS")

try:
    from flask import Flask, jsonify, request
    from flask_cors import CORS
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False
    print("⚠️  Flask not installed. Install with: pip install flask flask-cors")


# ========== ADS-B Decoder ==========
class ADSBTracker:
    """Tracks aircraft from raw ADS-B messages."""

    # ICAO hex address ranges → country
    ICAO_RANGES = [
        (0xA00000, 0xAFFFFF, 'United States'), (0xC00000, 0xC3FFFF, 'Canada'),
        (0xE00000, 0xE3FFFF, 'Argentina'), (0xE40000, 0xE7FFFF, 'Brazil'),
        (0x400000, 0x43FFFF, 'France'), (0x3C0000, 0x3FFFFF, 'Germany'),
        (0x440000, 0x447FFF, 'Germany'), (0x480000, 0x4BFFFF, 'Germany'),
        (0x840000, 0x87FFFF, 'United Kingdom'),
        (0x300000, 0x33FFFF, 'Italy'), (0x340000, 0x37FFFF, 'Spain'),
        (0x380000, 0x3BFFFF, 'Netherlands'), (0x200000, 0x27FFFF, 'India'),
        (0x780000, 0x7BFFFF, 'Japan'), (0x7C0000, 0x7FFFFF, 'Australia'),
        (0x800000, 0x83FFFF, 'China'), (0x880000, 0x887FFF, 'South Korea'),
        (0xD00000, 0xD7FFFF, 'Russia'), (0x710000, 0x7103FF, 'Turkey'),
        (0x740000, 0x7403FF, 'United Arab Emirates'),
        (0x500000, 0x5003FF, 'Saudi Arabia'), (0x008000, 0x00FFFF, 'Egypt'),
        (0x040000, 0x05FFFF, 'Morocco'), (0x4C0000, 0x4C7FFF, 'Norway'),
        (0x4C8000, 0x4CFFFF, 'Sweden'), (0x4D0000, 0x4D03FF, 'Finland'),
        (0x494000, 0x497FFF, 'Switzerland'), (0x470000, 0x477FFF, 'Austria'),
        (0x478000, 0x47FFFF, 'Belgium'), (0x4B8000, 0x4BFFFF, 'Greece'),
        (0x4B0000, 0x4B7FFF, 'Denmark'), (0x501000, 0x501FFF, 'Ireland'),
        (0x010000, 0x017FFF, 'Nigeria'), (0x006000, 0x006FFF, 'South Africa'),
        (0x0B0000, 0x0B7FFF, 'New Zealand'), (0xC80000, 0xC87FFF, 'Mexico'),
        (0x888000, 0x88FFFF, 'Singapore'), (0x898000, 0x8983FF, 'Indonesia'),
    ]

    @staticmethod
    def icao_to_country(icao_hex):
        """Look up country from ICAO hex address prefix."""
        try:
            val = int(icao_hex, 16)
        except (ValueError, TypeError):
            return None
        for lo, hi, country in ADSBTracker.ICAO_RANGES:
            if lo <= val <= hi:
                return country
        return None

    def __init__(self, lat=0, lon=0):
        self.aircraft = {}  # icao -> aircraft dict
        self.lat = lat  # receiver lat (for surface position decoding)
        self.lon = lon  # receiver lon
        self.lock = threading.Lock()
        self.msg_count = 0
        self.start_time = time.time()
        self.max_range = 0  # furthest aircraft seen (km)
        self.country_stats = defaultdict(int)  # country → count

    def handle_message(self, msg_hex):
        """Process a raw ADS-B hex message."""
        msg = msg_hex.strip()
        if len(msg) < 28:
            return

        try:
            df = pms.df(msg)
        except Exception:
            return

        # We want DF17 (ADS-B) and DF11 (Mode S)
        if df not in (17, 11, 18):
            return

        try:
            icao = pms.icao(msg)
        except Exception:
            return

        if not icao:
            return

        self.msg_count += 1

        with self.lock:
            if icao not in self.aircraft:
                self.aircraft[icao] = {
                    'icao': icao,
                    'callsign': None,
                    'country': self.icao_to_country(icao),  # Derive from ICAO hex
                    'lat': None,
                    'lon': None,
                    'alt': None,
                    'spd': None,
                    'hdg': None,
                    'vsi': None,
                    'squawk': None,
                    'on_ground': False,
                    'last_seen': time.time(),
                    'msg_count': 0,
                    'trail': [],
                    'category': None,
                }

            ac = self.aircraft[icao]
            ac['last_seen'] = time.time()
            ac['msg_count'] += 1

            if df == 17 or df == 18:
                tc = pms.adsb.typecode(msg)

                # Aircraft identification (callsign)
                if 1 <= tc <= 4:
                    try:
                        cs = pms.adsb.callsign(msg)
                        if cs:
                            ac['callsign'] = cs.strip('_').strip()
                        ac['category'] = pms.adsb.category(msg)
                    except Exception:
                        pass

                # Airborne position
                elif 9 <= tc <= 18:
                    try:
                        alt = pms.adsb.altitude(msg)
                        ac['alt'] = alt * 0.3048 if alt else ac['alt']  # ft→m

                        # CPR decoding needs even/odd pair; use reference position
                        try:
                            lat, lon = pms.adsb.position_with_ref(msg, self.lat, self.lon)
                            if lat and lon and -90 <= lat <= 90 and -180 <= lon <= 180:
                                ac['lat'] = lat
                                ac['lon'] = lon
                                # Track max range
                                if self.lat and self.lon:
                                    d = self._haversine(self.lat, self.lon, lat, lon)
                                    if d > self.max_range:
                                        self.max_range = d
                                # Update country stats
                                if ac.get('country'):
                                    self.country_stats[ac['country']] = len([
                                        a for a in self.aircraft.values()
                                        if a.get('country') == ac['country']
                                        and a['lat'] and not a['on_ground']
                                        and time.time() - a['last_seen'] < 60
                                    ])
                                # Add to trail
                                trail = ac['trail']
                                trail.append({'lat': lat, 'lon': lon})
                                if len(trail) > 20:
                                    ac['trail'] = trail[-20:]
                        except Exception:
                            pass
                    except Exception:
                        pass

                # Surface position
                elif 5 <= tc <= 8:
                    ac['on_ground'] = True
                    try:
                        spd = pms.adsb.surface_velocity(msg)
                        if spd:
                            ac['spd'] = spd[0] * 0.514  # kts→m/s
                            ac['hdg'] = spd[1]
                    except Exception:
                        pass

                # Airborne velocity
                elif tc == 19:
                    try:
                        vel = pms.adsb.velocity(msg)
                        if vel:
                            ac['spd'] = vel[0] * 0.514 if vel[0] else ac['spd']  # kts→m/s
                            ac['hdg'] = vel[1] if vel[1] else ac['hdg']
                            ac['vsi'] = vel[2] * 0.00508 if vel[2] else ac['vsi']  # ft/min→m/s
                    except Exception:
                        pass

    @staticmethod
    def _haversine(lat1, lon1, lat2, lon2):
        """Calculate distance in km between two points."""
        R = 6371
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def get_aircraft_list(self):
        """Return list of active aircraft (seen in last 60s, airborne, with position)."""
        now = time.time()
        with self.lock:
            # Clean old entries
            stale = [k for k, v in self.aircraft.items() if now - v['last_seen'] > 120]
            for k in stale:
                del self.aircraft[k]

            return [
                {
                    'icao': ac['icao'],
                    'callsign': ac['callsign'],
                    'country': ac.get('country'),
                    'lat': ac['lat'],
                    'lon': ac['lon'],
                    'alt': ac['alt'],
                    'spd': ac['spd'],
                    'hdg': ac['hdg'],
                    'vsi': ac['vsi'],
                    'squawk': ac['squawk'],
                    'on_ground': ac['on_ground'],
                    'last_seen': ac['last_seen'],
                    'msg_count': ac['msg_count'],
                    'distance': round(self._haversine(self.lat, self.lon, ac['lat'], ac['lon']), 1) if self.lat and self.lon else None,
                }
                for ac in self.aircraft.values()
                if ac['lat'] and ac['lon']
                and not ac['on_ground']
                and now - ac['last_seen'] < 60
            ]

    def get_stats(self):
        """Return receiver statistics."""
        uptime = time.time() - self.start_time
        with self.lock:
            total = len(self.aircraft)
            active = [a for a in self.aircraft.values()
                      if a['lat'] and not a['on_ground']
                      and time.time() - a['last_seen'] < 60]
            airborne = len(active)
            # Country breakdown
            countries = defaultdict(int)
            for a in active:
                c = a.get('country') or 'Unknown'
                countries[c] += 1
            top_countries = sorted(countries.items(), key=lambda x: -x[1])[:10]

        return {
            'uptime_seconds': int(uptime),
            'total_messages': self.msg_count,
            'msg_per_second': round(self.msg_count / max(1, uptime), 1),
            'total_tracked': total,
            'airborne': airborne,
            'max_range_km': round(self.max_range, 1),
            'top_countries': top_countries,
            'timestamp': datetime.utcnow().isoformat() + 'Z',
        }


# ========== RTL-SDR Reader ==========
class RTLReader:
    """Reads raw ADS-B from rtl_adsb or dump1090."""

    def __init__(self, tracker, use_dump1090=False):
        self.tracker = tracker
        self.use_dump1090 = use_dump1090
        self.process = None
        self.running = False

    def start(self):
        self.running = True
        thread = threading.Thread(target=self._read_loop, daemon=True)
        thread.start()
        return thread

    def stop(self):
        self.running = False
        if self.process:
            self.process.terminate()

    def _read_loop(self):
        """Start RTL-SDR process and read decoded messages."""

        if self.use_dump1090:
            cmd = ['dump1090', '--raw', '--net-only', '--quiet']
            alt_cmd = ['readsb', '--raw', '--net-only', '--quiet']
        else:
            # rtl_adsb outputs hex messages directly
            cmd = ['rtl_adsb']
            alt_cmd = None

        try:
            print(f"🛰️  Starting: {' '.join(cmd)}")
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
        except FileNotFoundError:
            if alt_cmd:
                try:
                    print(f"⚠️  {cmd[0]} not found, trying: {' '.join(alt_cmd)}")
                    self.process = subprocess.Popen(
                        alt_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )
                except FileNotFoundError:
                    print(f"❌ Neither {cmd[0]} nor {alt_cmd[0]} found!")
                    print("   Install: sudo apt install rtl-sdr dump1090-mutability")
                    self.running = False
                    return
            else:
                print(f"❌ {cmd[0]} not found!")
                print("   Install: sudo apt install rtl-sdr")
                self.running = False
                return

        print("📡 SDR receiver running. Listening for ADS-B on 1090 MHz...")

        while self.running:
            line = self.process.stdout.readline()
            if not line:
                if self.process.poll() is not None:
                    print("⚠️  RTL process exited")
                    break
                continue

            line = line.strip()
            # rtl_adsb outputs lines like: *8D4840D6202CC371C32CE0576098;
            if line.startswith('*') and line.endswith(';'):
                msg = line[1:-1]
                self.tracker.handle_message(msg)
            elif len(line) >= 28 and all(c in '0123456789ABCDEFabcdef' for c in line):
                self.tracker.handle_message(line)


# ========== dump1090 Network Reader ==========
class Dump1090NetReader:
    """Reads from dump1090's raw TCP output (port 30002)."""

    def __init__(self, tracker, host='127.0.0.1', port=30002):
        self.tracker = tracker
        self.host = host
        self.port = port
        self.running = False

    def start(self):
        self.running = True
        thread = threading.Thread(target=self._read_loop, daemon=True)
        thread.start()
        return thread

    def stop(self):
        self.running = False

    def _read_loop(self):
        import socket
        print(f"📡 Connecting to dump1090 at {self.host}:{self.port}...")

        while self.running:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect((self.host, self.port))
                print(f"✅ Connected to dump1090 raw output")
                buf = ''

                while self.running:
                    try:
                        data = sock.recv(4096).decode('ascii', errors='ignore')
                        if not data:
                            break
                        buf += data
                        while '\n' in buf:
                            line, buf = buf.split('\n', 1)
                            line = line.strip()
                            if line.startswith('*') and line.endswith(';'):
                                self.tracker.handle_message(line[1:-1])

                    except socket.timeout:
                        continue

            except (ConnectionRefusedError, OSError) as e:
                print(f"⚠️  Cannot connect to dump1090: {e}")
                print("   Retrying in 5 seconds...")
                time.sleep(5)
            finally:
                try:
                    sock.close()
                except:
                    pass


# ========== Beast / SBS-1 BaseStation Reader ==========
class SBSReader:
    """Reads SBS-1 (BaseStation) format from dump1090 port 30003."""

    def __init__(self, tracker, host='127.0.0.1', port=30003):
        self.tracker = tracker
        self.host = host
        self.port = port
        self.running = False

    def start(self):
        self.running = True
        thread = threading.Thread(target=self._read_loop, daemon=True)
        thread.start()
        return thread

    def stop(self):
        self.running = False

    def _read_loop(self):
        import socket
        print(f"📡 Connecting to SBS output at {self.host}:{self.port}...")

        while self.running:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect((self.host, self.port))
                print(f"✅ Connected to SBS (BaseStation) output")
                buf = ''

                while self.running:
                    try:
                        data = sock.recv(4096).decode('ascii', errors='ignore')
                        if not data:
                            break
                        buf += data
                        while '\n' in buf:
                            line, buf = buf.split('\n', 1)
                            self._parse_sbs(line.strip())

                    except socket.timeout:
                        continue

            except (ConnectionRefusedError, OSError) as e:
                print(f"⚠️  Cannot connect to SBS: {e}")
                time.sleep(5)
            finally:
                try:
                    sock.close()
                except:
                    pass

    def _parse_sbs(self, line):
        """Parse SBS-1 BaseStation format."""
        parts = line.split(',')
        if len(parts) < 11 or parts[0] != 'MSG':
            return

        icao = parts[4].strip()
        if not icao:
            return

        with self.tracker.lock:
            if icao not in self.tracker.aircraft:
                self.tracker.aircraft[icao] = {
                    'icao': icao, 'callsign': None, 'lat': None, 'lon': None,
                    'alt': None, 'spd': None, 'hdg': None, 'vsi': None,
                    'squawk': None, 'on_ground': False, 'last_seen': time.time(),
                    'msg_count': 0, 'trail': [], 'category': None,
                }

            ac = self.tracker.aircraft[icao]
            ac['last_seen'] = time.time()
            ac['msg_count'] += 1

            msg_type = parts[1].strip()

            try:
                if msg_type == '1':  # ID
                    cs = parts[10].strip()
                    if cs:
                        ac['callsign'] = cs

                elif msg_type == '3':  # Airborne position
                    alt = parts[11].strip()
                    lat = parts[14].strip()
                    lon = parts[15].strip()
                    if alt:
                        ac['alt'] = float(alt) * 0.3048  # ft→m
                    if lat and lon:
                        ac['lat'] = float(lat)
                        ac['lon'] = float(lon)
                        ac['trail'].append({'lat': ac['lat'], 'lon': ac['lon']})
                        if len(ac['trail']) > 20:
                            ac['trail'] = ac['trail'][-20:]

                elif msg_type == '4':  # Airborne velocity
                    spd = parts[12].strip()
                    hdg = parts[13].strip()
                    vsi = parts[16].strip()
                    if spd:
                        ac['spd'] = float(spd) * 0.514  # kts→m/s
                    if hdg:
                        ac['hdg'] = float(hdg)
                    if vsi:
                        ac['vsi'] = float(vsi) * 0.00508  # ft/min→m/s

                elif msg_type == '6':  # Squawk
                    sq = parts[17].strip()
                    if sq:
                        ac['squawk'] = sq

                ground = parts[21].strip() if len(parts) > 21 else ''
                if ground == '-1':
                    ac['on_ground'] = True
                elif ground == '0':
                    ac['on_ground'] = False

            except (ValueError, IndexError):
                pass


# ========== Flask API Server ==========
def create_app(tracker, receiver_lat, receiver_lon):
    app = Flask(__name__)
    CORS(app)

    @app.route('/api/aircraft')
    def aircraft():
        """Return aircraft in OpenSky-compatible format for the web app."""
        ac_list = tracker.get_aircraft_list()
        # Convert to OpenSky states format
        states = []
        for ac in ac_list:
            states.append([
                ac['icao'],        # 0: icao24
                ac['callsign'],    # 1: callsign
                ac.get('country'), # 2: origin_country (from ICAO hex lookup)
                None,              # 3: time_position
                ac['last_seen'],   # 4: last_contact
                ac['lon'],         # 5: longitude
                ac['lat'],         # 6: latitude
                ac['alt'],         # 7: baro_altitude
                ac['on_ground'],   # 8: on_ground
                ac['spd'],         # 9: velocity
                ac['hdg'],         # 10: true_track
                ac['vsi'],         # 11: vertical_rate
                None,              # 12: sensors
                ac['alt'],         # 13: geo_altitude
                ac['squawk'],      # 14: squawk
                False,             # 15: spi
                0,                 # 16: position_source
            ])
        return jsonify({
            'time': int(time.time()),
            'states': states,
            'source': 'sdr',
            'receiver': {'lat': receiver_lat, 'lon': receiver_lon},
        })

    @app.route('/api/stats')
    def stats():
        return jsonify(tracker.get_stats())

    @app.route('/api/aircraft/raw')
    def aircraft_raw():
        """Return raw aircraft data (not OpenSky format)."""
        return jsonify(tracker.get_aircraft_list())

    @app.route('/api/coverage')
    def coverage():
        """Return range/coverage data for polar plot."""
        ac_list = tracker.get_aircraft_list()
        points = []
        for ac in ac_list:
            if ac.get('distance') is not None:
                bearing_val = 0
                if receiver_lat and receiver_lon and ac['lat'] and ac['lon']:
                    dlon = math.radians(ac['lon'] - receiver_lon)
                    y = math.sin(dlon) * math.cos(math.radians(ac['lat']))
                    x = (math.cos(math.radians(receiver_lat)) * math.sin(math.radians(ac['lat'])) -
                         math.sin(math.radians(receiver_lat)) * math.cos(math.radians(ac['lat'])) * math.cos(dlon))
                    bearing_val = (math.degrees(math.atan2(y, x)) + 360) % 360
                points.append({
                    'icao': ac['icao'],
                    'bearing': round(bearing_val, 1),
                    'distance': ac['distance'],
                    'alt': ac['alt'],
                })
        return jsonify({
            'points': points,
            'max_range': tracker.max_range,
            'receiver': {'lat': receiver_lat, 'lon': receiver_lon},
        })

    @app.route('/health')
    def health():
        return jsonify({'status': 'ok', 'source': 'sdr'})

    return app


# ========== Main ==========
def main():
    parser = argparse.ArgumentParser(description='✈️ SDR ADS-B Receiver for Planes in the Sky')
    parser.add_argument('--port', type=int, default=8090, help='HTTP server port (default: 8090)')
    parser.add_argument('--lat', type=float, default=0, help='Receiver latitude')
    parser.add_argument('--lon', type=float, default=0, help='Receiver longitude')
    parser.add_argument('--dump1090', action='store_true', help='Use dump1090 as backend')
    parser.add_argument('--dump1090-host', default='127.0.0.1', help='dump1090 host (default: 127.0.0.1)')
    parser.add_argument('--dump1090-port', type=int, default=30002, help='dump1090 raw port (default: 30002)')
    parser.add_argument('--sbs', action='store_true', help='Read SBS/BaseStation format (port 30003)')
    parser.add_argument('--sbs-port', type=int, default=30003, help='SBS port (default: 30003)')
    args = parser.parse_args()

    if not HAS_FLASK:
        print("❌ Flask is required. Run: pip install flask flask-cors")
        sys.exit(1)

    print("=" * 50)
    print("  ✈️  Planes in the Sky — SDR Receiver")
    print("=" * 50)

    tracker = ADSBTracker(lat=args.lat, lon=args.lon)

    # Start the appropriate reader
    if args.sbs:
        reader = SBSReader(tracker, args.dump1090_host, args.sbs_port)
        print(f"📻 Mode: SBS/BaseStation (port {args.sbs_port})")
    elif args.dump1090:
        if not HAS_PYMS:
            # If no pyModeS, connect to dump1090 network
            reader = Dump1090NetReader(tracker, args.dump1090_host, args.dump1090_port)
            print(f"📻 Mode: dump1090 network (port {args.dump1090_port})")
        else:
            reader = RTLReader(tracker, use_dump1090=True)
            print("📻 Mode: dump1090 local")
    else:
        if not HAS_PYMS:
            print("❌ pyModeS is required for direct RTL-SDR. Run: pip install pyModeS")
            print("   Or use --dump1090 or --sbs to connect to an existing decoder")
            sys.exit(1)
        reader = RTLReader(tracker)
        print("📻 Mode: rtl_adsb direct")

    reader.start()

    print(f"🌐 API server: http://localhost:{args.port}")
    print(f"📍 Receiver: {args.lat}, {args.lon}")
    print(f"\n   In the web app, tap 📡 SDR and enter:")
    print(f"   http://localhost:{args.port}")
    print()

    app = create_app(tracker, args.lat, args.lon)

    try:
        app.run(host='0.0.0.0', port=args.port, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
        reader.stop()


if __name__ == '__main__':
    main()
